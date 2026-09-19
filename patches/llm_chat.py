import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Tuple
from abc import ABC, abstractmethod

import yaml

from kirara_ai.config.global_config import GlobalConfig
from kirara_ai.im.message import ImageMessage, IMMessage, MessageElement, TextMessage
from kirara_ai.im.sender import ChatSender
from kirara_ai.ioc.container import DependencyContainer
from kirara_ai.llm.format import LLMChatMessage, LLMChatTextContent
from kirara_ai.llm.format.message import LLMChatContentPartType, LLMChatImageContent
from kirara_ai.llm.format.request import LLMChatRequest
from kirara_ai.llm.format.response import LLMChatResponse
from kirara_ai.llm.llm_manager import LLMManager
from kirara_ai.llm.llm_registry import LLMAbility
from kirara_ai.logger import get_logger
from kirara_ai.media.manager import MediaManager
from kirara_ai.memory.composes.base import ComposableMessageType
from kirara_ai.workflow.core.block import Block, Input, Output, ParamMeta
from kirara_ai.workflow.core.execution.executor import WorkflowExecutor

_VISION_CONTEXT_HINT = (
    "\n\n（对方发了图片。先看清这一张里实际有什么，再按这一张反应。"
    "近期聊天只用来避免叫错人、接上刚说过的话，不要把上一轮看图的句子、梗、反应模板套过来。"
    "不要用括号写动作旁白。"
    "若图里的人明显像你本人（或很像你的二创/截图/表情包）：直接按「看到自己」反应即可，"
    "不要把图解释成别人拍的、P 的、偷存的，也不要点名无关的人来编因果关系；"
    "除非对方原文明确提到某人与这张图有关。"
    "不要为了找同伴而说「截图发给她 / 拉她看」；对方没点同伴就别拐。"
    "若图是同伴或其他人，也不要硬扯无关的人。）"
)

_POOLS_LOGGER = get_logger("LLMPools")
_POOLS_CACHE: Optional[Dict[str, Any]] = None
_POOLS_MTIME: float = 0.0

_QUOTA_MARKERS = (
    "insufficient_quota",
    "insufficient_balance",
    "quota",
    "rate limit",
    "rate_limit",
    "too many requests",
    "429",
    "401",
    "402",
    "404",
    "arrearage",
    "balance",
    "timeout",
    "timed out",
    "exceeded",
    "throttl",
    "allocation",
    "billing",
    "overloaded",
    "capacity",
    "no available",
    "model not found",
    "model_not_found",
    "model not exist",
    "does not exist",
    "not exist",
    "unpurchased",
    "access denied",
    "accessdenied",
    "forbidden",
    "unexpected item type",
    "does not support image",
)

_VISION_NAME_MARKERS = (
    "-vl",
    "vl-",
    "vl_",
    "_vl",
    "vision",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "qwen3-vl",
)


def model_name_options_provider(container: DependencyContainer, block: Block) -> List[str]:
    llm_manager: LLMManager = container.resolve(LLMManager)
    return sorted(llm_manager.get_supported_models(LLMAbility.TextChat))


def _load_llm_pools() -> Dict[str, Any]:
    """读取 data/llm_pools.yaml；文件变更时自动重载。"""
    global _POOLS_CACHE, _POOLS_MTIME
    path = Path("data/llm_pools.yaml")
    if not path.is_file():
        return {
            "source": "config",
            "text": [],
            "vision": [],
            "vision_fallback_to_text": True,
            "max_failover": 8,
        }
    try:
        mtime = path.stat().st_mtime
        if _POOLS_CACHE is not None and mtime == _POOLS_MTIME:
            return _POOLS_CACHE
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("source", "config")
        data.setdefault("vision_fallback_to_text", True)
        data.setdefault("max_failover", 8)
        _POOLS_CACHE = data
        _POOLS_MTIME = mtime
        return _POOLS_CACHE
    except Exception as e:
        _POOLS_LOGGER.warning(f"failed to load llm_pools.yaml: {e}")
        return {
            "source": "config",
            "text": [],
            "vision": [],
            "vision_fallback_to_text": True,
            "max_failover": 8,
        }


