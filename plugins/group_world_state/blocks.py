from __future__ import annotations

import random
import threading
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from kirara_ai.im.message import IMMessage, TextMessage
from kirara_ai.im.sender import ChatSender, ChatType
from kirara_ai.ioc.container import DependencyContainer
from kirara_ai.llm.format.message import LLMChatMessage, LLMChatTextContent
from kirara_ai.llm.format.request import LLMChatRequest
from kirara_ai.llm.format.response import LLMChatResponse
from kirara_ai.llm.llm_manager import LLMManager
from kirara_ai.llm.llm_registry import LLMAbility
from kirara_ai.logger import get_logger
from kirara_ai.memory.composes.base import ComposableMessageType
from kirara_ai.workflow.core.block import Block, Input, Output, ParamMeta

from .characters import (
    aliases,
    character_by_im,
    get_character,
    immersion_config,
    invalidate_peer_binding,
    peer_address,
    peer_id_for,
    peer_qq,
    turn_object_line,
)
from .extractor import (
    EXTRACT_SYSTEM,
    build_extract_prompt,
    filter_ops,
    parse_extract_json,
    should_extract,
)
from .mentions import (
    addressed_to_self,
    mentioned_bot as _mentioned_bot,
    mentioned_others as _mentioned_others,
    sender_qq_of,
)
from .narration import to_narration
from .parser import extract_command, strip_memory_points, strip_state
from .compiler import USE_COMPILER, compile_persona
from .voice_pack import note_after_reply as note_voice_after_reply
from .voice_pack import style_tail
from .persona_text import envelop_module, strip_workflow_chrome
from .peer import (
    PeerChainStore,
    analyze_dialogue_target,
    looks_addressed_to_self,
    looks_like_narrated_scene,
    looks_like_wrap_up,
    peer_should_discard,
)
from .scene_context import SceneContextStore
from .store import WorldStateStore, empty_text_for, scope_id
from .voice_text import is_voice_only, strip_voice_message
from .story import (
    StorySessionStore,
    display_of,
    extract_participating_bots,
    finalize_story,
    other_bots_label,
    route_story,
)
from .style_guard import (
    critical_block_for,
    critical_instruction_for,
    fallback_safe_reply,
    find_character_violations,
    fix_third_person_peer,
    last_user_text,
    looks_like_question,
    looks_like_markdown,
    looks_peer_distress_cue,
    replace_assistant_text,
    retry_rewrite,
    scrub_long_inner_aside,
    scrub_markdown_markup,
    scrub_stray_close_quote,
    scrub_truncated_tail,
    scrub_vocative_header,
    scrub_wrong_inner_style,
    scrub_soyo_catchphrase,
    scrub_soyo_fixed_voice,
    strip_inner_asides_for_peer,
    salvage_non_ask_reply,
    source_names_peer,
    trigger_source_text,
)
from .token_meter import format_module_injection, format_simple_call

logger = get_logger("WorldState")

HELP_TEXT = (
    "本群长期设定（和近期聊天记录分开，会一直留着）：\n"
    "/长期记忆\n"
    "/长期记忆 设定 relationship 已经向素世告白，目前在交往\n"
    "/长期记忆 删除 relationship\n"
    "/长期记忆 清空\n"
    "键名建议：relationship、nickname、plot、peer_relationship。按角色+群隔离。"
)


PERSONA_ROOT = Path("data/persona")
PERSONA_MODULES = ("base", "scene", "trigger", "companion", "story", "mode_phone")
SCENE_EMPTY = "（暂无额外环境音。）"

_module_cache: Dict[str, str] = {}
_module_lock = threading.RLock()


def persona_module_path(character: str, module: str) -> Path:
    return PERSONA_ROOT / character / "modules" / f"{character}_{module}.md"


def load_persona_module(character: str, module: str) -> str:
    """读盘一次后常驻进程内存；若为 PERSONA_PACK 则规范化后再注入。"""
    key = f"{character}:{module}"
    with _module_lock:
        cached = _module_cache.get(key)
    if cached is not None:
        return cached
    try:
        from .persona_pack import format_persona_pack, parse_persona_pack

        text = persona_module_path(character, module).read_text(encoding="utf-8")
        text = strip_workflow_chrome(text).strip()
        # base/trigger 的紧凑 XML 原样注入；PERSONA_PACK 规范化并去 :: 备注后再注入
        low = text.lower()
        if "[PERSONA_PACK]" in text.upper():
            pack = parse_persona_pack(text, module)
            text = format_persona_pack(pack, strip_notes=True).strip()
        elif "<role" in low and (module or "").strip() == "base":
            pass
        elif "<trigger" in low and (module or "").strip() == "trigger":
            pass
        elif "<role" in low or "<trigger" in low:
            pack = parse_persona_pack(text, module)
            text = format_persona_pack(pack, strip_notes=True).strip()
    except FileNotFoundError:
        text = ""
    except Exception as exc:
        logger.warning(f"load persona module {key} failed: {exc}")
        text = ""
    with _module_lock:
        _module_cache[key] = text
    return text


def has_persona_modules(character: str) -> bool:
    return bool(load_persona_module(character, "base"))


def warm_persona_modules(characters) -> Dict[str, int]:
    sizes: Dict[str, int] = {}
    for character in characters:
        for module in PERSONA_MODULES:
            sizes[f"{character}:{module}"] = len(load_persona_module(character, module))
    return sizes


def invalidate_persona_module(character: str, module: Optional[str] = None) -> None:
    prefix = f"{(character or '').strip()}:"
    with _module_lock:
        if module:
            _module_cache.pop(f"{character}:{module}", None)
            return
        for key in [k for k in _module_cache if k.startswith(prefix)]:
            _module_cache.pop(key, None)


def read_persona_module_raw(character: str, module: str) -> str:
    path = persona_module_path(character, module)
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def save_persona_module(character: str, module: str, text: str) -> Dict[str, Any]:
    character = (character or "").strip()
    module = (module or "").strip()
    if character not in ("soyo", "anon"):
        raise ValueError("未知角色")
    if module not in PERSONA_MODULES:
        raise ValueError("未知模块")
    body = strip_workflow_chrome((text or "").replace("\r\n", "\n"))
    if len(body) > 200_000:
        raise ValueError("内容过长（上限 20 万字）")
    path = persona_module_path(character, module)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    tmp.replace(path)
    invalidate_persona_module(character, module)
    if module == "base":
        invalidate_peer_binding(character)
    loaded = load_persona_module(character, module)
    stat = path.stat()
    return {
        "character": character,
        "module": module,
        "bytes": int(stat.st_size),
        "text": loaded or body,
    }


def save_persona_module_pack(character: str, module: str, pack: Dict[str, Any]) -> Dict[str, Any]:
    from .persona_pack import format_persona_pack, pack_from_request, parse_persona_pack

    mid = (module or "").strip()
    normalized = pack_from_request(pack if isinstance(pack, dict) else {}, mid)
    normalized["module"] = mid
    text = format_persona_pack(normalized)
    saved = save_persona_module(character, mid, text)
    saved["pack"] = parse_persona_pack(saved.get("text") or text, mid)
    return saved


def _store(container: DependencyContainer) -> WorldStateStore:
    return container.resolve(WorldStateStore)


def _peer_store(container: DependencyContainer) -> PeerChainStore:
    try:
        return container.resolve(PeerChainStore)
    except Exception:
        store = PeerChainStore(__import__("pathlib").Path("data/world_state/_peer_chains"))
        try:
            container.register(PeerChainStore, store)
        except Exception:
            pass
        return store


def _story_store(container: DependencyContainer) -> StorySessionStore:
    try:
        return container.resolve(StorySessionStore)
    except Exception:
        store = StorySessionStore(Path("data/world_state/_story"))
        try:
            container.register(StorySessionStore, store)
        except Exception:
            pass
        return store


def _character_of(block_character: str, sender: Optional[ChatSender] = None) -> str:
    """优先用消息来源适配器推断角色，否则用块参数。"""
    if sender is not None:
        meta = getattr(sender, "raw_metadata", None) or {}
        im = meta.get("im_name")
        if im:
            cid = character_by_im(str(im))
            if cid:
                return cid
    return (block_character or "anon").strip() or "anon"


def _scope_from_sender(sender: ChatSender, character: str = "anon") -> str:
    if sender.chat_type == ChatType.GROUP:
        return scope_id(character, sender.group_id, sender.user_id)
    return scope_id(character, None, sender.user_id)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).lower() in ("1", "true", "yes")


def _assistant_text(resp: Optional[LLMChatResponse]) -> str:
    if not resp or not resp.message:
        return ""
    chunks = []
    for part in resp.message.content or []:
        if isinstance(part, LLMChatTextContent) and part.text:
            chunks.append(part.text)
    return "\n".join(chunks).strip()


def _group_name(chat_sender: ChatSender, user_msg: Optional[IMMessage] = None) -> str:
    raw = getattr(user_msg, "raw_message", None) if user_msg else None
    if isinstance(raw, dict) and raw.get("group_name"):
        return str(raw.get("group_name"))
    if raw is not None and getattr(raw, "group_name", None):
        return str(raw.group_name)
    meta = getattr(chat_sender, "metadata", None) or {}
    if isinstance(meta, dict) and meta.get("group_name"):
        return str(meta.get("group_name"))
    return ""


def _public_speaker_name(display: str) -> str:
    """提示里只给可读名字；纯数字账号不当成称呼。"""
    name = (display or "").strip()
    if not name or (name.isdigit() and len(name) >= 5):
        return "眼前的人"
    return name


class QueryWorldState(Block):
    name = "query_world_state"
    inputs = {
        "chat_sender": Input("chat_sender", "聊天对象", ChatSender, "按群读取长期设定"),
    }
    outputs = {"text": Output("text", "长期设定文本", str, "注入提示词的本群长期设定")}
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "anon",
    ):
        self.character = (character or "anon").strip() or "anon"

    def execute(self, chat_sender: ChatSender) -> Dict[str, Any]:
        character = _character_of(self.character, chat_sender)
        try:
            store = _store(self.container)
            scope = _scope_from_sender(chat_sender, character)
            return {"text": store.render(scope)}
        except Exception as exc:
            logger.warning(f"query world_state failed: {exc}")
            return {"text": empty_text_for(character)}


