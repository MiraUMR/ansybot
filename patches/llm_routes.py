from quart import Blueprint, Response, g, jsonify, request

from kirara_ai.config.config_loader import CONFIG_FILE, ConfigLoader
from kirara_ai.config.global_config import GlobalConfig, LLMPriorityConfig
from kirara_ai.llm.adapter import AutoDetectModelsProtocol
from kirara_ai.llm.llm_manager import LLMManager
from kirara_ai.llm.llm_registry import LLMAbility, LLMBackendRegistry
from kirara_ai.logger import get_logger
from kirara_ai.web.api.llm.models import (LLMAdapterConfigSchema, LLMAdapterTypes, LLMBackendCreateRequest,
                                          LLMBackendInfo, LLMBackendList, LLMBackendListResponse, LLMBackendResponse,
                                          LLMBackendUpdateRequest, LLMPriorityInfo, LLMPriorityResponse,
                                          LLMPriorityUpdateRequest)

from ...auth.middleware import require_auth
from pathlib import Path
import yaml

llm_bp = Blueprint("llm", __name__)
logger = get_logger("WebServer.LLM")
PRIORITY_UI_PATH = Path(__file__).resolve().parents[4] / "data" / "llm_priority_ui.html"
# Prefer mounted patch file next to routes when present
_PATCH_UI = Path("/app/data/llm_priority_ui.html")
_LOCAL_UI = Path(__file__).with_name("llm_priority_ui.html")


def _priority_ui_path() -> Path:
    for candidate in (_PATCH_UI, Path("data/llm_priority_ui.html"), _LOCAL_UI, PRIORITY_UI_PATH):
        if candidate.is_file():
            return candidate
    return _PATCH_UI


def _ensure_priority(config: GlobalConfig) -> LLMPriorityConfig:
    priority = getattr(config.llms, "priority", None)
    if priority is None:
        priority = LLMPriorityConfig()
        config.llms.priority = priority
    return priority


def _normalize_model_id(model_id) -> str | None:
    if isinstance(model_id, str):
        s = model_id.strip()
        return s or None
    if isinstance(model_id, dict):
        s = model_id.get("id") or model_id.get("name")
        return str(s).strip() if s else None
    for attr in ("id", "name"):
        if hasattr(model_id, attr):
            s = getattr(model_id, attr)
            if s:
                return str(s).strip()
    s = str(model_id).strip()
    return s if s and s != "None" else None


def _is_vision_name(name: str) -> bool:
    try:
        from kirara_ai.llm.model_ref import api_model_name
        n = (api_model_name(name) or name or "").lower().replace("_", "-")
    except Exception:
        n = (name or "").lower().replace("_", "-")
    keys = ("-vl", "vl-", "vision", "qwen-vl", "gpt-4o", "gemini-1.5", "gemini-2.0", "gemini-2.5")
    return any(k in n for k in keys)


def _merge_models_from_disk(config: GlobalConfig) -> None:
    """把磁盘 config 里模型管理的最新 models / priority 合并进内存，避免 WebUI 刚保存后本页仍旧。"""
    try:
        disk = ConfigLoader.load_config(CONFIG_FILE, GlobalConfig)
    except Exception as e:
        logger.warning(f"reload config for priority failed: {e}")
        return

    mem_by_name = {b.name: b for b in config.llms.api_backends}
    for db in disk.llms.api_backends:
        mb = mem_by_name.get(db.name)
        if mb is None:
            config.llms.api_backends.append(db)
            continue
        merged: list[str] = []
        seen: set[str] = set()
        for src in (list(mb.models or []), list(db.models or [])):
            for raw in src:
                mid = _normalize_model_id(raw)
                if mid and mid not in seen:
                    seen.add(mid)
                    merged.append(mid)
        mb.models = merged
        mb.enable = db.enable

    disk_priority = getattr(disk.llms, "priority", None)
    if disk_priority is not None:
        priority = _ensure_priority(config)
        priority.text = list(disk_priority.text or [])
        priority.vision = list(disk_priority.vision or [])


