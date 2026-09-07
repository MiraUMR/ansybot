"""语义分类 REST API（Quart Blueprint）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from pydantic import ValidationError

try:
    from quart import Blueprint, Response, request
    from kirara_ai.web.auth.middleware import require_auth
except Exception:  # pragma: no cover - 本地无 Kirara 时仍可 import 工具层
    Blueprint = object  # type: ignore
    Response = object  # type: ignore
    request = None  # type: ignore

    def require_auth(fn):  # type: ignore
        return fn


from .prompt_builder import build_classify_prompt
from .schemas import (
    CategoryCreate,
    CategoryUpdate,
    ClassifyIn,
    ClassifyOut,
    DetectorConfigUpdate,
    MatchedCategory,
    ReplyStyleCreate,
)
from . import yaml_store as store
from .yaml_store import IDLE_ID, YamlStoreError

UI_PATH = Path(__file__).with_name("ui.html")

semantic_bp = Blueprint("semantic_classify", __name__) if Blueprint is not object else None  # type: ignore
_MOUNTED = False


def mount_semantic_classify(app) -> bool:
    """幂等挂载；供 SemanticClassifyPlugin 或 GroupWorldStatePlugin 调用。"""
    global _MOUNTED
    if _MOUNTED or semantic_bp is None:
        return False
    app.register_blueprint(semantic_bp, url_prefix="/api/semantic-classify")
    _MOUNTED = True
    return True


# 兼容任务书 FastAPI 命名
router = semantic_bp

OPENAPI_SPEC: Dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {
        "title": "RP Bot Semantic Classify API",
        "version": "1.0.0",
        "description": "爱好/场景语义分类配置与试分类接口",
    },
    "paths": {
        "/api/semantic-classify/{persona}/categories": {
            "get": {"summary": "获取场景分类列表"},
            "post": {"summary": "新增场景分类"},
        },
        "/api/semantic-classify/{persona}/categories/{category_id}": {
            "put": {"summary": "更新场景分类"},
            "delete": {"summary": "删除场景分类"},
        },
        "/api/semantic-classify/{persona}/classify": {
            "post": {"summary": "测试命中并生成 Prompt"},
        },
        "/api/semantic-classify/{persona}/config": {
            "get": {"summary": "获取检测器配置"},
            "put": {"summary": "更新检测器配置"},
        },
        "/api/semantic-classify/{persona}/export": {
            "get": {"summary": "导出原始 YAML"},
        },
        "/api/semantic-classify/{persona}/reply-styles": {
            "get": {"summary": "列出回复风格（内置+自定义）"},
            "post": {"summary": "新增自定义回复风格"},
        },
        "/api/semantic-classify/{persona}/reply-styles/{style_id}": {
            "delete": {"summary": "删除自定义回复风格"},
        },
    },
}


def _err(message: str, code: int) -> Tuple[dict, int]:
    return {"error": message, "code": code}, code


def _from_validation(exc: ValidationError) -> Tuple[dict, int]:
    msg = "; ".join(
        f"{'.'.join(str(x) for x in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()
    )
    return _err(msg or "请求参数无效", 400)


def _import_classify():
    try:
        from kirara_ai.plugins.group_world_state import topic_classify as tc
    except Exception:
        from group_world_state import topic_classify as tc  # type: ignore
    classify_fn = getattr(tc, "classify", None) or getattr(tc, "classify_text")
    return tc, classify_fn


def _confidence(hit: Any) -> float:
    score = float(getattr(hit, "score", 0.0) or 0.0)
    detector = str(getattr(hit, "detector", "") or "")
    if getattr(hit, "is_idle", False) or str(getattr(hit, "category_id", "")) == IDLE_ID:
        return 0.0
    if detector == "embed":
        return round(min(1.0, max(0.0, score / 100.0)), 4)
    return round(min(1.0, max(0.0, score / 20.0)), 4)


def _find_raw_category(persona: str, category_id: str) -> Dict[str, Any]:
    doc = store.load_doc(persona)
    for cat in doc.get("categories") or []:
        if isinstance(cat, dict) and str(cat.get("id")) == category_id:
            return cat
    return {
        "id": category_id,
        "display_name": category_id,
        "reply_stance": "deflect",
        "mode_hints": [],
        "sample_lines": [],
        "forbid_pivot": False,
    }


if semantic_bp is not None:

    @semantic_bp.route("/ui", methods=["GET"])
    async def semantic_ui():
        html = UI_PATH.read_text(encoding="utf-8")
        return Response(
            html,
            mimetype="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @semantic_bp.route("/openapi.json", methods=["GET"])
    async def openapi_json():
        return OPENAPI_SPEC

    @semantic_bp.route("/docs", methods=["GET"])
    async def swagger_docs():
        html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>Semantic Classify API</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"/>
</head><body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
SwaggerUIBundle({ url: './openapi.json', dom_id: '#swagger-ui' });
</script>
</body></html>"""
        return Response(html, mimetype="text/html; charset=utf-8")

    @semantic_bp.route("/<persona>/categories", methods=["GET"])
    @require_auth
    async def list_categories(persona: str):
        try:
            items = store.list_categories(persona)
            return [c.model_dump() for c in items]
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"内部错误: {exc}", 500)

    @semantic_bp.route("/<persona>/categories", methods=["POST"])
    @require_auth
    async def create_category(persona: str):
        try:
            raw = await request.get_json(force=True, silent=True) or {}
            body = CategoryCreate.model_validate(raw)
            created = store.create_category(persona, body)
            return created.model_dump(), 201
        except ValidationError as exc:
            return _from_validation(exc)
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"内部错误: {exc}", 500)

    @semantic_bp.route("/<persona>/categories/<category_id>", methods=["PUT"])
    @require_auth
    async def update_category(persona: str, category_id: str):
        try:
            raw = await request.get_json(force=True, silent=True) or {}
            body = CategoryUpdate.model_validate(raw)
            updated = store.update_category(persona, category_id, body)
            return updated.model_dump()
        except ValidationError as exc:
            return _from_validation(exc)
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"内部错误: {exc}", 500)

    @semantic_bp.route("/<persona>/categories/<category_id>", methods=["DELETE"])
    @require_auth
    async def delete_category(persona: str, category_id: str):
        try:
            store.delete_category(persona, category_id)
            return Response(status=204)
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"内部错误: {exc}", 500)

    @semantic_bp.route("/<persona>/classify", methods=["POST"])
    @require_auth
    async def classify(persona: str):
        try:
            store.assert_persona(persona)
            raw = await request.get_json(force=True, silent=True) or {}
            body = ClassifyIn.model_validate(raw)
            _tc, classify_fn = _import_classify()
            hit = classify_fn(persona, body.text)
            cat_id = str(getattr(hit, "category_id", "") or IDLE_ID)
            raw_cat = dict(_find_raw_category(persona, cat_id))
            raw_cat["id"] = cat_id
            raw_cat["display_name"] = str(
                getattr(hit, "display_name", None) or raw_cat.get("display_name") or cat_id
            )
            raw_cat["reply_stance"] = str(
                getattr(hit, "stance", None) or raw_cat.get("reply_stance") or "soft"
            )
            if getattr(hit, "sample_lines", None):
                raw_cat["sample_lines"] = list(hit.sample_lines)
            is_hit = cat_id != IDLE_ID and not bool(getattr(hit, "is_idle", False))
            prompt = build_classify_prompt(category=raw_cat, input_text=body.text)
            out = ClassifyOut(
                matched_category=MatchedCategory(
                    id=cat_id,
                    display_name=str(raw_cat.get("display_name") or cat_id),
                    reply_stance=str(raw_cat.get("reply_stance") or "soft"),
                ),
                confidence=_confidence(hit),
                is_hit=is_hit,
                generated_prompt=prompt,
            )
            return out.model_dump()
        except ValidationError as exc:
            return _from_validation(exc)
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"分类引擎异常: {exc}", 500)

    @semantic_bp.route("/<persona>/config", methods=["GET"])
    @require_auth
    async def get_config(persona: str):
        try:
            return store.get_detector_config(persona)
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"内部错误: {exc}", 500)

    @semantic_bp.route("/<persona>/config", methods=["PUT"])
    @require_auth
    async def put_config(persona: str):
        try:
            raw = await request.get_json(force=True, silent=True) or {}
            body = DetectorConfigUpdate.model_validate(raw)
            return store.update_detector_config(persona, body.model_dump(exclude_unset=True))
        except ValidationError as exc:
            return _from_validation(exc)
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"内部错误: {exc}", 500)

    @semantic_bp.route("/<persona>/export", methods=["GET"])
    @require_auth
    async def export_yaml(persona: str):
        try:
            data = store.export_yaml_bytes(persona)
            return Response(
                data,
                mimetype="application/x-yaml; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{persona}_hobbies.yaml"'
                },
            )
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"内部错误: {exc}", 500)

    @semantic_bp.route("/<persona>/reply-styles", methods=["GET"])
    @require_auth
    async def list_reply_styles(persona: str):
        try:
            items = store.list_reply_styles(persona)
            return [c.model_dump() for c in items]
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"内部错误: {exc}", 500)

    @semantic_bp.route("/<persona>/reply-styles", methods=["POST"])
    @require_auth
    async def create_reply_style(persona: str):
        try:
            raw = await request.get_json(force=True, silent=True) or {}
            body = ReplyStyleCreate.model_validate(raw)
            created = store.create_reply_style(persona, body)
            return created.model_dump(), 201
        except ValidationError as exc:
            return _from_validation(exc)
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"内部错误: {exc}", 500)

    @semantic_bp.route("/<persona>/reply-styles/<style_id>", methods=["DELETE"])
    @require_auth
    async def delete_reply_style(persona: str, style_id: str):
        try:
            store.delete_reply_style(persona, style_id)
            return Response(status=204)
        except YamlStoreError as exc:
            return _err(exc.message, exc.code)
        except Exception as exc:
            return _err(f"内部错误: {exc}", 500)