class ApplyWorldState(Block):
    name = "apply_world_state"
    inputs = {
        "chat_sender": Input("chat_sender", "聊天对象", ChatSender, "要写入的群"),
        "user_msg": Input("user_msg", "用户消息", IMMessage, "原样传给抽取，避免抽取提前执行"),
        "llm_resp": Input("llm_resp", "LLM 响应", LLMChatResponse, "从回复里提取长期设定标记"),
    }
    outputs = {
        "llm_resp": Output("llm_resp", "处理后的响应", LLMChatResponse, "已去掉 <<STATE>> 标记的回复"),
        "user_msg": Output("user_msg", "用户消息", IMMessage, "原样传出"),
        "chat_sender": Output("chat_sender", "聊天对象", ChatSender, "原样传出"),
    }
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "anon",
    ):
        self.character = (character or "anon").strip() or "anon"

    def execute(
        self,
        chat_sender: ChatSender,
        user_msg: IMMessage,
        llm_resp: LLMChatResponse,
    ) -> Dict[str, Any]:
        cleaned = llm_resp.model_copy(deep=True)
        passthrough = {
            "llm_resp": cleaned,
            "user_msg": user_msg,
            "chat_sender": chat_sender,
        }
        if not cleaned.message or not cleaned.message.content:
            return passthrough

        all_ops = []
        all_points: List[str] = []
        for part in cleaned.message.content:
            if isinstance(part, LLMChatTextContent):
                text, ops = strip_state(part.text)
                text, points = strip_memory_points(text)
                part.text = text
                all_ops.extend(ops)
                all_points.extend(points)

        visible = _assistant_text(cleaned)
        if all_points and visible.strip() not in ("[NO_REPLY]", ""):
            try:
                gid = str(getattr(chat_sender, "group_id", "") or "").strip()
                character = _character_of(self.character, chat_sender)
                if gid:
                    _story_store(self.container).append_memory(gid, character, all_points)
            except Exception as exc:
                logger.warning(f"story memory_point persist failed: {exc}")

        if not all_ops:
            return passthrough

        try:
            store = _store(self.container)
        except Exception as exc:
            logger.warning(f"world_state store missing: {exc}")
            return passthrough

        scope = _scope_from_sender(chat_sender, _character_of(self.character, chat_sender))
        for op in all_ops:
            if op.key.lower().startswith("example") or "一句话写清" in (op.text or ""):
                logger.info(f"world_state ignore copied example {scope} {op.key}")
                continue
            try:
                if op.op == "set":
                    store.set_fact(scope, op.key, op.text, source="llm")
                    logger.info(f"world_state SET {scope} {op.key}")
                elif op.op == "del":
                    store.delete_fact(scope, op.key)
                    logger.info(f"world_state DEL {scope} {op.key}")
            except KeyError:
                logger.info(f"world_state DEL miss {scope} {op.key}")
            except Exception as exc:
                logger.warning(f"world_state apply failed {scope} {op}: {exc}")
        return passthrough


def _spawn_extract(
    logger,
    container: DependencyContainer,
    chat_sender: ChatSender,
    user_text: str,
    assistant_text: str,
    model_name: Optional[str],
    character: str = "anon",
    user_msg: Optional[IMMessage] = None,
    source: str = "extract",
    force: bool = False,
) -> None:
    try:
        store = _store(container)
        llm_manager = container.resolve(LLMManager)
    except Exception as exc:
        logger.warning(f"extract skipped, missing deps: {exc}")
        return

    scope = _scope_from_sender(chat_sender, character)
    group_name = _group_name(chat_sender, user_msg)
    try:
        store.ensure_group(scope, group_name or None)
    except Exception as exc:
        logger.warning(f"ensure_group failed {scope}: {exc}")
    current = store.render(scope)
    display = get_character(character).get("display") or character
    system = EXTRACT_SYSTEM.replace("爱音", display)
    prompt = build_extract_prompt(
        current,
        _public_speaker_name(chat_sender.display_name or ""),
        user_text,
        assistant_text,
        group_name or "",
    )
    model_id = (model_name or "").strip() or None

    def job() -> None:
        try:
            from kirara_ai.config.global_config import GlobalConfig

            candidates: List[str] = []
            seen = set()

            def _add(name: Optional[str]) -> None:
                if not name or name in seen:
                    return
                seen.add(name)
                candidates.append(name)

            _add(model_id)
            try:
                cfg = container.resolve(GlobalConfig)
            except Exception:
                cfg = getattr(llm_manager, "config", None)
            # 优先：llm_pools.yaml → llms.priority → defaults/backends
            try:
                from pathlib import Path
                import yaml as _yaml

                pools_path = Path("data/llm_pools.yaml")
                if pools_path.is_file():
                    pools = _yaml.safe_load(pools_path.read_text(encoding="utf-8")) or {}
                    for name in pools.get("text") or []:
                        _add(name)
            except Exception:
                pass
            if cfg is not None:
                priority = getattr(getattr(cfg, "llms", None), "priority", None)
                raw = getattr(priority, "text", None) if priority is not None else None
                if raw is None and isinstance(priority, dict):
                    raw = priority.get("text")
                for name in raw or []:
                    _add(name)
                if len(candidates) <= (1 if model_id else 0):
                    default_id = getattr(getattr(cfg, "defaults", None), "llm_model", None)
                    _add((default_id or "").strip() or None)
                    for backend in getattr(getattr(cfg, "llms", None), "api_backends", None) or []:
                        if not getattr(backend, "enable", True):
                            continue
                        bname = getattr(backend, "name", "") or ""
                        for mid in getattr(backend, "models", None) or []:
                            if not mid:
                                continue
                            low = str(mid).lower()
                            if any(x in low for x in ("-vl", "vl-", "vl_", "_vl", "vision", "qwen-vl")):
                                continue
                            ref = f"{bname}/{mid}" if bname and "/" not in str(mid) else str(mid)
                            _add(ref)
            if not candidates:
                fallback = llm_manager.get_llm_id_by_ability(LLMAbility.TextChat)
                _add(fallback)
            # 避免模型管理自动探测出上百个模型时刷爆 API
            candidates = candidates[:8]

            messages = [
                LLMChatMessage(
                    role="system",
                    content=[LLMChatTextContent(text=system)],
                ),
                LLMChatMessage(
                    role="user",
                    content=[LLMChatTextContent(text=prompt)],
                ),
            ]
            resp = None
            last_err = None
            for chosen in candidates:
                llm = llm_manager.get_llm(chosen)
                if not llm:
                    continue
                try:
                    resp = llm.chat(LLMChatRequest(messages=messages, model=chosen))
                    try:
                        logger.info(
                            format_simple_call(
                                purpose="extract",
                                model=chosen,
                                system=system,
                                user=prompt,
                                resp=resp,
                            )
                        )
                    except Exception:
                        pass
                    break
                except Exception as exc:
                    last_err = exc
                    logger.warning(f"extract failover from {chosen}: {exc}")
                    continue
            if resp is None:
                logger.warning(f"extract skipped, no LLM / all failed last={last_err}")
                return
            raw = _assistant_text(resp)
            ops = filter_ops(parse_extract_json(raw), current)
            if not ops:
                logger.info(f"world_state EXTRACT skip {scope}: {(raw or '')[:160]}")
                return
            for op in ops:
                if op.op == "set":
                    store.set_fact(
                        scope,
                        op.key,
                        op.text,
                        source=source,
                        group_name=group_name or None,
                    )
                    logger.info(f"world_state EXTRACT SET {scope} {op.key}={op.text}")
                elif op.op == "del":
                    try:
                        store.delete_fact(scope, op.key)
                        logger.info(f"world_state EXTRACT DEL {scope} {op.key}")
                    except KeyError:
                        pass
        except Exception as exc:
            logger.warning(f"extract failed {scope}: {exc}")

    threading.Thread(target=job, daemon=True, name="world-state-extract").start()


class ExtractWorldState(Block):
    name = "extract_world_state"
    inputs = {
        "chat_sender": Input("chat_sender", "聊天对象", ChatSender, "按群写入长期设定"),
        "user_msg": Input("user_msg", "用户消息", IMMessage, "本轮群友消息"),
        "llm_resp": Input("llm_resp", "LLM 响应", LLMChatResponse, "角色回复，抽取必须等回复写完"),
        "extract_priority": Input(
            "extract_priority",
            "抽取优先级",
            str,
            "peer 时强制抽取",
            nullable=True,
        ),
    }
    outputs = {}
    container: DependencyContainer

    def __init__(
        self,
        always: Annotated[
            bool,
            ParamMeta(
                label="每次回复都抽取",
                description="开启后，只要角色回了话就会尝试更新长期设定；关闭则仅在出现告白/交往等关键词时抽取",
            ),
        ] = True,
        model_name: Annotated[
            Optional[str],
            ParamMeta(label="抽取模型", description="留空则用默认对话模型"),
        ] = "deepseek-v4-flash-0731",
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "anon",
    ):
        self.always = _as_bool(always, True)
        self.model_name = model_name
        self.character = (character or "anon").strip() or "anon"
        self.logger = get_logger("WorldState.Extract")

    def execute(
        self,
        chat_sender: ChatSender,
        user_msg: IMMessage,
        llm_resp: LLMChatResponse,
        extract_priority: Optional[str] = None,
    ) -> Dict[str, Any]:
        character = _character_of(self.character, chat_sender)
        user_text = user_msg.content or ""
        assistant_text = _assistant_text(llm_resp)
        if (extract_priority or "").strip() == "skip":
            return {}
        if assistant_text.strip() in ("", "[NO_REPLY]"):
            return {}
        peer = (extract_priority or "") == "peer"
        if not peer and not should_extract(user_text, assistant_text, always=self.always):
            return {}
        source = "peer_extract" if peer else "extract"
        _spawn_extract(
            self.logger,
            self.container,
            chat_sender,
            user_text,
            assistant_text,
            self.model_name,
            character=character,
            user_msg=user_msg,
            source=source,
            force=peer,
        )
        # record peer chain after we replied
        if peer and chat_sender.group_id:
            try:
                _peer_store(self.container).record_reply(chat_sender.group_id, character)
            except Exception as exc:
                self.logger.debug(f"peer chain record failed: {exc}")
        return {}


class ExtractUserWorldState(Block):
    name = "extract_user_world_state"
    inputs = {
        "chat_sender": Input("chat_sender", "聊天对象", ChatSender, "按群写入长期设定"),
        "user_msg": Input("user_msg", "用户消息", IMMessage, "本轮群友消息"),
    }
    outputs = {}
    container: DependencyContainer

    def __init__(
        self,
        model_name: Annotated[
            Optional[str],
            ParamMeta(label="抽取模型", description="留空则用默认对话模型"),
        ] = "deepseek-v4-flash-0731",
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "anon",
    ):
        self.model_name = model_name
        self.character = (character or "anon").strip() or "anon"
        self.logger = get_logger("WorldState.ExtractUser")

    def execute(self, chat_sender: ChatSender, user_msg: IMMessage) -> Dict[str, Any]:
        from .characters import is_registered_bot_qq

        character = _character_of(self.character, chat_sender)
        user_text = user_msg.content or ""
        qq = sender_qq_of(chat_sender, user_msg)
        mentioned = addressed_to_self(user_msg, character)
        # 人类未 @本账号 / 非登记 Bot：不抽取关系，避免环境旁白污染
        if not is_registered_bot_qq(qq) and not mentioned:
            return {}
        if not should_extract(user_text, "", always=False):
            return {}
        _spawn_extract(
            self.logger,
            self.container,
            chat_sender,
            user_text,
            "",
            self.model_name,
            character=character,
            user_msg=user_msg,
            source="extract",
        )
        return {}