def _is_vision_model(model_id: str) -> bool:
    # 用裸模型名判断，忽略「后端/」前缀
    try:
        from kirara_ai.llm.model_ref import api_model_name
        name = (api_model_name(model_id) or model_id or "").lower()
    except Exception:
        name = (model_id or "").lower()
    return any(m in name for m in _VISION_NAME_MARKERS)


def _models_from_management(config: GlobalConfig, *, vision: bool) -> List[str]:
    """按模型管理（启用后端 + models 列表顺序）收集候选，带平台前缀。"""
    out: List[str] = []
    seen = set()
    try:
        from kirara_ai.llm.model_ref import qualify_model
    except Exception:
        qualify_model = None  # type: ignore
    for backend in getattr(getattr(config, "llms", None), "api_backends", None) or []:
        if not getattr(backend, "enable", True):
            continue
        bname = getattr(backend, "name", "") or ""
        for model_id in getattr(backend, "models", None) or []:
            if not model_id:
                continue
            key = qualify_model(bname, model_id) if qualify_model else f"{bname}/{model_id}"
            if key in seen:
                continue
            if vision != _is_vision_model(key):
                continue
            seen.add(key)
            out.append(key)
    return out


def _default_model_id(config: Optional[GlobalConfig]) -> Optional[str]:
    if not config:
        return None
    name = getattr(getattr(config, "defaults", None), "llm_model", None)
    return (name or "").strip() or None


def _priority_from_config(config: Optional[GlobalConfig], *, vision: bool) -> List[str]:
    if not config:
        return []
    priority = getattr(getattr(config, "llms", None), "priority", None)
    if not priority:
        return []
    raw = getattr(priority, "vision" if vision else "text", None)
    if raw is None and isinstance(priority, dict):
        raw = priority.get("vision" if vision else "text")
    return [m for m in (raw or []) if isinstance(m, str) and m]


def _resolve_model_candidates(
    *,
    config: Optional[GlobalConfig],
    pools: Dict[str, Any],
    preferred: Optional[str],
    vision: bool,
    enable_failover: bool,
) -> List[str]:
    """
    优先级（可自由配置）：
    1. 工作流显式指定的 model_name / vision_model_name（若有）
    2. data/llm_pools.yaml 的 text/vision（非空则整表作为优先级，热更新）
    3. config.yaml → llms.priority.text / vision（模型管理旁的优先级配置）
    4. 回退：defaults.llm_model + 后端 models 列表顺序
    """
    pools_list = [m for m in (pools.get("vision" if vision else "text") or []) if m]
    config_priority = _priority_from_config(config, vision=vision)
    management_pool = _models_from_management(config, vision=vision) if config else []

    if pools_list:
        base_pool = list(pools_list)
    elif config_priority:
        base_pool = list(config_priority)
    else:
        base_pool = list(management_pool)
        if not vision:
            default_id = _default_model_id(config)
            if default_id and default_id not in base_pool:
                base_pool.insert(0, default_id)

    heads: List[str] = []
    if preferred:
        heads.append(preferred)

    candidates = _ordered_unique(None, heads + base_pool)
    if not candidates and not vision:
        default_id = _default_model_id(config)
        if default_id:
            candidates = [default_id]

    if not enable_failover:
        return candidates[:1]

    max_failover = int(pools.get("max_failover") or 8)
    if max_failover > 0:
        candidates = candidates[:max_failover]
    return candidates


def _prompt_has_images(prompt: List[LLMChatMessage]) -> bool:
    for msg in prompt or []:
        for part in getattr(msg, "content", None) or []:
            if isinstance(part, LLMChatImageContent):
                return True
    return False


def _prompt_wants_phone_mode(prompt: List[LLMChatMessage]) -> bool:
    """仅当真正注入 mode_phone 时提高 temperature。

    注意：不要匹配 Base 文案里的说明性字样（如 interaction_mode=phone），
    否则会误判并把 temperature=0.9 打进 LLMChatRequest（schema 要 int）导致整轮失败。
    """
    for msg in prompt or []:
        for part in getattr(msg, "content", None) or []:
            text = getattr(part, "text", None) or ""
            if "PHONE MODE ACTIVE" in text or "BRACKET_ACTIONS_DISABLED" in text:
                return True
    return False