def _models_from_pools_yaml() -> list[str]:
    path = Path("data/llm_pools.yaml")
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for key in ("text", "vision"):
        for raw in data.get(key) or []:
            mid = _normalize_model_id(raw)
            if mid and mid not in seen:
                seen.add(mid)
                names.append(mid)
    return names


def _available_models(config: GlobalConfig, manager: LLMManager) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def _add(raw) -> None:
        mid = _normalize_model_id(raw)
        if mid and mid not in seen:
            seen.add(mid)
            names.append(mid)

    try:
        from kirara_ai.llm.model_ref import qualify_model
    except Exception:
        qualify_model = None  # type: ignore

    for backend in config.llms.api_backends:
        if not backend.enable:
            continue
        bname = backend.name or ""
        for model_id in backend.models or []:
            mid = _normalize_model_id(model_id)
            if not mid:
                continue
            key = qualify_model(bname, mid) if qualify_model else f"{bname}/{mid}"
            _add(key)
    for mid in _models_from_pools_yaml():
        _add(mid)
    try:
        for model_id in manager.get_supported_models(LLMAbility.TextChat) or []:
            _add(model_id)
    except Exception:
        pass
    try:
        vision_ability = getattr(LLMAbility, "TextImageMultiModal", None)
        if vision_ability is not None:
            for model_id in manager.get_supported_models(vision_ability) or []:
                _add(model_id)
    except Exception:
        pass
    return names


def _autofill_unused(priority: LLMPriorityConfig, available: list[str]) -> list[str]:
    """模型管理里已有、但还未进入任一优先级列表的模型，按名称自动归入文本/识图。
    同一裸模型名若已在任一平台出现，则不再重复并入其他平台。"""
    try:
        from kirara_ai.llm.model_ref import api_model_name
    except Exception:
        api_model_name = lambda x: x  # type: ignore

    used_refs = set(priority.text or []) | set(priority.vision or [])
    used_bare = {api_model_name(m) for m in used_refs}
    added: list[str] = []
    for mid in available:
        if mid in used_refs:
            continue
        bare = api_model_name(mid)
        if not bare or bare in used_bare:
            continue
        if _is_vision_name(mid):
            priority.vision.append(mid)
        else:
            priority.text.append(mid)
        used_refs.add(mid)
        used_bare.add(bare)
        added.append(mid)
    return added


def _bind_priority_models(
    config: GlobalConfig, refs: list[str]
) -> tuple[list[str], set[str]]:
    """把优先级里的模型规范成「平台/模型」，并写入对应后端的 models。

    返回 (规范化后的 refs, 被改动的后端名集合)。
    """
    try:
        from kirara_ai.llm.model_ref import qualify_model, set_backend_names, split_model_ref
    except Exception:
        return list(refs), set()

    backends = list(config.llms.api_backends or [])
    backends_by_name = {b.name: b for b in backends}
    set_backend_names(backends_by_name.keys())
    enabled = [b for b in backends if b.enable]
    touched: set[str] = set()
    normalized: list[str] = []

    for raw in refs:
        ref = (raw or "").strip()
        if not ref:
            continue
        backend_name, bare = split_model_ref(ref)
        if not bare:
            continue

        target = None
        if backend_name and backend_name in backends_by_name:
            target = backends_by_name[backend_name]
        else:
            owners = [
                b
                for b in enabled
                if bare in [m.strip() for m in (b.models or []) if isinstance(m, str)]
            ]
            if owners:
                target = owners[0]
            elif enabled:
                # 裸名/厂商前缀 id：默认绑到第一个启用后端（通常是阿里）
                target = enabled[0]

        if target is None:
            # 无可用后端时原样保留
            normalized.append(ref)
            continue

        names = [m.strip() for m in (target.models or []) if isinstance(m, str) and m.strip()]
        if bare not in names:
            names.append(bare)
            target.models = names
            touched.add(target.name)

        qualified = qualify_model(target.name, bare)
        if qualified not in normalized:
            normalized.append(qualified)

    return normalized, touched