def _scene_store(container: DependencyContainer) -> SceneContextStore:
    try:
        return container.resolve(SceneContextStore)
    except Exception:
        cfg = immersion_config()
        store = SceneContextStore(
            Path("data/world_state/_scene"),
            maxlen=int(cfg.get("scene_buffer_max") or 5),
        )
        try:
            container.register(SceneContextStore, store)
        except Exception:
            pass
        return store


class QuerySceneContext(Block):
    name = "query_scene_context"
    inputs = {
        "chat_sender": Input("chat_sender", "聊天对象", ChatSender, "按群读取场景缓冲"),
    }
    outputs = {
        "text": Output("text", "场景 XML", str, "注入 {current_scene}"),
    }
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "anon",
    ):
        self.character = (character or "anon").strip() or "anon"

    def execute(self, chat_sender: ChatSender) -> Dict[str, Any]:
        character = _character_of(self.character, chat_sender)
        gid = str(chat_sender.group_id or "").strip()
        if not gid:
            return {"text": "（暂无额外环境音。）"}
        try:
            xml = _scene_store(self.container).render_xml(character, gid)
            return {"text": xml or "（暂无额外环境音。）"}
        except Exception as exc:
            logger.warning(f"query scene_context failed: {exc}")
            return {"text": "（暂无额外环境音。）"}


def exclusive_persona_primary(mode: str, scene: str = "") -> Optional[str]:
    """互斥网关：本轮只允许一个条件模块。story/trigger/companion 永不并行。"""
    mode = (mode or "").strip()
    scene = (scene or "").strip()
    if mode == "story":
        return "story"
    if mode == "direct":
        return "trigger"
    if mode in ("peer", "env_peer"):
        return "companion"
    if mode in ("scene", "env") and scene and scene != SCENE_EMPTY:
        return "scene"
    return None


class PersonaLayers(Block):
    """分层人设：Base 作身份；条件模块互斥注入（story|trigger|companion|scene 四选一）。
    interaction_mode=phone 时追加 mode_phone（高于 Base speech）。"""

    name = "persona_layers"
    inputs = {
        "chat_sender": Input("chat_sender", "聊天对象", ChatSender, "按群判断同伴是否在线"),
        "message_mode": Input(
            "message_mode", "消息模式", str, "peer / direct / env / discard", nullable=True
        ),
        "current_scene": Input(
            "current_scene", "当前场景", str, "scene_context 渲染结果", nullable=True
        ),
        "interaction_mode": Input(
            "interaction_mode",
            "交互模式",
            str,
            "face / phone；phone 时叠加 mode_phone",
            nullable=True,
        ),
        "user_msg": Input(
            "user_msg",
            "用户消息",
            IMMessage,
            "用于家庭/乐队/触发词按需编译",
            nullable=True,
        ),
    }
    outputs = {
        "text": Output("text", "分层人设", str, "Base + 本轮唯一条件模块"),
    }
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "soyo",
    ):
        self.character = (character or "soyo").strip() or "soyo"

    def _companion_online(self, character: str, chat_sender: ChatSender, mode: str) -> bool:
        if mode == "peer":
            return True
        gid = str(getattr(chat_sender, "group_id", "") or "").strip()
        if not gid:
            return False
        try:
            return _peer_store(self.container).companion_online(gid)
        except Exception as exc:
            logger.warning(f"companion_online check failed: {exc}")
            return False

    def execute(
        self,
        chat_sender: ChatSender,
        message_mode: Optional[str] = None,
        current_scene: Optional[str] = None,
        interaction_mode: Optional[str] = None,
        user_msg: Optional[IMMessage] = None,
    ) -> Dict[str, Any]:
        character = _character_of(self.character, chat_sender)
        mode = (message_mode or "").strip()
        scene = (current_scene or "").strip()
        imode = (interaction_mode or "").strip().lower() or "face"
        user_text = ""
        if user_msg is not None:
            user_text = str(getattr(user_msg, "content", "") or "")

        if mode == "story_end":
            return {
                "text": (
                    "不要扮演角色。不要续写故事。"
                    "只输出这一句：故事已结束，关键情节已记录。\n\n"
                )
            }

        primary = exclusive_persona_primary(mode, scene)
        # env_peer：主动拉同伴，即使连环未开始也要注入 companion
        if primary == "companion" and mode != "env_peer" and not self._companion_online(
            character, chat_sender, mode
        ):
            primary = None

        peer_online = primary == "companion" or mode in ("peer", "env_peer")
        if not peer_online:
            peer_online = self._companion_online(character, chat_sender, mode)

        context_text = "\n".join(x for x in (user_text, scene) if x)
        compile_mode = "story" if primary == "story" or mode == "story" else "chat"
        sender_qq = sender_qq_of(chat_sender, user_msg)
        if mode in ("peer", "env_peer") or primary == "companion":
            sender_qq = sender_qq or peer_qq(character)

        story_prompt = ""
        story_others = ""
        if primary == "story":
            gid = str(getattr(chat_sender, "group_id", "") or "").strip()
            session = None
            if gid:
                try:
                    session = _story_store(self.container).get(gid)
                except Exception as exc:
                    logger.warning(f"persona_layers story session miss: {exc}")
            others = list((session.participating_bots if session else []) or [])
            story_prompt = (session.story_prompt if session else "") or "一段尚未命名的故事"
            story_others = other_bots_label(character, others)

        if USE_COMPILER:
            try:
                base_body = compile_persona(
                    character,
                    mode=compile_mode,
                    peer_online=peer_online,
                    context_text=context_text,
                    interaction=imode,
                    sender_qq=sender_qq,
                    at_mode=(mode == "direct" or primary == "trigger"),
                    inject_scene=(primary == "scene"),
                    story_prompt=story_prompt,
                    story_others=story_others,
                )
            except Exception as exc:
                logger.warning(f"persona compiler failed, fallback md: {exc}")
                base_body = load_persona_module(character, "base")
        else:
            base_body = load_persona_module(character, "base")

        parts = [envelop_module("base", base_body, mode)]
        hit = ["base"]

        if primary == "story":
            # 故事轮不注入 Companion / Trigger：日常互聊收束和问答体规则会把故事拍封死。
            if USE_COMPILER and "<story_mode>" in (base_body or ""):
                hit.append("story")
            else:
                story_txt = load_persona_module(character, "story")
                story_txt = story_txt.replace("{story_prompt}", story_prompt or "一段尚未命名的故事")
                story_txt = story_txt.replace("{other_bots_in_story}", story_others)
                story_txt = envelop_module("story", story_txt, mode)
                if story_txt:
                    parts.append(story_txt)
                    hit.append("story")
        elif primary == "trigger" and not USE_COMPILER:
            parts.append(
                envelop_module("trigger", load_persona_module(character, "trigger"), mode)
            )
            hit.append("trigger")
        elif primary == "companion" and not USE_COMPILER:
            parts.append(
                envelop_module(
                    "companion", load_persona_module(character, "companion"), mode
                )
            )
            hit.append("companion")
        elif primary == "scene":
            if USE_COMPILER and "<scene_mode>" in (base_body or ""):
                hit.append("scene")
            else:
                parts.append(
                    envelop_module("scene", load_persona_module(character, "scene"), mode)
                )
                hit.append("scene")

        if imode == "phone" and mode not in ("story_end", "discard"):
            if USE_COMPILER and "<phone_mode" in (base_body or ""):
                hit.append("mode_phone")
            else:
                phone_txt = envelop_module(
                    "mode_phone", load_persona_module(character, "mode_phone"), mode
                )
                if phone_txt:
                    parts.append(phone_txt)
                    hit.append("mode_phone")

        skipped = [m for m in ("story", "trigger", "companion", "scene") if m not in hit]
        if mode not in ("story", "story_end", "discard"):
            try:
                from .weather import here_now_block

                gid = str(getattr(chat_sender, "group_id", "") or "").strip() or "dm"
                here = here_now_block(
                    character, group_id=gid, user_text=context_text
                )
                if here:
                    parts.append(here)
                    hit.append("here_now")
            except Exception as exc:
                logger.debug(f"here_now skip: {exc}")
        text = "\n\n".join(p for p in parts if p).strip()
        try:
            logger.info(
                format_module_injection(character, mode, list(zip(hit, parts)))
            )
            logger.info(
                f"persona_layers {character} mutex primary={primary or 'base'} "
                f"interaction_mode={imode} skip={','.join(skipped)}"
            )
        except Exception as exc:
            logger.debug(f"persona_layers token log skip: {exc}")
        return {"text": (text + "\n\n") if text else ""}


class AppendSceneContext(Block):
    name = "append_scene_context"
    inputs = {
        "chat_sender": Input("chat_sender", "聊天对象", ChatSender, "按群写入"),
        "user_msg": Input("user_msg", "用户消息", IMMessage, "原话"),
        "message_mode": Input("message_mode", "消息模式", str, "仅 env 写入", nullable=True),
        "narration": Input("narration", "旁白", str, "环境旁白", nullable=True),
        "narration_source": Input(
            "narration_source", "旁白来源", str, "template/llm", nullable=True
        ),
        "llm_resp": Input(
            "llm_resp",
            "LLM 响应",
            LLMChatResponse,
            "有回复后再写入场景（保证本轮已发生）",
            nullable=True,
        ),
    }
    outputs = {}
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "anon",
    ):
        self.character = (character or "anon").strip() or "anon"

    def execute(
        self,
        chat_sender: ChatSender,
        user_msg: IMMessage,
        message_mode: Optional[str] = None,
        narration: Optional[str] = None,
        narration_source: Optional[str] = None,
        llm_resp: Optional[LLMChatResponse] = None,
    ) -> Dict[str, Any]:
        if (message_mode or "").strip() != "env":
            return {}
        narr = (narration or "").strip()
        if not narr:
            return {}
        # 丢弃空回复
        if llm_resp is not None:
            text = _assistant_text(llm_resp).strip()
            if not text or text == "[NO_REPLY]":
                return {}
        character = _character_of(self.character, chat_sender)
        gid = str(chat_sender.group_id or "").strip()
        if not gid:
            return {}
        try:
            from .narration import strip_addressing

            raw_text = strip_addressing(user_msg.content or "")
            _scene_store(self.container).append(
                character,
                gid,
                raw=raw_text,
                narration=narr,
                source=(narration_source or "template").strip() or "template",
            )
        except Exception as exc:
            logger.warning(f"append scene_context failed: {exc}")
        return {}