def _strip_images(prompt: List[LLMChatMessage]) -> List[LLMChatMessage]:
    out: List[LLMChatMessage] = []
    for msg in prompt or []:
        parts = []
        for part in getattr(msg, "content", None) or []:
            if isinstance(part, LLMChatImageContent):
                continue
            parts.append(part)
        if not parts:
            parts = [LLMChatTextContent(text="[图片]")]
        cloned = deepcopy(msg)
        cloned.content = parts
        out.append(cloned)
    return out


_AUTH_MARKERS = (
    "invalid_api_key",
    "incorrect api key",
    "invalid api key",
    "unauthorized",
    "authentication",
    "api key provided",
)


def _is_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "401" in text:
        return True
    return any(m in text for m in _AUTH_MARKERS)


def _backend_of(model_id: str) -> str:
    try:
        from kirara_ai.llm.model_ref import split_model_ref

        backend, _ = split_model_ref(model_id)
        return backend or ""
    except Exception:
        if "/" in (model_id or ""):
            return model_id.split("/", 1)[0]
        return ""


def _is_failover_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(m in text for m in _QUOTA_MARKERS)


def _ordered_unique(preferred: Optional[str], pool: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for name in ([preferred] if preferred else []) + list(pool or []):
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _chat_with_model_failover(
    llm_manager: LLMManager,
    candidates: List[str],
    prompt: List[LLMChatMessage],
    logger,
    *,
    temperature: Optional[int] = None,
) -> Tuple[LLMChatResponse, str]:
    last_err: Optional[BaseException] = None
    tried: List[str] = []
    skip_backends = set()
    for model_id in candidates:
        backend = _backend_of(model_id)
        if backend and backend in skip_backends:
            logger.warning(f"skip model on auth-failed backend={backend}: {model_id}")
            continue
        llm = llm_manager.get_llm(model_id)
        if not llm:
            logger.warning(f"model not registered, skip: {model_id}")
            continue
        tried.append(model_id)
        try:
            logger.info(f"llm try model={model_id}")
            req_kwargs = {"messages": prompt, "model": model_id}
            if temperature is not None:
                req_kwargs["temperature"] = temperature
            resp = llm.chat(LLMChatRequest(**req_kwargs))
            if model_id != candidates[0]:
                logger.info(f"llm failover success model={model_id} tried={tried}")
            return resp, model_id
        except Exception as e:
            last_err = e
            if _is_auth_error(e) and backend:
                skip_backends.add(backend)
                logger.warning(
                    f"llm auth failed backend={backend}, skip rest of this provider: {e}"
                )
                continue
            if _is_failover_error(e):
                logger.warning(f"llm failover from {model_id}: {e}")
                continue
            logger.error(f"llm non-retryable error model={model_id}: {e}")
            raise
    raise RuntimeError(
        f"all models failed tried={tried} last={last_err}"
    ) from last_err


def _extract_group_name(user_msg: IMMessage) -> str:
    raw = user_msg.raw_message
    if raw is None:
        return ""
    if isinstance(raw, dict):
        return str(raw.get("group_name") or raw.get("groupName") or "")
    name = getattr(raw, "group_name", None)
    if name:
        return str(name)
    getter = getattr(raw, "get", None)
    if callable(getter):
        try:
            return str(getter("group_name") or "")
        except Exception:
            return ""
    return ""


def _safe_public_name(name: str) -> str:
    s = (name or "").strip()
    if not s or (s.isdigit() and len(s) >= 5):
        return "眼前的人"
    return s


class ChatMessageConstructor(Block):
    name = "chat_message_constructor"
    inputs = {
        "user_msg": Input("user_msg", "本轮消息", IMMessage, "用户消息"),
        "user_prompt_format": Input(
            "user_prompt_format", "本轮消息格式", str, "本轮消息格式", default=""
        ),
        "memory_content": Input("memory_content", "历史消息对话", List[ComposableMessageType], "历史消息对话"),
        "system_prompt_format": Input(
            "system_prompt_format", "系统提示词", str, "系统提示词", default=""
        ),
        "dialogue_target": Input(
            "dialogue_target",
            "对话对象",
            str,
            "同伴或眼前的人，写入 {dialogue_target}",
            nullable=True,
            default="眼前的人",
        ),
        "user_prompt_text": Input(
            "user_prompt_text",
            "本轮注入文覆盖",
            str,
            "若非空则覆盖格式化后的 user prompt（环境旁白等）",
            nullable=True,
            default="",
        ),
        "current_scene": Input(
            "current_scene",
            "当前场景",
            str,
            "注入 {current_scene}，环境缓冲 XML",
            nullable=True,
            default="",
        ),
        "critical_instruction": Input(
            "critical_instruction",
            "P0 层级锁",
            str,
            "非空则追加到系统提示末尾，覆盖低层接话规则",
            nullable=True,
            default="",
        ),
    }
    outputs = {
        "llm_msg": Output(
            "llm_msg", "LLM 对话记录", List[LLMChatMessage], "LLM 对话记录"
        )
    }
    container: DependencyContainer

    def substitute_variables(self, text: str, executor: WorkflowExecutor) -> str:
        def replace_var(match):
            var_path = match.group(1).split(".")
            var_name = var_path[0]
            value = executor.get_variable(var_name, match.group(0))
            for attr in var_path[1:]:
                try:
                    if isinstance(value, dict):
                        value = value.get(attr, match.group(0))
                    elif hasattr(value, attr):
                        value = getattr(value, attr)
                    else:
                        return match.group(0)
                except Exception:
                    return match.group(0)
            return str(value)

        return re.sub(r"\{([^}]+)\}", replace_var, text)

    def execute(
        self,
        user_msg: IMMessage,
        memory_content: str,
        system_prompt_format: str = "",
        user_prompt_format: str = "",
        dialogue_target: Optional[str] = None,
        user_prompt_text: Optional[str] = None,
        current_scene: Optional[str] = None,
        critical_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        executor = self.container.resolve(WorkflowExecutor)

        scene = (current_scene or "").strip() or "（暂无额外环境音。）"
        speaker = _safe_public_name(user_msg.sender.display_name or "")
        target = re.sub(
            r"[（(][^）)]*\d{5,}[^）)]*[）)]", "", (dialogue_target or "").strip()
        ).strip(" ，,")
        if not target or (target.isdigit() and len(target) >= 5):
            target = "眼前的人"
        replacements = {
            "{current_date_time}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "{user_msg}": user_msg.content,
            "{user_name}": speaker,
            "{user_id}": "",
            "{group_id}": "",
            "{group_name}": _extract_group_name(user_msg) or "当下",
            "{dialogue_target}": target or "眼前的人",
            "{current_scene}": scene,
        }

        if isinstance(memory_content, list) and all(isinstance(item, str) for item in memory_content):
            replacements["{memory_content}"] = "\n".join(memory_content)

        for old, new in replacements.items():
            system_prompt_format = system_prompt_format.replace(old, new)
            user_prompt_format = user_prompt_format.replace(old, new)

        system_prompt = self.substitute_variables(system_prompt_format, executor)
        lock = (critical_instruction or "").strip()
        if lock:
            system_prompt = f"{system_prompt.rstrip()}\n\n{lock}\n"
        override = (user_prompt_text or "").strip()
        if override:
            user_prompt = override
        else:
            user_prompt = self.substitute_variables(user_prompt_format, executor)

        images = list(user_msg.images or [])
        # 环境旁白回合不带原图进对话（避免把外人身份带回来）；仍允许被点到时带图
        if override.startswith(("【当前环境】", "【系统】", "【当前场面】")):
            images = []

        prompt_text = user_prompt
        if images:
            desc_bits = []
            for image in images:
                try:
                    desc = (image.get_description() or "").strip()
                except Exception:
                    desc = ""
                if desc and not _looks_like_voice_caption(desc):
                    desc_bits.append(desc)
            if desc_bits:
                prompt_text = f"{prompt_text}\n[已识别图片内容: {'；'.join(desc_bits)}]"
            prompt_text = f"{prompt_text}{_VISION_CONTEXT_HINT}"

        content: List[LLMChatContentPartType] = [LLMChatTextContent(text=prompt_text)]
        for image in images:
            content.append(LLMChatImageContent(media_id=image.media_id))

        llm_msg = [
            LLMChatMessage(role="system", content=[LLMChatTextContent(text=system_prompt)]),
        ]
        
        if isinstance(memory_content, list) and all(isinstance(item, LLMChatMessage) for item in memory_content):
            llm_msg.extend(memory_content) # type: ignore
            
        llm_msg.append(LLMChatMessage(role="user", content=content))
        return {"llm_msg": llm_msg}


_VISION_VOICE_LEAK_RE = re.compile(
    r"发给|截图|soyorin|小爱音|走不动|某人|拉她|给她看",
    re.IGNORECASE,
)


def _looks_like_voice_caption(text: str) -> bool:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return False
    if _VISION_VOICE_LEAK_RE.search(raw):
        return True
    return len(raw) >= 40


def _vision_caption_from_reply(reply: str) -> str:
    """记忆里只留短物象，不把整段角色回复当图片说明。"""
    text = re.sub(r"\s+", " ", (reply or "").strip())
    if not text:
        return "已看过图"
    head = re.split(r"[。？?\n]", text, maxsplit=1)[0].strip("，,。！!?—-… ")
    if len(head) < 8:
        bits = [p.strip() for p in re.split(r"[。！？!?\n]", text) if p.strip()]
        head = "。".join(bits[:2]).strip("，,。！!?—-… ")
    if not head or _looks_like_voice_caption(head):
        cleaned = _VISION_VOICE_LEAK_RE.sub(" ", head or text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip("，,。！!?—-… ")
        if 4 <= len(cleaned) <= 24:
            return cleaned
        return "已看过图"
    return head[:36]


def _assistant_plain_text(resp: LLMChatResponse) -> str:
    parts: List[str] = []
    for part in getattr(getattr(resp, "message", None), "content", None) or []:
        if isinstance(part, LLMChatTextContent) and part.text:
            parts.append(part.text)
    text = "\n".join(parts)
    text = re.sub(r"<break>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class ChatCompletion(Block):
    name = "chat_completion"
    inputs = {
        "prompt": Input("prompt", "LLM 对话记录", List[LLMChatMessage], "LLM 对话记录")
    }
    outputs = {"resp": Output("resp", "LLM 对话响应", LLMChatResponse, "LLM 对话响应")}
    container: DependencyContainer

    def __init__(
        self,
        model_name: Annotated[
            Optional[str],
            ParamMeta(
                label="模型 ID",
                description="留空则用模型管理的默认模型 defaults.llm_model，并按后端 models 顺序自动切换",
                options_provider=model_name_options_provider,
            ),
        ] = None,
        vision_model_name: Annotated[
            Optional[str],
            ParamMeta(label="识图模型 ID", description="有图时的首选识图模型；空则从模型管理里的 VL 模型自动选"),
        ] = None,
        enable_model_failover: Annotated[
            bool,
            ParamMeta(label="额度自动切换", description="额度/限流失败时按模型管理中的模型列表自动切换"),
        ] = True,
    ):
        self.model_name = model_name
        self.vision_model_name = vision_model_name
        self.enable_model_failover = enable_model_failover
        self.logger = get_logger("ChatCompletionBlock")

    def execute(self, prompt: List[LLMChatMessage]) -> Dict[str, Any]:
        llm_manager = self.container.resolve(LLMManager)
        try:
            config = self.container.resolve(GlobalConfig)
        except Exception:
            config = getattr(llm_manager, "config", None)

        pools = _load_llm_pools()
        vision_fallback = bool(pools.get("vision_fallback_to_text", True))
        has_images = _prompt_has_images(prompt)

        if has_images:
            candidates = _resolve_model_candidates(
                config=config,
                pools=pools,
                preferred=(self.vision_model_name or "").strip() or None,
                vision=True,
                enable_failover=self.enable_model_failover,
            )
            mode = "vision"
            self.logger.info(f"prompt has images, use vision candidates: {candidates}")
        else:
            preferred = (self.model_name or "").strip() or None
            candidates = _resolve_model_candidates(
                config=config,
                pools=pools,
                preferred=preferred,
                vision=False,
                enable_failover=self.enable_model_failover,
            )
            if not preferred:
                default_id = _default_model_id(config)
                if default_id:
                    self.logger.info(f"Model id unspecified, using defaults.llm_model: {default_id}")
            mode = "text"

        if not candidates:
            raise ValueError(
                "No available LLM models found (check 模型管理 defaults.llm_model / backends.models)"
            )

        try:
            phone = _prompt_wants_phone_mode(prompt)
            # Kirara LLMChatRequest.temperature 类型为 Optional[int]，不能传 0.9
            temp = 1 if phone else None
            if phone:
                self.logger.info("phone mode detected → temperature=1")
            resp, used = _chat_with_model_failover(
                llm_manager, candidates, prompt, self.logger, temperature=temp
            )
            self.logger.info(f"chat ok mode={mode} model={used}")
            self._log_token_usage(prompt, resp, used, mode)
            if mode in ("vision", "vision_degraded"):
                self._persist_vision_context(prompt, resp)
            return {"resp": resp}
        except Exception as e:
            if mode == "vision" and vision_fallback and self.enable_model_failover:
                text_candidates = _resolve_model_candidates(
                    config=config,
                    pools=pools,
                    preferred=(self.model_name or "").strip() or None,
                    vision=False,
                    enable_failover=True,
                )
                if text_candidates:
                    self.logger.warning(
                        f"vision pool exhausted, fallback to text without images: {e}"
                    )
                    stripped = _strip_images(prompt)
                    resp, used = _chat_with_model_failover(
                        llm_manager, text_candidates, stripped, self.logger
                    )
                    self.logger.info(f"chat ok mode=vision_degraded model={used}")
                    self._log_token_usage(stripped, resp, used, "vision_degraded")
                    self._persist_vision_context(prompt, resp)
                    return {"resp": resp}
            raise

    def _log_token_usage(
        self,
        prompt: List[LLMChatMessage],
        resp: LLMChatResponse,
        model_id: str,
        mode: str,
    ) -> None:
        try:
            from kirara_ai.plugins.group_world_state.token_meter import format_chat_token_report

            self.logger.info(
                format_chat_token_report(
                    prompt, model=model_id, mode=mode, resp=resp, purpose="chat"
                )
            )
        except Exception as exc:
            usage = getattr(resp, "usage", None)
            pt = getattr(usage, "prompt_tokens", 0) if usage else 0
            ct = getattr(usage, "completion_tokens", 0) if usage else 0
            tt = getattr(usage, "total_tokens", 0) if usage else 0
            self.logger.info(
                f"token usage model={model_id} mode={mode} "
                f"prompt 消耗了 {pt} token，completion 消耗了 {ct} token，合计 {tt} token "
                f"(拆分失败: {exc})"
            )

    def _persist_vision_context(self, prompt: List[LLMChatMessage], resp: LLMChatResponse) -> None:
        media_ids: List[str] = []
        for msg in prompt or []:
            for part in getattr(msg, "content", None) or []:
                if isinstance(part, LLMChatImageContent) and part.media_id:
                    if part.media_id not in media_ids:
                        media_ids.append(part.media_id)
        if not media_ids:
            return
        summary = _vision_caption_from_reply(_assistant_plain_text(resp))
        try:
            media_manager = self.container.resolve(MediaManager)
        except Exception as e:
            self.logger.warning(f"vision desc skip, no MediaManager: {e}")
            return
        for media_id in media_ids:
            try:
                media = media_manager.get_media(media_id)
                if not media:
                    self.logger.warning(f"vision desc skip, media missing: {media_id}")
                    continue
                old = (media.description or "").strip()
                if (
                    old
                    and old not in ("用户发送了一张图片", "已看过图")
                    and not _looks_like_voice_caption(old)
                    and len(old) >= 4
                ):
                    continue
                media.description = summary
                self.logger.info(f"vision desc saved media={media_id}: {summary[:80]}")
            except Exception as e:
                self.logger.warning(f"vision desc save failed {media_id}: {e}")


class ChatResponseConverter(Block):
    name = "chat_response_converter"
    inputs = {"resp": Input("resp", "LLM 响应", LLMChatResponse, "LLM 响应")}
    outputs = {"msg": Output("msg", "IM 消息", IMMessage, "IM 消息")}
    container: DependencyContainer

    def execute(self, resp: LLMChatResponse) -> Dict[str, Any]:
        message_elements: List[MessageElement] = []

        for part in resp.message.content:
            if isinstance(part, LLMChatTextContent):
                text = (part.text or "").strip()
                if text == "[NO_REPLY]" or text.upper() == "NO_REPLY":
                    continue
                for element in text.split("<break>"):
                    chunk = element.strip()
                    if not chunk or chunk == "[NO_REPLY]":
                        continue
                    message_elements.append(TextMessage(chunk))
            elif isinstance(part, LLMChatImageContent):
                message_elements.append(ImageMessage(media_id=part.media_id))
        msg = IMMessage(sender=ChatSender.get_bot_sender(), message_elements=message_elements)
        return {"msg": msg}

class ExampleFunction(Block, ABC):
    """
    这个块是抽象function block，没有实际功能，你可以继承这个类，也可以参考这个类自己实现（遵从inputs, outputs格式约定）。
    """
    name = "tool"
    inputs = {
        "im_msg": Input("im_msg", "im 消息", IMMessage, "im 消息", True),
        "tool_call": Input("call_tools", "llm 回应", LLMChatResponse, "接收llm 的函数调用请求，你应该执行函数调用", True),
    }
    outputs = {
        "send_memory": Output("send_memory", "发送记忆模块", list[LLMChatMessage], "你应该在将函数调用期间的llm对话记录存储到记忆模块中"),
        # TODO: 请将所有LLMChatMessage 整合为一个LLMChatRequest。包含tool调用过程中的toolCallContent和toolResultContent。
        # EXAMPLE: 将接收到的call_tools: LLMChatResponse 中LLMChatMessage提取出来，设定role为assistance, 
        # 然后将所有函数调用结果按照LLMChaMessage(role="tool", content=[LLMToolResultContent])，整合为另外一个LLMChatMessage，拼接到上次构建的LLMChatRequest中。
        "request_body": Output("tool_result", "工具回应", LLMChatRequest, "请将全部上下文信息整合为LLMChatRequest")
    }
    container: DependencyContainer

    @abstractmethod
    def __init__(self):
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> dict[str, Any]:
        return super().execute(**kwargs)
    
class FunctionCalling(Block):
    """
    这个类只负责联系llm, 请将tools变量或者将tool_result变量整合为LLMChatRequest传入。注意同时传入tool_call和tool_result信息。
    注意: 你实现的function block 应该将too_result存入memory中, 本块不会自动存入函数调用期间的llm对话记录.

    具体block信息流转流程图将放置于后续教程中。详情请参见kirara wiki function calling部分。
    """
    name = "function_calling"
    inputs = {
        "request_body": Input("request_body", "llm 函数调用请求体", LLMChatRequest, "传递一个规范的函数调用请求体"),
    }
    outputs = {
        "resp": Output("resp", "llm 回应", LLMChatResponse, "返回的response, llm认为无需调用tool或者根据tool结果返回"),
        "tool_call": Output("call_tools", "llm 回应", LLMChatResponse, "返回的response带有tool_calls字段，你需要根据此字段进行下一个动作")
    }
    container: DependencyContainer
    
    def __init__(self, model_name: Annotated[
            str, 
            # 等待实现： 只列出支持function_calling的模型
            ParamMeta(label="模型 ID, 支持函数调用且不可为空", description="支持函数调用的模型", options_provider=model_name_options_provider)
        ]): 
        self.model_name = model_name
        self.logger = get_logger("FunctionCallingBlock")

    def execute(self, request_body: LLMChatRequest) -> Dict[str, Any]:
        if not self.model_name:
            raise ValueError("need a model name which support function calling")
        else:
            self.logger.info(f"Using  model: {self.model_name} to execute function calling")
        llm = self.container.resolve(LLMManager).get_llm(self.model_name)
        if not llm:
            raise ValueError(f"LLM {self.model_name} not found, please check the model name")
        # 在这里指定llm的model
        request_body.model = self.model_name
        response: LLMChatResponse = llm.chat(request_body)
        if not response.message.tool_calls:
            self.logger.debug("No tool calls found, return response directly")
            return {"resp": response}
        else:
            self.logger.debug("Tool calls found, return response with tool calls")
            return {"tool_call": response}