async def _reload_backends(manager: LLMManager, names: set[str]) -> None:
    for name in names:
        try:
            if name in manager.backends:
                await manager.reload_backend(name)
            else:
                backend = next(
                    (b for b in manager.config.llms.api_backends if b.name == name),
                    None,
                )
                if backend and backend.enable:
                    manager.load_backend(name)
        except Exception as e:
            logger.warning(f"reload backend {name} after model bind failed: {e}")


def _sync_pools_yaml(text: list[str], vision: list[str]) -> None:
    path = Path("data/llm_pools.yaml")
    data = {}
    if path.is_file():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data["text"] = list(text)
    data["vision"] = list(vision)
    data.setdefault("max_failover", 8)
    data.setdefault("vision_fallback_to_text", True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


@llm_bp.route("/priority/ui", methods=["GET"])
async def priority_ui():
    path = _priority_ui_path()
    if not path.is_file():
        return jsonify({"error": "priority ui missing"}), 404
    return Response(path.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")


@llm_bp.route("/priority", methods=["GET"])
@require_auth
async def get_priority():
    try:
        config: GlobalConfig = g.container.resolve(GlobalConfig)
        manager: LLMManager = g.container.resolve(LLMManager)
        _merge_models_from_disk(config)
        priority = _ensure_priority(config)
        available = _available_models(config, manager)
        added = _autofill_unused(priority, available)
        if added:
            try:
                if priority.text:
                    config.defaults.llm_model = priority.text[0]
                ConfigLoader.save_config_with_backup(CONFIG_FILE, config)
                _sync_pools_yaml(list(priority.text or []), list(priority.vision or []))
                logger.info(f"auto-filled llm priority with models: {added}")
            except Exception as e:
                logger.warning(f"persist auto-filled priority failed: {e}")
        return LLMPriorityResponse(
            data=LLMPriorityInfo(
                text=list(priority.text or []),
                vision=list(priority.vision or []),
                available=available,
                added=added,
            )
        ).model_dump()
    except Exception as e:
        logger.opt(exception=e).error("Failed to get llm priority")
        return jsonify({"error": str(e)}), 500


@llm_bp.route("/priority", methods=["PUT"])
@require_auth
async def update_priority():
    try:
        config: GlobalConfig = g.container.resolve(GlobalConfig)
        manager: LLMManager = g.container.resolve(LLMManager)
        _merge_models_from_disk(config)
        body = LLMPriorityUpdateRequest(**(await request.get_json() or {}))
        text = [m.strip() for m in (body.text or []) if isinstance(m, str) and m.strip()]
        vision = [m.strip() for m in (body.vision or []) if isinstance(m, str) and m.strip()]
        # de-dupe keep order
        text = list(dict.fromkeys(text))
        vision = list(dict.fromkeys(vision))

        # 规范化为「平台/模型」，并写入对应服务商 models
        text, touched_t = _bind_priority_models(config, text)
        vision, touched_v = _bind_priority_models(config, vision)
        touched = touched_t | touched_v

        priority = _ensure_priority(config)
        priority.text = text
        priority.vision = vision
        if text:
            config.defaults.llm_model = text[0]

        ConfigLoader.save_config_with_backup(CONFIG_FILE, config)
        try:
            _sync_pools_yaml(text, vision)
        except Exception as e:
            logger.warning(f"sync llm_pools.yaml failed: {e}")

        if touched:
            await _reload_backends(manager, touched)

        return LLMPriorityResponse(
            data=LLMPriorityInfo(
                text=text,
                vision=vision,
                available=_available_models(config, manager),
            )
        ).model_dump()
    except Exception as e:
        logger.opt(exception=e).error("Failed to update llm priority")
        return jsonify({"error": str(e)}), 500


@llm_bp.route("/types", methods=["GET"])
@require_auth
async def get_adapter_types():
    """获取所有可用的适配器类型"""
    registry: LLMBackendRegistry = g.container.resolve(LLMBackendRegistry)
    return LLMAdapterTypes(types=registry.get_adapter_types()).model_dump()


@llm_bp.route("/backends", methods=["GET"])
@require_auth
async def list_backends():
    """获取所有后端列表"""
    try:
        config: GlobalConfig = g.container.resolve(GlobalConfig)
        backends = []
        for backend in config.llms.api_backends:
            backends.append(
                LLMBackendInfo(
                    name=backend.name,
                    adapter=backend.adapter,
                    config=backend.config,
                    enable=backend.enable,
                    models=backend.models,
                )
            )
        return LLMBackendListResponse(
            data=LLMBackendList(backends=backends)
        ).model_dump()
    except Exception as e:
        logger.opt(exception=e).error("Failed to list backends")
        return jsonify({"error": str(e)}), 500


@llm_bp.route("/backends/<backend_name>", methods=["GET"])
@require_auth
async def get_backend(backend_name: str):
    """获取指定后端信息"""
    try:
        config: GlobalConfig = g.container.resolve(GlobalConfig)
        backend = next(
            (b for b in config.llms.api_backends if b.name == backend_name), None
        )
        if not backend:
            return jsonify({"error": f"Backend {backend_name} not found"}), 404

        return LLMBackendResponse(
            data=LLMBackendInfo(
                name=backend.name,
                adapter=backend.adapter,
                config=backend.config,
                enable=backend.enable,
                models=backend.models,
            )
        ).model_dump()
    except Exception as e:
        logger.opt(exception=e).error("Failed to get backend")
        return jsonify({"error": str(e)}), 500


@llm_bp.route("/backends", methods=["POST"])
@require_auth
async def create_backend():
    """创建新的后端"""
    try:
        data = await request.get_json()
        request_data = LLMBackendCreateRequest(**data)

        config: GlobalConfig = g.container.resolve(GlobalConfig)
        manager: LLMManager = g.container.resolve(LLMManager)

        # 检查后端名称是否已存在
        if any(b.name == request_data.name for b in config.llms.api_backends):
            return (
                jsonify({"error": f"Backend {request_data.name} already exists"}),
                400,
            )

        # 创建新的后端配置
        backend = LLMBackendInfo(
            name=request_data.name,
            adapter=request_data.adapter,
            config=request_data.config,
            enable=request_data.enable,
            models=request_data.models,
        )

        # 添加到配置中
        config.llms.api_backends.append(backend)

        # 如果启用则加载后端
        if backend.enable:
            manager.load_backend(backend.name)

        ConfigLoader.save_config_with_backup(CONFIG_FILE, config)
        return LLMBackendResponse(data=backend).model_dump()
    except Exception as e:
        logger.opt(exception=e).error("Failed to create backend")
        return jsonify({"error": str(e)}), 500


@llm_bp.route("/backends/<backend_name>", methods=["PUT"])
@require_auth
async def update_backend(backend_name: str):
    """更新指定后端"""
    try:
        data = await request.get_json()
        request_data = LLMBackendUpdateRequest(**data)

        config: GlobalConfig = g.container.resolve(GlobalConfig)
        manager: LLMManager = g.container.resolve(LLMManager)

        # 查找要更新的后端
        backend_index = next(
            (
                i
                for i, b in enumerate(config.llms.api_backends)
                if b.name == backend_name
            ),
            -1,
        )
        if backend_index == -1:
            return jsonify({"error": f"Backend {backend_name} not found"}), 404

        # 创建更新后的后端配置
        updated_backend = LLMBackendInfo(
            name=request_data.name,
            adapter=request_data.adapter,
            config=request_data.config,
            enable=request_data.enable,
            models=request_data.models,
        )

        # 如果原后端已启用，先卸载
        if config.llms.api_backends[backend_index].enable:
            await manager.unload_backend(backend_name)

        # 更新配置
        config.llms.api_backends[backend_index] = updated_backend

        # 如果新配置启用则加载后端
        if updated_backend.enable:
            manager.load_backend(updated_backend.name)
        ConfigLoader.save_config_with_backup(CONFIG_FILE, config)
        return LLMBackendResponse(data=updated_backend).model_dump()
    except Exception as e:
        logger.opt(exception=e).error("Failed to update backend")
        return jsonify({"error": str(e)}), 500


@llm_bp.route("/backends/<backend_name>", methods=["DELETE"])
@require_auth
async def delete_backend(backend_name: str):
    """删除指定后端"""
    try:
        config: GlobalConfig = g.container.resolve(GlobalConfig)
        manager: LLMManager = g.container.resolve(LLMManager)

        # 查找要删除的后端
        backend_index = next(
            (
                i
                for i, b in enumerate(config.llms.api_backends)
                if b.name == backend_name
            ),
            -1,
        )
        if backend_index == -1:
            return jsonify({"error": f"Backend {backend_name} not found"}), 404

        backend = config.llms.api_backends[backend_index]
        # 如果后端已启用，要卸载
        if backend.enable:
            await manager.unload_backend(backend_name)
            
        # 从配置中删除
        deleted_backend = config.llms.api_backends.pop(backend_index)

        ConfigLoader.save_config_with_backup(CONFIG_FILE, config)
            
        return LLMBackendResponse(
            data=LLMBackendInfo(
                name=deleted_backend.name,
                adapter=deleted_backend.adapter,
                config=deleted_backend.config,
                enable=deleted_backend.enable,
                models=deleted_backend.models,
            )
        ).model_dump()
    except Exception as e:
        logger.opt(exception=e).error("Failed to delete backend")
        return jsonify({"error": str(e)}), 500


@llm_bp.route("/types/<adapter_type>/config-schema", methods=["GET"])
@require_auth
async def get_adapter_config_schema(adapter_type: str):
    """获取指定适配器类型的配置字段模式"""
    try:
        registry: LLMBackendRegistry = g.container.resolve(LLMBackendRegistry)
        config_class = registry.get_config_class(adapter_type)
        if not config_class:
            return jsonify({"error": f"Adapter type {adapter_type} not found"}), 404

        schema = config_class.model_json_schema()
        return LLMAdapterConfigSchema(configSchema=schema).model_dump()
    except Exception as e:
        logger.opt(exception=e).error("Failed to get adapter config schema")
        return jsonify({"error": str(e)}), 500


@llm_bp.route("/types/<adapter_type>/supports-auto-detect-models", methods=["GET"])
@require_auth
async def supports_auto_detect_models(adapter_type: str):
    """检查指定适配器类型是否支持自动检测模型"""
    try:
        registry: LLMBackendRegistry = g.container.resolve(LLMBackendRegistry)
        adapter_class = registry.get(adapter_type)
        if not adapter_class:
            return jsonify({"error": f"Adapter type {adapter_type} not found"}), 404
        if not issubclass(adapter_class, AutoDetectModelsProtocol):
            return (
                jsonify(
                    {
                        "error": f"Adapter type {adapter_type} does not support auto-detect models"
                    }
                ),
                400,
            )
        return jsonify({"supportsAutoDetectModels": True})
    except Exception as e:
        logger.opt(exception=e).error("Failed to check if adapter supports auto-detect models")
        return jsonify({"error": str(e)}), 500


@llm_bp.route("/backends/<backend_name>/auto-detect-models", methods=["GET"])
@require_auth
async def auto_detect_models(backend_name: str):
    """自动检测指定后端的模型列表"""
    try:
        manager: LLMManager = g.container.resolve(LLMManager)
        adapter = manager.get(backend_name)
        if not adapter:
            return jsonify({"error": f"Backend {backend_name} not found"}), 404
        if not isinstance(adapter, AutoDetectModelsProtocol):
            return (
                jsonify(
                    {
                        "error": f"Backend {backend_name} does not support auto-detect models"
                    }
                ),
                400,
            )
        models = await adapter.auto_detect_models()
        return jsonify({"models": models})
    except Exception as e:
        logger.opt(exception=e).error("Failed to auto-detect models")
        return jsonify({"error": str(e)}), 500