class GatedChatMemoryStore(Block):
    """env/discard 时跳过对话记忆写入。"""

    name = "gated_chat_memory_store"
    inputs = {
        "user_msg": Input("user_msg", "用户消息", IMMessage, "用户消息", nullable=True),
        "llm_resp": Input(
            "llm_resp", "LLM 响应", LLMChatResponse, "LLM 响应", nullable=True
        ),
        "skip_chat_memory": Input(
            "skip_chat_memory",
            "跳过对话记忆",
            str,
            "true/false；env 旁白不进对话历史",
            nullable=True,
        ),
    }
    outputs = {}
    container: DependencyContainer

    def __init__(
        self,
        scope_type: Annotated[
            Optional[str],
            ParamMeta(label="级别", description="记忆作用域"),
        ] = None,
    ):
        self.scope_type = scope_type
        self.logger = get_logger("WorldState.GatedMemory")

    def execute(
        self,
        user_msg: Optional[IMMessage] = None,
        llm_resp: Optional[LLMChatResponse] = None,
        skip_chat_memory: Optional[str] = None,
    ) -> Dict[str, Any]:
        skip = str(skip_chat_memory or "").strip().lower() in ("1", "true", "yes", "y")
        if skip:
            self.logger.debug("skip chat memory for env/discard turn")
            return {}
        if user_msg is not None:
            if is_voice_only(user_msg):
                self.logger.debug("skip chat memory for voice-only turn")
                return {}
            user_msg = strip_voice_message(user_msg)
        if llm_resp is not None:
            text = _assistant_text(llm_resp).strip()
            if not text or text == "[NO_REPLY]":
                return {}
        try:
            from kirara_ai.memory.composes.base import ComposableMessageType
            from kirara_ai.memory.memory_manager import MemoryManager
            from kirara_ai.memory.registry import ComposerRegistry, ScopeRegistry
        except Exception as exc:
            self.logger.warning(f"gated memory deps missing: {exc}")
            return {}

        memory_manager = self.container.resolve(MemoryManager)
        scope_type = self.scope_type or memory_manager.config.default_scope
        scope_registry = self.container.resolve(ScopeRegistry)
        scope = scope_registry.get_scope(scope_type)
        composer_registry = self.container.resolve(ComposerRegistry)
        composer = composer_registry.get_composer("default")

        composed: list = []
        if user_msg is not None:
            composed.append(user_msg)
        if llm_resp is not None and llm_resp.message:
            composed.append(llm_resp.message)
        if not composed:
            return {}
        entries = composer.compose(
            user_msg.sender if user_msg else None, composed
        )
        memory_manager.store(scope, entries)
        return {}


class FilterFallbackMemory(Block):
    """fallback 记忆：仅同伴 Bot / 被 @ 的人类写入。"""

    name = "filter_fallback_memory"
    inputs = {
        "user_msg": Input("user_msg", "用户消息", IMMessage, "用户消息"),
    }
    outputs = {
        "user_msg": Output("user_msg", "可入库消息", IMMessage, "原样或空壳"),
        "skip_chat_memory": Output(
            "skip_chat_memory", "跳过对话记忆", str, "true=不入库"
        ),
    }
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "anon",
    ):
        self.character = (character or "anon").strip() or "anon"

    def execute(self, user_msg: IMMessage) -> Dict[str, Any]:
        from .characters import is_registered_bot_qq

        sender = user_msg.sender
        character = _character_of(self.character, sender)
        qq = sender_qq_of(sender, user_msg)
        mentioned = addressed_to_self(user_msg, character)
        if is_registered_bot_qq(qq) or mentioned:
            if is_voice_only(user_msg):
                empty = IMMessage(sender=sender, message_elements=[])
                return {"user_msg": empty, "skip_chat_memory": "true"}
            return {"user_msg": strip_voice_message(user_msg), "skip_chat_memory": "false"}
        empty = IMMessage(sender=sender, message_elements=[])
        return {"user_msg": empty, "skip_chat_memory": "true"}


class GateMemoryByMode(Block):
    """env / scene / discard / story 不把近期对话记忆注入系统提示，避免历史 @/回复被当成「有人在对你说话」。"""

    name = "gate_memory_by_mode"
    inputs = {
        "memory_content": Input(
            "memory_content",
            "近期聊天",
            List[ComposableMessageType],
            "query_memory 输出",
            nullable=True,
        ),
        "message_mode": Input(
            "message_mode", "消息模式", str, "env/scene 时清空", nullable=True
        ),
    }
    outputs = {
        "memory_content": Output(
            "memory_content", "过滤后记忆", List[ComposableMessageType], "可能为空列表"
        ),
    }

    def execute(
        self,
        memory_content: Any = None,
        message_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        mode = (message_mode or "").strip()
        if mode in ("env", "env_peer", "scene", "discard", "story", "story_end"):
            return {"memory_content": []}
        if memory_content is None:
            return {"memory_content": []}
        from .day_rollover import keep_today_memory

        return {"memory_content": keep_today_memory(memory_content)}


MENTION_CHANCE = 0.12


def _peer_addr(character: str) -> Dict[str, str]:
    """称呼来源：人设【同伴绑定】。"""
    addr = peer_address(character)
    if addr.get("call"):
        return addr
    # 极端缺省，避免空串
    if character == "anon":
        return {
            "call": "soyorin",
            "absent": "soyorin",
            "forbid": "素世 / 素世世 / soyo",
        }
    return {
        "call": "小爱音",
        "absent": "「某人」或「小爱音」",
        "forbid": "爱音 / 爱音酱 / Anon",
    }


def _voice_tail(character: str, group_id: str = "", content: str = "") -> str:
    """声线与例句来自 voice_pack；这里只留其它层没说过的那几条禁令。"""
    ban_self = "soyorin" if character == "anon" else "小爱音"
    return (
        "\n本轮你不是助理、不是客服。"
        "禁止秘书腔：我记下了 / 你负责 / 上次你…我还记得 / 我来帮你安排。"
        f"禁止用「{ban_self}，」当抬头，称呼塞进句子中间或末尾。\n"
        + style_tail(character, group_id, content)
    )


def _env_voice_tail(character: str, group_id: str = "", content: str = "") -> str:
    """环境音是最后一层，必须自己顶住『回应对方』那条常规规则。"""
    default_pivot = "吉他音准/调弦" if character == "anon" else "红茶菜单/练团"
    return (
        "\n本轮没有对话对象：你不知道这句话是谁说的，也不要去猜是谁。\n"
        "禁止回答它、禁止复述它、禁止用「你/你们/您」称呼任何人、"
        "禁止说「有人说 / 群里有人 / 刚才谁提到」。\n"
        "只做一句自言自语，一两句就停，不要追问。不要动作括号。"
        "前后必须同一条因果：后半句解释前半句，不要把翻手机和天气、头发拼成两截。"
        "here_now 若写了 WEATHER: OFF，本轮不要提天气。"
        "否则体感以 here_now 为准，不要编季节或温度。"
        f"没有爱好命中时禁止默认切到{default_pivot}。\n"
        + style_tail(character, group_id, content)
    )


def _env_peer_ping_tail(
    character: str, chain_hint: str = "", group_id: str = "", content: str = ""
) -> str:
    """环境闲聊开关 ON：允许 @ 同伴续聊；轮次由 peer chain 收束。"""
    addr = _peer_addr(character)
    pqq = peer_qq(character) or ""
    at_token = f"[CQ:at,qq={pqq}]" if pqq else ""
    call = addr["call"]
    hint = f"\n{chain_hint}" if chain_hint else ""
    return (
        "\n[ENV_PEER_PING: ON]\n"
        "本轮是随机闲聊，但允许主动点同伴把话题续上。\n"
        "禁止回答旁白、禁止找说话人、禁止说「有人说/群里有人」。\n"
        "旁白内容含糊、跟你们无关时不要编成「在说我们/在议论我们」；"
        "只是借着这句话此刻的气氛/心情甩给同伴一句，不要给旁白强加身份或意图。\n"
        f"必须出现同伴称呼「{call}」，并带上 {at_token or '同伴@'}；"
        f"对同伴可以用「你」，禁止「{addr['forbid']}」。先 {at_token} 再喊「{call}」，"
        "半句把眼前感触甩给她续，不要动作括号。\n"
        + style_tail(character, group_id, content)
        + f"\n一两句就停；不要一次聊完，留给她接。{hint}"
    )


def _address_tail(character: str, group_id: str = "", content: str = "") -> str:
    addr = _peer_addr(character)
    call = addr["call"]
    need_call = True
    try:
        from .action_cue import address_allowed

        need_call = address_allowed(character, group_id or "dm")
    except Exception:
        need_call = True
    if need_call:
        rule = (
            f"\n称呼：这轮可以把「{call}」塞进句子中间或末尾一次；"
            f"禁止「{call}，」起手当抬头。"
        )
    else:
        rule = (
            f"\n称呼：上一句已经叫过「{call}」，这轮用「你」接就行，"
            f"不要再「{call}，」起手，也不必硬点名。"
        )
    return (
        rule
        + f"禁止 {addr['forbid']}。"
        "禁止导演解说、禁止复盘「这个状况」。"
        + _voice_tail(character, group_id, content)
    )


def _build_external_trigger_prompt(
    character: str, display: str, group_name: str, content: str, group_id: str = ""
) -> str:
    """把被@/点名的人类消息交给情境自适应框架；约 30% 允许自我回应后轻提同伴。"""
    addr = _peer_addr(character)
    mention_on = random.random() < MENTION_CHANCE
    switch = "ON" if mention_on else "OFF"
    peer_named = False
    try:
        from .characters import peer_id_for
        from .peer import looks_vocative_to

        pid = peer_id_for(character)
        peer_named = bool(pid) and looks_vocative_to(content, pid)
    except Exception:
        peer_named = False
    if not peer_named:
        try:
            from .topic_classify import source_mentions_peer

            peer_named = source_mentions_peer(character, content)
        except Exception:
            pass
    distress = False
    try:
        from .style_guard import looks_peer_distress_cue

        distress = looks_peer_distress_cue(content)
    except Exception:
        distress = False
    if distress:
        mention_rule = (
            f"同伴正在跑开或在哭：必须立刻追「{addr['call']}」，"
            "禁止沿用上文「算了明天见」「鞋带没系好」「麻烦死了」「又不差这一会儿」——"
            "那些是口误，这轮作废。不要回答提问者，直接追。"
        )
        switch = "TYPE3"
        peer_named = True
    elif peer_named:
        mention_rule = (
            f"触发内容已点名同伴：必须选类型3，直接对{addr['call']}说话（第二人称「你」），"
            f"像当面/隔空喊她，不是回答提问者。"
            f"禁止转述或评论她——不管是用「她」还是直接喊「{addr['call']}」，"
            "只要是讲给提问者听的第三人称报告（「她刚才怎样怎样」）就算违规；"
            "禁止「让她自己来问」「不看」「别催」这类回答提问者。"
            "不要复读对方的选择问。对同伴可以提问（要不要/对吧），不要向外答题。"
        )
        switch = "TYPE3"
    elif mention_on:
        mention_rule = (
            f"本轮轻提开关：ON。可以在同一句里偶尔带过{addr['call']}，"
            "不要答完再另起一句拐到她，也不要把整段改成找她互动。"
        )
    else:
        mention_rule = (
            "本轮轻提开关：OFF。选自我回应或环境反应时不要主动提到同伴。"
        )
    asked_lock = ""
    qa_out = ""
    if peer_named:
        asked_lock = "本轮对同伴说话：问句可以放行。禁止向外答题或解释问题。\n"
    else:
        qa_out = (
            "禁止对眼前的人输出提问句：不要吗/对吧/会不会/什么呢/要不要，"
            "没有问号也算提问，一律改成陈述。\n"
        )
        if looks_like_question(content):
            asked_lock = (
                "对方在提问（没有问号也算：会不会/什么呢/对吧/吗/都有什么）。"
                "禁止答题，禁止列举清单，禁止反问，转化成角色正在发的一句陈述。\n"
            )
    body = (
        "[SYSTEM: EXTERNAL_TRIGGER]\n"
        f"触发内容：{content}\n"
        "响应要求：只选一种最自然的反应，优先自己接住眼前这句；"
        "禁止把每个问题都转化成找同伴互动；"
        "仅当内容明确指向她或共同计划时才把整段改成对她说话。"
        "禁止两截转进：不要「先应一声，再问同伴是不是」。\n"
        "禁止问答体：不要复读问题，不要向对方给许可或拒绝，不要解释「这个问题」。\n"
        f"{qa_out}"
        f"{asked_lock}"
        f"{mention_rule}\n"
        f"称呼：若本轮提及同伴，称「{addr['call']}」"
        f"（不在场可用 {addr['absent']}）；禁止 {addr['forbid']}。"
        f"轻提开关={switch}。不要当考题作答。禁止先复述再入戏。"
        f"{_voice_tail(character, group_id, content)}\n"
    )
    if peer_named:
        body += (
            "[ARBITRATION: peer_interaction]\n"
            "本轮已点名同伴：忽略 deflect/idle；类型3优先；禁止权衡规则冲突。\n"
            "[INSTRUCTION: DO NOT ANALYZE RULE CONFLICTS. DIRECT ACTION ONLY.]\n"
        )
    body += "[/SYSTEM: EXTERNAL_TRIGGER]"
    return body


def _no_reply_bundle(text: str) -> Dict[str, Any]:
    return {
        "text": text,
        "extract_priority": "skip",
        "message_mode": "discard",
        "user_prompt_text": "【系统】本轮无有效环境信息，请只输出：[NO_REPLY]",
        "skip_chat_memory": "true",
        "narration": "",
        "narration_source": "",
        "critical_instruction": "",
    }


def _with_critical(
    character: str,
    bundle: Dict[str, Any],
    source_text: str = "",
    *,
    group_id: str = "",
) -> Dict[str, Any]:
    """挂 CRITICAL（系统层一次）和 P0，并按原文做爱好/话题分类注入【本轮话题锁】。

    身份判定只在代码里做：提示不写发送者账号、不写「群聊」。
    """
    mode = str(bundle.get("message_mode") or "")
    parts: List[str] = []
    if mode in ("direct", "story"):
        parts.append(critical_block_for(character))
    p0 = critical_instruction_for(character, mode)
    if p0:
        parts.append(p0)
    bundle["critical_instruction"] = "\n".join(parts)
    if mode in ("discard", "story_end") or not (source_text or "").strip():
        # discard 也可能是 /phone 命令，仍要解析模式
        try:
            from .interaction_mode import attach_interaction_mode

            return attach_interaction_mode(
                bundle,
                character=character,
                group_id=group_id or "dm",
                content=source_text or "",
            )
        except Exception:
            bundle.setdefault("interaction_mode", "face")
            return bundle
    try:
        from .topic_classify import (
            classify_text,
            force_peer_interaction_override,
            topic_critical_addon,
            topic_lock_text,
        )

        prompt = str(bundle.get("user_prompt_text") or "")
        chase_lock = None
        if mode == "peer" and group_id:
            try:
                from pathlib import Path as _P

                from .peer import PeerChainStore
                from .topic_classify import chase_scene_lock_text

                scene = PeerChainStore(_P("data/world_state/_peer_chains")).get_scene(
                    group_id
                )
                if scene == "anon_chasing_soyo":
                    chase_lock = chase_scene_lock_text(character, mode=mode)
            except Exception:
                chase_lock = None
        forced = chase_lock or force_peer_interaction_override(
            character, mode=mode, user_prompt=prompt, source_text=source_text
        )
        scene_forced = None
        if not forced:
            from .topic_classify import force_scene_continue_override

            scene_forced = force_scene_continue_override(
                character, mode=mode, user_prompt=prompt, source_text=source_text
            )
        if forced or scene_forced:
            lock = forced or scene_forced
            if lock and "id: chase_scene" in lock:
                lock_id = "chase_scene"
            elif lock and "ACTION: chase_now" in lock:
                lock_id = "peer_distress"
            elif forced:
                lock_id = "peer_interaction"
            else:
                lock_id = "scene_continue"
            bundle["user_prompt_text"] = (prompt + "\n" + lock).strip()
            existing = str(bundle.get("critical_instruction") or "")
            if lock_id == "chase_scene" and character == "soyo":
                arb = (
                    "[P0: CHASE SCENE]\n"
                    "你是跑开/被追的那一方。小爱音在追你。"
                    "禁止也好收束，禁止说自己追到了，禁止去追她。\n"
                    "[/P0]"
                )
            elif lock_id == "chase_scene":
                arb = (
                    "[P0: CHASE SCENE]\n"
                    "你在追 soyorin。对面的「你」就是她。"
                    "禁止把 soyorin 说成旁边第三个人去比谁跑得快。鞋带散了是你自己的。\n"
                    "[/P0]"
                )
            elif forced:
                arb = (
                    "[P0: PEER INTERACTION ARBITRATION]\n"
                    "mode_hint=peer_interaction reply_stance=engage\n"
                    "IGNORE: idle_ambient|deflect|TOPIC_LOCK_deflect\n"
                    "DO: 类型3定向同伴互动；禁止权衡规则冲突；禁止日常收束收口\n"
                    "[INSTRUCTION: DO NOT ANALYZE RULE CONFLICTS. DIRECT ACTION ONLY.]\n"
                    "[/P0]"
                )
            else:
                arb = (
                    "[P0: SCENE CONTINUE ARBITRATION]\n"
                    "mode_hint=scene_continue reply_stance=engage\n"
                    "IGNORE: idle_ambient|deflect|priority4沉默|日常收束\n"
                    "DO: 按第二人称场面自由发挥接下一拍；禁止收束到结束；禁止回答旁白者\n"
                    "若场面有同伴在场：当面称呼推进，不要用「她」向外转述\n"
                    "[INSTRUCTION: CONTINUE THE SCENE. DO NOT WRAP UP.]\n"
                    "[/P0]"
                )
            bundle["critical_instruction"] = (
                (existing + "\n" + arb).strip() if existing else arb
            )
            try:
                from pathlib import Path as _P2

                from .peer import PeerChainStore as _PCS
                from .style_guard import looks_chase_in_flight as _chase_on

                if group_id and (
                    lock_id in ("chase_scene", "peer_distress")
                    or _chase_on(source_text)
                ):
                    _PCS(_P2("data/world_state/_peer_chains")).set_scene(
                        group_id, "anon_chasing_soyo"
                    )
            except Exception:
                pass
            logger.info(
                f"topic_lock character={character} mode={mode} "
                f"id={lock_id} stance=engage detector=external_trigger_shortcircuit "
                f"forced=1"
            )
        else:
            hit = classify_text(character, source_text)
            lock = topic_lock_text(
                character,
                hit,
                mode=mode,
                source_text=source_text,
                group_id=group_id,
            )
            if lock:
                bundle["user_prompt_text"] = (prompt + "\n" + lock).strip()
            addon = topic_critical_addon(
                character, hit, mode=mode, group_id=group_id, source_text=source_text
            )
            if addon:
                existing = str(bundle.get("critical_instruction") or "")
                bundle["critical_instruction"] = (
                    (existing + "\n" + addon).strip() if existing else addon
                )
            logger.info(
                f"topic_lock character={character} mode={mode} "
                f"id={hit.category_id} stance={hit.stance} detector={hit.detector} "
                f"score={hit.score} terms={hit.matched_terms[:4]}"
            )
    except Exception as exc:
        logger.warning(f"topic_lock inject failed: {exc}")
    try:
        from .interaction_mode import attach_interaction_mode

        bundle = attach_interaction_mode(
            bundle,
            character=character,
            group_id=group_id or "dm",
            content=source_text or "",
        )
        # /phone 可能把 discard 抬成 direct，需补 P0
        if (bundle.get("message_mode") or "") == "direct" and not (
            bundle.get("critical_instruction") or ""
        ).strip():
            bundle["critical_instruction"] = critical_instruction_for(character, "direct")
        # F2F 稀疏动作 / Phone 禁括号：软约束注记
        mode_now = str(bundle.get("message_mode") or "")
        if mode_now not in ("discard", "story_end"):
            try:
                from .action_cue import assemble_action_note

                note = assemble_action_note(
                    character,
                    group_id or "dm",
                    str(bundle.get("interaction_mode") or "face"),
                    bump=True,
                )
                if note:
                    existing = str(bundle.get("critical_instruction") or "")
                    bundle["critical_instruction"] = (
                        (existing + "\n" + note).strip() if existing else note.strip()
                    )
            except Exception as cue_exc:
                logger.debug(f"action_cue note skip: {cue_exc}")
    except Exception as exc:
        logger.warning(f"interaction_mode attach failed: {exc}")
        bundle.setdefault("interaction_mode", "face")
    return bundle


def _build_story_turn_prompt(character: str, session: Any, guide_text: str) -> str:
    others = other_bots_label(character, session.participating_bots)
    last = session.current_speaker
    catch = ""
    if last and last != character:
        catch = (
            f"上一轮由{display_of(last)}发言，你必须先接住其内容再推进，不得无视同伴台词。\n"
        )
    addr = _peer_addr(character)
    if character == "soyo":
        close = (
            "本轮收束：演完这一拍就停，停在还能往下走的位置"
            "（没说完的半句、还没伸出去的手、看向小爱音却没开口）。"
            "禁止用「就这样/先这样/知道了/不说了」把场面封死。"
        )
    else:
        close = (
            "本轮收束：把这一下做完就停，停在还能被拉走的位置"
            "（刚抓住袖口、糖还没咬、话只说了半截）。"
            "禁止把场收死，也不要把下一个摊位一并逛完。"
        )
    return (
        "[SYSTEM: STORY MODE]\n"
        f"故事引子：{session.story_prompt}\n"
        f"本轮引导：{guide_text or '在当前情境里轻轻推进一步，不要快进。'}\n"
        f"协同角色：{others}\n"
        f"{catch}"
        "以角色身份推进剧情。对话对象是故事中的角色/环境，不是现实提问者。\n"
        f"{close}\n"
        "这不是故事结束。只有发起人发送 end / 结束 / stop 才结束整段故事。\n"
        "回复末尾输出隐藏标签：<memory_point>本轮关键事件/情感变化/决定</memory_point>\n"
        f"称呼若提及同伴，称「{addr['call']}」；禁止 {addr['forbid']}。\n"
        "[/SYSTEM: STORY MODE]"
    )


def _build_story_end_prompt() -> str:
    return (
        "[SYSTEM: STORY_END]\n"
        "故事已结束。不要扮演角色。不要续写。"
        "只输出这一句：故事已结束，关键情节已记录。\n"
        "[/SYSTEM: STORY_END]"
    )


def _default_chat_model(container: DependencyContainer, llm_manager: LLMManager) -> str:
    try:
        from kirara_ai.config.global_config import GlobalConfig

        cfg = container.resolve(GlobalConfig)
        mid = (getattr(getattr(cfg, "defaults", None), "llm_model", None) or "").strip()
        if mid:
            return mid
    except Exception:
        pass
    cfg = getattr(llm_manager, "config", None)
    return (getattr(getattr(cfg, "defaults", None), "llm_model", None) or "").strip()


class GuardCharacterReply(Block):
    """素世回复校验：违规称呼 / 采访体命中后记日志并重试一次。"""

    name = "guard_character_reply"
    inputs = {
        "llm_resp": Input("llm_resp", "LLM 响应", LLMChatResponse, "待校验回复"),
        "message_mode": Input(
            "message_mode", "消息模式", str, "direct 时额外拦采访体", nullable=True
        ),
        "prompt": Input(
            "prompt",
            "原对话",
            List[LLMChatMessage],
            "重试时续写用",
            nullable=True,
        ),
        "chat_sender": Input(
            "chat_sender", "聊天对象", ChatSender, "用于推断角色", nullable=True
        ),
    }
    outputs = {
        "llm_resp": Output("llm_resp", "校验后的响应", LLMChatResponse, "可能已重写"),
    }
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "soyo",
    ):
        self.character = (character or "soyo").strip() or "soyo"

    def execute(
        self,
        llm_resp: LLMChatResponse,
        message_mode: Optional[str] = None,
        prompt: Optional[List[LLMChatMessage]] = None,
        chat_sender: Optional[ChatSender] = None,
    ) -> Dict[str, Any]:
        character = _character_of(self.character, chat_sender)
        if character not in ("soyo", "anon"):
            return {"llm_resp": llm_resp}
        if (message_mode or "").strip() == "story_end":
            return {"llm_resp": llm_resp}
        text = _assistant_text(llm_resp)
        if not text or text.strip() in ("[NO_REPLY]",):
            return {"llm_resp": llm_resp}
        mode_l = (message_mode or "").strip()
        if looks_like_markdown(text):
            cleaned_md = scrub_markdown_markup(text)
            logger.info("style_guard scrub markdown markup")
            text = cleaned_md or ("诶？！" if character == "anon" else "……嗯。")
            llm_resp = replace_assistant_text(llm_resp, text)
        cleaned_quote = scrub_stray_close_quote(text)
        if cleaned_quote != text.strip():
            logger.info("style_guard scrub stray close quote tail")
            text = cleaned_quote or text
            llm_resp = replace_assistant_text(llm_resp, text)
        cleaned_cut = scrub_truncated_tail(text)
        if cleaned_cut != text.strip():
            logger.info("style_guard scrub truncated latin tail")
            text = cleaned_cut or text
            llm_resp = replace_assistant_text(llm_resp, text)
        if character == "soyo":
            cleaned = scrub_soyo_catchphrase(text)
            if cleaned != text.strip():
                logger.info("style_guard drop soyo catchphrase aside")
                text = cleaned or "嗯。"
                llm_resp = replace_assistant_text(llm_resp, text)
        if character == "anon":
            cleaned = scrub_soyo_fixed_voice(text)
            if cleaned != text.strip():
                logger.info("style_guard scrub soyo fixed voice from anon")
                text = cleaned or "诶？！"
                llm_resp = replace_assistant_text(llm_resp, text)
        # 内心：允许，但拆串腔；冷却/每轮一句在下方与 action_cue 对齐
        if mode_l != "story":
            cleaned = scrub_wrong_inner_style(character, text)
            if cleaned != text.strip():
                logger.info(f"style_guard scrub wrong inner style character={character}")
                text = cleaned or ("诶？！" if character == "anon" else "嗯。")
                llm_resp = replace_assistant_text(llm_resp, text)
            cleaned_inner = scrub_long_inner_aside(text)
            if cleaned_inner != text.strip():
                logger.info(f"style_guard scrub novelistic/long inner aside character={character}")
                text = cleaned_inner or text
                llm_resp = replace_assistant_text(llm_resp, text)
        cleaned_voc = scrub_vocative_header(character, text)
        if cleaned_voc != text.strip():
            logger.info(f"style_guard scrub vocative header character={character}")
            text = cleaned_voc or text
            llm_resp = replace_assistant_text(llm_resp, text)
        trigger_mode = mode_l == "direct"
        peer_mode = mode_l == "peer"
        env_peer_mode = mode_l == "env_peer"
        env_mode = mode_l in ("env", "scene")
        blob = last_user_text(prompt)
        if "[SYSTEM: EXTERNAL_TRIGGER]" in blob:
            trigger_mode = True
            peer_mode = False
            env_peer_mode = False
        elif "本轮是 Bot 互聊" in blob:
            peer_mode = True
            trigger_mode = False
            env_peer_mode = False
        elif "[ENV_PEER_PING: ON]" in blob:
            env_peer_mode = True
            env_mode = False
            peer_mode = False
            trigger_mode = False
        src = trigger_source_text(prompt)
        allow_ask = bool(peer_mode or env_peer_mode)
        if trigger_mode and not allow_ask:
            try:
                from .topic_classify import source_mentions_peer

                allow_ask = source_mentions_peer(character, src) or source_names_peer(
                    character, src
                )
            except Exception:
                allow_ask = source_names_peer(character, src)
            if not allow_ask:
                allow_ask = (
                    "轻提开关=TYPE3" in blob
                    or "peer_interaction" in blob
                    or looks_peer_distress_cue(src)
                )
        topic_idle = False
        try:
            from .topic_classify import parse_topic_from_prompt

            parsed = parse_topic_from_prompt(blob)
            topic_idle = bool(
                parsed and parsed[0] in ("idle_ambient", "peer_bond_suppressed")
            )
            # 场面续写 / 同伴互动 / 危急追人：不算 idle，避免收束
            if parsed and parsed[0] in (
                "scene_continue",
                "peer_interaction",
                "peer_distress",
                "chase_scene",
            ):
                topic_idle = False
            if "SCENE CONTINUE" in blob or "scene_continue" in blob:
                topic_idle = False
            if "PEER INTERACTION" in blob or "peer_interaction" in blob:
                topic_idle = False
            if "peer_distress" in blob or "ACTION: chase_now" in blob:
                topic_idle = False
            if "chase_scene" in blob or "ACTION: being_chased" in blob:
                topic_idle = False
        except Exception:
            topic_idle = False

        gid = str(getattr(chat_sender, "group_id", "") or "").strip() or "dm"
        need_addr = bool(env_peer_mode)
        if peer_mode:
            try:
                from .action_cue import address_allowed as _addr_ok

                need_addr = _addr_ok(character, gid)
            except Exception:
                need_addr = True

        # 本地修「她」转述：场面续写时不要落到「……这样啊」收束兜底
        fixed_she = fix_third_person_peer(character, text)
        if fixed_she:
            logger.info("style_guard local fix third-person peer address")
            text = fixed_she
            llm_resp = replace_assistant_text(llm_resp, text)
        hits = find_character_violations(
            character,
            text,
            trigger_mode=trigger_mode,
            peer_mode=peer_mode,
            env_mode=env_mode,
            env_peer_mode=env_peer_mode,
            user_text=src,
            allow_ask=allow_ask,
            topic_idle=topic_idle,
            require_address=need_addr,
        )
        imode = "face"
        any_stage_bracket_hits = None
        long_bracket_hits = None
        note_after_reply = None
        drop_long_brackets = None
        strip_stage_brackets = None
        try:
            from .action_cue import (
                any_stage_bracket_hits as _any_br,
                drop_long_brackets as _drop_br,
                long_bracket_hits as _long_br,
                note_after_reply as _note_ar,
                strip_stage_brackets as _strip_br,
            )
            from .interaction_mode import get_interaction_mode

            any_stage_bracket_hits = _any_br
            long_bracket_hits = _long_br
            note_after_reply = _note_ar
            drop_long_brackets = _drop_br
            strip_stage_brackets = _strip_br
            imode = get_interaction_mode(character, gid)
        except Exception as cue_exc:
            logger.debug(f"action_cue guard skip: {cue_exc}")

        def _mark(final_text: str) -> None:
            try:
                note_voice_after_reply(character, gid, final_text)
            except Exception as exc:
                logger.debug(f"voice_pack note skip: {exc}")
            try:
                from .weather import note_weather_after_reply

                note_weather_after_reply(character, gid, final_text, src)
            except Exception as exc:
                logger.debug(f"weather note skip: {exc}")
            if note_after_reply is None:
                return
            try:
                note_after_reply(character, gid, final_text, imode)
            except Exception:
                pass

        def _finish(resp: LLMChatResponse, final_text: str) -> Dict[str, Any]:
            _mark(final_text)
            # env_peer 主动点同伴：计入互聊轮次，达到 max_rounds 后冷却停聊
            if env_peer_mode and chat_sender and getattr(chat_sender, "group_id", None):
                try:
                    _peer_store(self.container).record_reply(
                        str(chat_sender.group_id), character
                    )
                except Exception as exc:
                    logger.debug(f"env_peer chain record failed: {exc}")
            return {"llm_resp": resp}

        def _bracket_hits(sample: str) -> list:
            try:
                if imode == "phone" and any_stage_bracket_hits:
                    return any_stage_bracket_hits(sample)
                if long_bracket_hits:
                    return long_bracket_hits(sample)
            except Exception:
                pass
            return []

        def _wx_hits(sample: str) -> list:
            if "WEATHER: OFF" not in blob and "ACTION: skip_weather" not in blob:
                return []
            try:
                from .weather import reply_mentions_weather as _wx_talk

                if _wx_talk(sample):
                    return ["天气限流"]
            except Exception:
                pass
            return []

        # 1) 本地修括号：不另开 LLM，避免每轮 token 翻倍
        local_text = text
        if imode == "phone" and strip_stage_brackets and _bracket_hits(local_text):
            cleaned = strip_stage_brackets(local_text)
            if cleaned and cleaned != local_text:
                logger.info("style_guard local strip phone brackets")
                local_text = cleaned
                llm_resp = replace_assistant_text(llm_resp, local_text)
        elif drop_long_brackets and _bracket_hits(local_text):
            cleaned = drop_long_brackets(local_text)
            if cleaned and cleaned != local_text:
                logger.info("style_guard local drop long brackets")
                local_text = cleaned
                llm_resp = replace_assistant_text(llm_resp, local_text)

        # 内心括号：冷却中拆掉；否则每轮最多一句。同伴入站另有剥离。
        if mode_l != "story" and imode != "phone":
            try:
                from .action_cue import (
                    drop_inner_asides as _drop_inner,
                    inner_allowed as _inner_ok,
                    keep_one_inner_aside as _one_inner,
                )

                if not _inner_ok(character, gid):
                    cleaned = _drop_inner(local_text)
                    if cleaned != local_text.strip():
                        logger.info(f"style_guard inner cooling character={character}")
                        local_text = cleaned or local_text
                        llm_resp = replace_assistant_text(llm_resp, local_text)
                else:
                    cleaned = _one_inner(local_text)
                    if cleaned != local_text.strip():
                        logger.info(f"style_guard keep one inner character={character}")
                        local_text = cleaned
                        llm_resp = replace_assistant_text(llm_resp, local_text)
            except Exception as inner_exc:
                logger.debug(f"inner aside guard skip: {inner_exc}")

        hits = find_character_violations(
            character,
            local_text,
            trigger_mode=trigger_mode,
            peer_mode=peer_mode,
            env_mode=env_mode,
            env_peer_mode=env_peer_mode,
            user_text=src,
            allow_ask=allow_ask,
            topic_idle=topic_idle,
            require_address=need_addr,
        )
        hits = list(hits) + _bracket_hits(local_text) + _wx_hits(local_text)

        # 2) 提问类优先本地 salvage，仍避免二次满 prompt 重写
        ask_only = hits and all(
            h.startswith("提问") or h.startswith("求证") or h in ("提问句", "求证提问")
            for h in hits
        )
        if ask_only:
            salvaged = salvage_non_ask_reply(local_text)
            if salvaged:
                again = find_character_violations(
                    character,
                    salvaged,
                    trigger_mode=trigger_mode,
                    peer_mode=peer_mode,
                    env_mode=env_mode,
                    env_peer_mode=env_peer_mode,
                    user_text=src,
                    allow_ask=allow_ask,
                    topic_idle=topic_idle,
                    require_address=need_addr,
                )
                again = list(again) + _bracket_hits(salvaged) + _wx_hits(salvaged)
                if not again:
                    logger.info("style_guard local salvage ask → accepted")
                    return _finish(
                        replace_assistant_text(llm_resp, salvaged), salvaged
                    )

        if not hits:
            return _finish(llm_resp, local_text)
        logger.warning(
            f"style_guard hit character={character} mode={message_mode or '-'} "
            f"imode={imode} topic_idle={int(topic_idle)} violations={hits}"
        )
        try:
            llm_manager = self.container.resolve(LLMManager)
        except Exception as exc:
            logger.warning(f"style_guard retry skipped, no LLMManager: {exc}")
            return _finish(llm_resp, local_text)
        model_id = _default_chat_model(self.container, llm_manager)
        # 3) 轻量重写：短 system+原文，不再回灌整段对话
        rewritten = retry_rewrite(
            llm_manager,
            list(prompt or []),
            hits,
            logger,
            model_id=model_id,
            character=character,
            peer_mode=peer_mode,
            env_mode=env_mode,
            env_peer_mode=env_peer_mode,
            dirty_text=local_text,
            user_text=src,
        )
        if rewritten is None:
            salvaged = salvage_non_ask_reply(local_text, original=local_text) if ask_only or any(
                x in hits for x in ("提问句", "求证提问")
            ) else None
            fb = salvaged or fallback_safe_reply(
                character,
                trigger_mode=trigger_mode,
                peer_mode=peer_mode or env_peer_mode,
                env_mode=env_mode and not env_peer_mode,
                user_text=src,
            )
            logger.warning(f"style_guard fallback (no rewrite) → {fb!r}")
            return _finish(replace_assistant_text(llm_resp, fb), fb)
        new_text = scrub_vocative_header(character, _assistant_text(rewritten))
        again = find_character_violations(
            character,
            new_text,
            trigger_mode=trigger_mode,
            peer_mode=peer_mode,
            env_mode=env_mode,
            env_peer_mode=env_peer_mode,
            user_text=src,
            allow_ask=allow_ask,
            topic_idle=topic_idle,
            require_address=need_addr,
        )
        again = list(again) + _bracket_hits(new_text) + _wx_hits(new_text)
        if again and drop_long_brackets and any(h.startswith("括号") for h in again):
            new_text2 = drop_long_brackets(new_text) if imode != "phone" else (
                strip_stage_brackets(new_text) if strip_stage_brackets else new_text
            )
            again2 = find_character_violations(
                character,
                new_text2,
                trigger_mode=trigger_mode,
                peer_mode=peer_mode,
                env_mode=env_mode,
                env_peer_mode=env_peer_mode,
                user_text=src,
                allow_ask=allow_ask,
                topic_idle=topic_idle,
                require_address=need_addr,
            )
            again2 = list(again2) + _bracket_hits(new_text2) + _wx_hits(new_text2)
            if not again2:
                logger.info("style_guard retry+local bracket clean accepted")
                return _finish(
                    replace_assistant_text(llm_resp, new_text2), new_text2
                )
            again = again2
            new_text = new_text2
        if again:
            salvaged = (
                salvage_non_ask_reply(new_text, original=local_text)
                or salvage_non_ask_reply(local_text, original=local_text)
                if any(x in again for x in ("提问句", "求证提问"))
                else None
            )
            fb = salvaged or fallback_safe_reply(
                character,
                trigger_mode=trigger_mode,
                peer_mode=peer_mode or env_peer_mode,
                env_mode=env_mode and not env_peer_mode,
                user_text=src,
            )
            logger.warning(
                f"style_guard retry still dirty violations={again}; fallback → {fb!r}"
            )
            return _finish(replace_assistant_text(llm_resp, fb), fb)
        logger.info("style_guard retry accepted")
        return _finish(
            replace_assistant_text(llm_resp, new_text) if llm_resp else rewritten,
            new_text,
        )



class DialogueContext(Block):
    """分析本轮模式：peer / direct / env / discard，并生成注入文。"""

    name = "dialogue_context"
    inputs = {
        "chat_sender": Input("chat_sender", "聊天对象", ChatSender, "发送者"),
        "user_msg": Input("user_msg", "用户消息", IMMessage, "本轮消息"),
    }
    outputs = {
        "text": Output("text", "对话对象描述", str, "写入 runtime 的对话对象"),
        "extract_priority": Output("extract_priority", "抽取优先级", str, "peer/normal/skip"),
        "message_mode": Output(
            "message_mode", "消息模式", str, "peer|direct|env|discard"
        ),
        "user_prompt_text": Output(
            "user_prompt_text", "本轮注入文", str, "覆盖默认 user prompt"
        ),
        "skip_chat_memory": Output(
            "skip_chat_memory", "跳过对话记忆", str, "true/false"
        ),
        "narration": Output("narration", "环境旁白", str, "env 旁白原文"),
        "narration_source": Output(
            "narration_source", "旁白来源", str, "template|llm|空"
        ),
        "critical_instruction": Output(
            "critical_instruction",
            "P0 指令",
            str,
            "仅 story/direct 非空，挂到系统提示末尾",
        ),
        "interaction_mode": Output(
            "interaction_mode",
            "交互模式",
            str,
            "face|phone；phone 时注入 mode_phone",
        ),
    }
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "anon",
    ):
        self.character = (character or "anon").strip() or "anon"
        self.logger = get_logger("WorldState.Dialogue")

    def _route_story_mode(
        self,
        chat_sender: ChatSender,
        user_msg: IMMessage,
        character: str,
        content: str,
        mentioned: bool,
        group_name: str,
    ) -> Optional[Dict[str, Any]]:
        from .characters import character_by_qq, is_registered_bot_qq

        gid = str(getattr(chat_sender, "group_id", "") or "").strip()
        if not gid:
            return None

        # Host-driven V1.5 owns the group while ACTIVE — suppress legacy @RP story.
        try:
            from .host_manager import StoryHostManager

            try:
                host_mgr = self.container.resolve(StoryHostManager)
            except Exception:
                host_mgr = StoryHostManager(self.container)
            if host_mgr.has_active_for_group(gid):
                from .story import is_story_end_command, is_story_start_command

                extra = [character] if mentioned else []
                mentioned_bots = extract_participating_bots(
                    content, user_msg, extra_ids=extra
                )
                if is_story_start_command(content, mentioned_bots) or is_story_end_command(
                    content
                ):
                    self.logger.info(
                        f"story V1 suppressed (host active) character={character} group={gid}"
                    )
                    return _no_reply_bundle("故事由主持人推进中，请打开网页或 @官方机器人 结束")
                return None
        except Exception as exc:
            self.logger.debug(f"host active check skipped: {exc}")

        sender_qq = str(chat_sender.user_id or "").strip()
        extra = [character] if mentioned else []
        mentioned_bots = extract_participating_bots(
            content, user_msg, extra_ids=extra
        )
        try:
            store = _story_store(self.container)
            session = store.get(gid)
        except Exception as exc:
            self.logger.warning(f"story store miss: {exc}")
            return None

        sender_cid = character_by_qq(sender_qq) if is_registered_bot_qq(sender_qq) else None
        sender_is_participating = bool(
            session and sender_cid and sender_cid in session.participating_bots
        )
        routed = route_story(
            character=character,
            sender_qq=sender_qq,
            group_id=gid,
            content=content,
            mentioned_bots=mentioned_bots,
            session=session,
            sender_is_participating_bot=sender_is_participating,
        )
        if routed.action == "none":
            return None

        if routed.persist and routed.session is not None:
            try:
                store.save(routed.session)
            except Exception as exc:
                self.logger.warning(f"story save failed: {exc}")

        if routed.finalize and routed.session is not None:
            try:
                finalize_story(routed.session, _store(self.container), group_name)
            except Exception as exc:
                self.logger.warning(f"story finalize failed: {exc}")
            try:
                store.clear(gid)
            except Exception as exc:
                self.logger.warning(f"story clear failed: {exc}")

        if routed.action == "discard":
            self.logger.info(
                f"story discard character={character} speaker={routed.speaker}"
            )
            return _no_reply_bundle("故事模式（本轮非你发言）")

        if routed.action == "end":
            self.logger.info(f"story end character={character} group={gid}")
            return {
                "text": "故事结束（OOC确认）",
                "extract_priority": "skip",
                "message_mode": "story_end",
                "user_prompt_text": _build_story_end_prompt(),
                "skip_chat_memory": "true",
                "narration": "",
                "narration_source": "",
            }

        live = routed.session
        if live is None:
            return None
        live.current_speaker = character
        try:
            store.save(live)
        except Exception as exc:
            self.logger.warning(f"story speaker save failed: {exc}")
        self.logger.info(
            f"story {routed.action} character={character} bots={live.participating_bots}"
        )
        return {
            "text": f"故事模式：{live.story_prompt}",
            "extract_priority": "skip",
            "message_mode": "story",
            "user_prompt_text": _build_story_turn_prompt(
                character, live, routed.guide_text
            ),
            "skip_chat_memory": "true",
            "narration": "",
            "narration_source": "",
        }

    def execute(self, chat_sender: ChatSender, user_msg: IMMessage) -> Dict[str, Any]:
        import random

        character = _character_of(self.character, chat_sender)
        content = user_msg.content or ""
        group_name = _group_name(chat_sender, user_msg) or "当下"
        gid = str(getattr(chat_sender, "group_id", "") or "").strip() or "dm"
        display = _public_speaker_name(
            chat_sender.display_name or chat_sender.user_id or ""
        )
        at_self = _mentioned_bot(user_msg, character)
        at_others = _mentioned_others(user_msg, character)
        member_at = at_others and not at_self
        mentioned = addressed_to_self(user_msg, character)
        is_group = chat_sender.chat_type == ChatType.GROUP or bool(chat_sender.group_id)
        force_chat = (content or "").lstrip().lower().startswith("/chat")

        def finish(bundle: Dict[str, Any], src: str = content) -> Dict[str, Any]:
            return _with_critical(character, bundle, src, group_id=gid)

        if is_voice_only(user_msg, content):
            self.logger.info(f"dialogue {character} mode=discard reason=voice_only")
            return finish(_no_reply_bundle("忽略语音条"))

        story_hit = self._route_story_mode(
            chat_sender, user_msg, character, content, mentioned, group_name
        )
        if story_hit is not None:
            return finish(story_hit)

        sender_qq = sender_qq_of(chat_sender, user_msg)
        analysis = analyze_dialogue_target(
            character,
            sender_qq,
            content,
            mentioned_self=at_self,
            is_reply_to_self=False,
        )
        hint = ""
        allowed = True
        wrap = False
        if analysis.get("is_peer") and chat_sender.group_id:
            allowed, hint = _peer_store(self.container).should_continue(
                chat_sender.group_id, character
            )
            wrap = looks_like_wrap_up(strip_inner_asides_for_peer(content))
            if wrap:
                allowed = False
                hint = "对方已经把话收住，本轮不要再接，让对话自然停。"

        # --- 分流 ---
        imm = immersion_config()
        immersion_on = _as_bool(imm.get("enabled"), True)

        if member_at:
            self.logger.info(
                f"dialogue {character} skip-peer member_at=1 "
                f"is_peer={int(bool(analysis.get('is_peer')))} "
                f"sender={sender_qq} kind={analysis.get('sender_kind')}"
            )
        elif analysis.get("is_peer"):
            if peer_should_discard(allowed=allowed, wrap_up=wrap, at_self=at_self):
                if chat_sender.group_id:
                    try:
                        _peer_store(self.container).seal_chain(chat_sender.group_id)
                    except Exception as exc:
                        self.logger.debug(f"peer seal failed: {exc}")
                self.logger.info(
                    f"dialogue {character} mode=peer_stop wrap={int(wrap)} "
                    f"allowed={int(allowed)} at={int(at_self)} sender={sender_qq}"
                )
                return finish(_no_reply_bundle("同伴互聊收束"))
            target = analysis.get("dialogue_target") or "同伴"
            if hint:
                target = f"{target}；{hint}"
            spoken = strip_inner_asides_for_peer(content)
            prompt = (
                f"{turn_object_line(character, is_peer=True)}\n"
                f"{display}对你说：{spoken}"
                + _address_tail(character, gid, spoken)
            )
            if hint:
                prompt += "\n" + hint
            prompt += (
                "\n本轮是同伴互聊，不是外人提问。"
                "问句可以放行，不要改成陈述，不要按外人问答规则过滤。"
                "禁止AI段落句：不要「也行，要是踩雷了找你。周末下午吧我空着」这种排期腔。"
                "对方括号里的内心旁白你听不见，不要接、不要复述、不要当她说出口的话。"
            )
            self.logger.info(
                f"dialogue {character} mode=peer allowed={allowed} "
                f"sender={sender_qq} peer_qq={peer_qq(character)}"
            )
            return finish({
                "text": target,
                "extract_priority": analysis.get("extract_priority") or "peer",
                "message_mode": "peer",
                "user_prompt_text": prompt,
                "skip_chat_memory": "false",
                "narration": "",
                "narration_source": "",
            })

        if looks_like_narrated_scene(content, character) and not mentioned and not member_at:
            prompt = (
                f"【当前场面】{content}\n"
                "这是正在发生的场面，不是有人在向你提问。"
                "你就在现场，用本人口吻直接反应、说话，像手机打字。"
                "禁止导演解说、禁止复盘「这个状况」、禁止规划要不要跳出去。"
                + _voice_tail(character, gid, content)
            )
            self.logger.info(f"dialogue {character} mode=scene_cast")
            return finish({
                "text": "场面（你身处其中，不是被提问）",
                "extract_priority": "skip",
                "message_mode": "scene",
                "user_prompt_text": prompt,
                "skip_chat_memory": "true",
                "narration": "",
                "narration_source": "",
            })

        # 私聊或 /chat：不当环境音。/chat 优先于「只 @ 了别人」。
        if force_chat or not is_group:
            prompt = _build_external_trigger_prompt(character, display, group_name, content, gid)
            self.logger.info(
                f"dialogue {character} mode=direct reason="
                f"{'chat-cmd' if force_chat else 'private'} at={int(at_self)}"
            )
            return finish({
                "text": display or "眼前的人",
                "extract_priority": "skip",
                "message_mode": "direct",
                "user_prompt_text": prompt,
                "skip_chat_memory": "false",
                "narration": "",
                "narration_source": "",
            })

        # @ 了别的群员就是群员之间说话；只是提到名字也不算在跟你说话。
        addressed = (
            not member_at
            and not at_others
            and bool(analysis.get("named_self"))
            and looks_addressed_to_self(content, character)
        )
        if mentioned or addressed:
            prompt = _build_external_trigger_prompt(character, display, group_name, content, gid)
            prompt = (
                f"{turn_object_line(character, is_peer=False)}\n"
                + prompt
            )
            self.logger.info(
                f"dialogue {character} mode=direct at={int(at_self)} "
                f"addressed={int(addressed)} at_others={int(at_others)} "
                f"sender={sender_qq} kind=member"
            )
            return finish({
                "text": display or "眼前的人",
                # EXTERNAL_TRIGGER 触发的剧情反应是单方面演绎，不算同伴间真实互聊，
                # 记忆隔离：跳过长期设定抽取，避免虚构剧情被误记成真实关系进展。
                "extract_priority": "skip",
                "message_mode": "direct",
                "user_prompt_text": prompt,
                "skip_chat_memory": "false",
                "narration": "",
                "narration_source": "",
            })

        if not immersion_on:
            prompt = _build_external_trigger_prompt(character, display, group_name, content, gid)
            return finish({
                "text": display or "眼前的人",
                "extract_priority": "skip",
                "message_mode": "direct",
                "user_prompt_text": prompt,
                "skip_chat_memory": "false",
                "narration": "",
                "narration_source": "",
            })

        kind, narr = to_narration(
            content,
            self.container,
            short_max=int(imm.get("short_text_max_len") or 4),
            llm_min=int(imm.get("narration_llm_min_len") or 12),
            discard_only_emoji=_as_bool(imm.get("discard_only_emoji"), True),
            narration_model=str(imm.get("narration_model") or ""),
        )
        if kind == "discard":
            self.logger.info("discard short/emoji human utterance")
            return finish({
                "text": "环境（无有效声响）",
                "extract_priority": "skip",
                "message_mode": "discard",
                "user_prompt_text": "【系统】本轮无有效环境信息，请只输出：[NO_REPLY]",
                "skip_chat_memory": "true",
                "narration": "",
                "narration_source": "",
            })

        chance = int(imm.get("env_reply_chance") or 100)
        if chance < 100 and random.randint(1, 100) > max(0, chance):
            self.logger.info(f"env reply chance miss ({chance}%)")
            return finish({
                "text": "环境（未回应）",
                "extract_priority": "skip",
                "message_mode": "discard",
                "user_prompt_text": "【系统】本轮不回应环境音，请只输出：[NO_REPLY]",
                "skip_chat_memory": "true",
                "narration": narr,
                "narration_source": kind,
            })

        peer_ping = False
        chain_hint = ""
        ping_chance = int(imm.get("env_peer_ping_chance") or 40)
        if chat_sender.group_id and ping_chance > 0:
            try:
                allowed, chain_hint = _peer_store(self.container).should_continue(
                    chat_sender.group_id, character
                )
                if allowed and peer_qq(character) and random.randint(1, 100) <= max(
                    0, min(100, ping_chance)
                ):
                    peer_ping = True
            except Exception as exc:
                self.logger.debug(f"env peer ping check failed: {exc}")
                peer_ping = False

        if peer_ping:
            prompt = (
                "【当前环境】（空气与声响；本轮允许点同伴续聊）\n"
                f"{narr}"
                + _env_peer_ping_tail(character, chain_hint, gid, narr)
            )
            mode = "env_peer"
        else:
            prompt = (
                "【当前环境】（不是某个具体的人在对你说话；这只是此刻的空气与声响）\n"
                f"{narr}"
                + _env_voice_tail(character, gid, narr)
            )
            mode = "env"
        self.logger.info(
            f"dialogue {character} mode={mode} source={kind} "
            f"at={int(at_self)} at_others={int(at_others)} member_at={int(member_at)} "
            f"peer_ping={int(peer_ping)}"
        )
        return finish({
            "text": (
                "环境旁白（可点同伴）" if peer_ping else "环境旁白（非对话对象）"
            ),
            "extract_priority": "skip",
            "message_mode": mode,
            "user_prompt_text": prompt,
            "skip_chat_memory": "true",
            "narration": narr,
            "narration_source": kind,
        })


class ManageWorldState(Block):
    name = "manage_world_state"
    inputs = {"msg": Input("msg", "IM 消息", IMMessage, "管理命令")}
    outputs = {"msg": Output("msg", "IM 消息", IMMessage, "管理结果")}
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[
            str, ParamMeta(label="角色", description="anon / soyo")
        ] = "anon",
    ):
        self.character = (character or "anon").strip() or "anon"

    def execute(self, msg: IMMessage) -> Dict[str, Any]:
        store = _store(self.container)
        sender = msg.sender
        character = _character_of(self.character, sender)
        scope = _scope_from_sender(sender, character)
        parsed = extract_command(msg.content) or ("help", [])
        verb, args = parsed
        reply = self._handle(store, sender, scope, verb, args, character)
        return {
            "msg": IMMessage(
                sender=ChatSender.get_bot_sender(),
                message_elements=[TextMessage(reply)],
            )
        }

    def _handle(
        self,
        store: WorldStateStore,
        sender: ChatSender,
        scope: str,
        verb: str,
        args: list,
        character: str,
    ) -> str:
        label = get_character(character).get("display") or character
        if verb in ("show",):
            doc = store.get(scope)
            body = store.render(scope)
            title = doc.get("group_name") or scope
            return f"【{label}】群「{title}」长期设定：\n{body}\n\n改法：/长期记忆 设定 relationship 已经告白并交往"
        if verb == "help" or verb == "usage":
            return HELP_TEXT
        if not store.can_edit(sender.user_id):
            return "只有管理员能改本群长期设定。查看仍可用 /长期记忆"
        try:
            if verb == "set":
                store.set_fact(scope, args[0], args[1], source="command")
                return f"已记下 {normalize_key_safe(args[0])}：{args[1]}"
            if verb == "del":
                store.delete_fact(scope, args[0])
                return f"已删除 {args[0]}"
            if verb == "clear":
                store.clear(scope)
                return "已清空本群长期设定（人设和近期聊天记录还在）"
        except KeyError:
            return f"没有叫 {args[0]} 的条目"
        except ValueError as exc:
            return str(exc)
        return HELP_TEXT


def normalize_key_safe(key: str) -> str:
    from .store import normalize_key

    return normalize_key(key)
