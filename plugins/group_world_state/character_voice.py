"""把角色回复合成语音条：文字先走工作流发送，语音后台另发。"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated, Any, Dict, Optional

import yaml

from kirara_ai.im.message import IMMessage, TextMessage, VoiceMessage
from kirara_ai.ioc.container import DependencyContainer
from kirara_ai.logger import get_logger
from kirara_ai.workflow.core.block import Block, Input, Output, ParamMeta

from .characters import get_character
from .ja_phrases import (
    clip_to_japanese,
    first_voice_clip,
    is_spoken_japanese,
    ja_has_zh_leftover,
    normalize_ja_for_tts,
)

try:
    from kirara_ai.media.manager import MediaManager
except Exception:  # pragma: no cover
    MediaManager = None  # type: ignore

logger = get_logger("CharacterVoice")

CONFIG_PATH = Path("data/tts/config.yaml")
_PLACEHOLDER = re.compile(r"\[(图片|语音|语音消息|系统提示)[^\]]*\]")
_INNER = re.compile(r"[（(][^）)]{0,80}[）)]")
_SKIP_ONLY = re.compile(r"^[\s\[\]【】.。!！?？~～、,，]+$")


def _sf_api_base(raw: str) -> str:
    b = (raw or "").strip().rstrip("/")
    if not b:
        return "https://api.siliconflow.cn/v1"
    if b.endswith("/v1"):
        return b
    return b + "/v1"


def _load_config() -> dict:
    cfg: dict = {}
    if CONFIG_PATH.exists():
        try:
            cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning(f"tts config read failed: {exc}")
    url = (os.environ.get("CHARACTER_TTS_URL") or cfg.get("api_url") or "").strip()
    enabled = cfg.get("enabled", True)
    env_enabled = os.environ.get("CHARACTER_TTS_ENABLED")
    if env_enabled is not None:
        enabled = env_enabled.strip().lower() not in ("0", "false", "no", "off")
    return {
        "enabled": bool(enabled) and bool(url),
        "api_url": url.rstrip("/"),
        "timeout": int(cfg.get("timeout_seconds") or 90),
        "keep_text": bool(cfg.get("keep_text", True)),
        "max_chars": int(cfg.get("max_chars") or 180),
        "min_chars": int(cfg.get("min_chars") or 1),
        "convert_ja": bool(cfg.get("convert_ja", False)),
        "max_sentences": int(cfg.get("max_sentences") or 1),
        "sf_base": _sf_api_base(
            os.environ.get("SILICONFLOW_CHAT_BASE")
            or os.environ.get("SILICONFLOW_BASE")
            or (cfg.get("translate") or {}).get("api_base")
            or ""
        ),
        "sf_model": str(
            os.environ.get("SILICONFLOW_TTS_MODEL")
            or (cfg.get("translate") or {}).get("model")
            or "Qwen/Qwen2.5-72B-Instruct"
        ).strip(),
        "sf_key": (
            os.environ.get("SILICONFLOW_API_KEY")
            or os.environ.get("SF_KEY")
            or ""
        ).strip(),
        "sf_timeout": int((cfg.get("translate") or {}).get("timeout_seconds") or 60),
        "sf_max_tokens": int((cfg.get("translate") or {}).get("max_tokens") or 220),
    }


def _clean_text(text: str) -> str:
    t = (text or "").replace("\r", " ").replace("\n", " ")
    t = _PLACEHOLDER.sub(" ", t)
    t = _INNER.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace("<break>", " ")
    return t


def _light_clean(text: str) -> str:
    t = (text or "").replace("\r", "\n")
    t = _PLACEHOLDER.sub(" ", t)
    t = _INNER.sub(" ", t)
    t = t.replace("<break>", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def _first_utterance(msg: IMMessage, max_chars: int) -> str:
    for el in list(getattr(msg, "message_elements", None) or []):
        if not isinstance(el, TextMessage):
            continue
        piece = _light_clean(getattr(el, "text", "") or "")
        if piece and not _SKIP_ONLY.match(piece.replace("\n", "")):
            if len(piece) > max_chars:
                piece = piece[:max_chars]
            return piece
    return ""


def _looks_ja(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff]", text or ""))


def _looks_spoken(text: str, zh: str = "") -> bool:
    return is_spoken_japanese(text, zh)


_NAME_RULE = (
    "人名必须保留，并固定罗马音："
    "爱音/小爱音/千早爱音/Anon/あのん → anon chan ；"
    "素世/长崎素世/soyo/soyorin/そよ → soyorin。"
    "不要译成中文拼音，不要写成假名。"
)

_JA_QUALITY = (
    "必须译成完整、自然、能直接朗读的日语句子：助词（は/が/を/に/の/て）不能省，主谓齐全。"
    "禁止中日夹杂，禁止残留任何简体或繁体中文（包括什么、嘿嘿、哈哈、语音、听到、嘛、吗、吧、啦）。"
    "语气词改写成日文：诶→え、嘿嘿→えへへ、哈哈→あはは、嗯→うん、啊→あ。"
    "必须保留原文里的店、食物、人名、地点，不要概括成别的意思。"
    f"{_NAME_RULE}"
    "除人名罗马音外，只用日文假名和常用汉字。"
)

_JA_EXAMPLES = (
    "示例："
    "「嘿嘿，soyorin～听到我叫你了吗？」→「えへへ、soyorin、呼んでるの、聞こえた？」"
    "「听到了，小爱音，声音那么亮当然能注意到。」→「聞こえたよ、anon chan、声があんなに大きいんだから気づかないわけないでしょ。」"
    "「顺耳什么啊。」→「耳触りいいって、何よ。」"
)

_JA_SYS = {
    "anon": (
        "把下面这句中文口语译成爱音会说的完整日文句。"
        f"{_JA_QUALITY}"
        f"{_JA_EXAMPLES}"
        "只输出一行日文，不要解释，不要引号，不要 Markdown。"
    ),
    "soyo": (
        "把下面这句中文口语译成素世会说的完整日文句。"
        f"{_JA_QUALITY}"
        f"{_JA_EXAMPLES}"
        "只输出一行日文，不要解释，不要引号，不要 Markdown。"
    ),
}

_CLIP_SYS = {
    "anon": (
        "你是爱音的语音台词编辑。从她这轮中文回复里切出第一句完整口语，再译成日文。"
        "切句必须是完整的一句（叫名和后面那句可以算一句），不要半截词，也不要整段独白。"
        f"{_JA_QUALITY}"
        f"{_JA_EXAMPLES}"
        "只输出一行 JSON：{\"zh\":\"切出的中文\",\"ja\":\"完整日文句\"}。"
        "不要解释，不要 Markdown。"
    ),
    "soyo": (
        "你是素世的语音台词编辑。从她这轮中文回复里切出第一句完整口语，再译成日文。"
        "切句必须是完整的一句（叫名和后面那句可以算一句），不要半截词，也不要整段独白。"
        f"{_JA_QUALITY}"
        f"{_JA_EXAMPLES}"
        "只输出一行 JSON：{\"zh\":\"切出的中文\",\"ja\":\"完整日文句\"}。"
        "不要解释，不要 Markdown。"
    ),
}


def _llm_to_ja(manager: Any, character: str, clip: str) -> str:
    if manager is None:
        return ""
    try:
        from kirara_ai.llm.format.message import LLMChatMessage, LLMChatTextContent
        from kirara_ai.llm.format.request import LLMChatRequest
    except Exception as exc:
        logger.warning(f"tts ja import failed: {exc}")
        return ""
    try:
        cfg = getattr(manager, "config", None)
        mid = str(getattr(getattr(cfg, "defaults", None), "llm_model", "") or "").strip()
        llm = manager.get_llm(mid) if mid else None
        if not llm:
            return ""
        prompt = [
            LLMChatMessage(
                role="system",
                content=[LLMChatTextContent(text=_JA_SYS.get(character) or _JA_SYS["anon"])],
            ),
            LLMChatMessage(
                role="user",
                content=[LLMChatTextContent(text=f"原文：{clip}")],
            ),
        ]
        # Kirara 的 LLMChatRequest.temperature 只要整数；翻译用默认温度即可。
        try:
            req = LLMChatRequest(messages=prompt, model=mid, max_tokens=160)
        except Exception:
            req = LLMChatRequest(messages=prompt, model=mid)
        resp = llm.chat(req)
        text = ""
        msg = getattr(resp, "message", None)
        for part in getattr(msg, "content", None) or []:
            text += getattr(part, "text", None) or ""
        text = (text or "").strip().strip("\"'`")
        if text.startswith("```"):
            text = re.sub(r"^```(?:\w+)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        return text.splitlines()[0].strip() if text else ""
    except Exception as exc:
        logger.warning(f"tts ja llm failed: {exc}")
        return ""


def _sf_models(cfg: dict) -> list[str]:
    primary = str(cfg.get("sf_model") or "").strip()
    out: list[str] = []
    for m in (primary, "Qwen/Qwen2.5-72B-Instruct", "Qwen/Qwen2.5-32B-Instruct"):
        if m and m not in out:
            out.append(m)
    return out


def _sf_chat(cfg: dict, system: str, user: str) -> str:
    key = cfg.get("sf_key") or ""
    if not key:
        return ""
    last_err = ""
    for model in _sf_models(cfg):
        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": int(cfg.get("sf_max_tokens") or 220),
                "temperature": 0.2,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            cfg["sf_base"] + "/chat/completions",
            data=payload,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "User-Agent": "kirara-character-voice",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=int(cfg.get("sf_timeout") or 60)) as resp:
                body = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            last_err = f"{exc.code}: {detail}"
            if exc.code in (400, 404) and "model" in detail.lower():
                logger.warning(f"siliconflow model skip {model}: {last_err}")
                continue
            logger.warning(f"siliconflow http {last_err}")
            return ""
        except Exception as exc:
            logger.warning(f"siliconflow request failed: {exc}")
            return ""
        choices = body.get("choices") if isinstance(body, dict) else None
        if not choices:
            continue
        msg = (choices[0] or {}).get("message") or {}
        text = str(msg.get("content") or "").strip().strip("\"'`")
        if text.startswith("```"):
            text = re.sub(r"^```(?:\w+)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        if text:
            if model != cfg.get("sf_model"):
                logger.info(f"siliconflow using model={model}")
            return text
    if last_err:
        logger.warning(f"siliconflow failed: {last_err}")
    return ""


def _parse_clip_json(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "", ""
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        blob = raw[start : end + 1] if start >= 0 and end > start else raw
        data = json.loads(blob)
        zh = str(data.get("zh") or data.get("clip") or "").strip()
        ja = str(data.get("ja") or data.get("jp") or "").strip()
        return zh, ja
    except Exception:
        return "", raw


def _sf_translate(cfg: dict, character: str, clip: str) -> str:
    if not (cfg.get("sf_key") and (clip or "").strip()):
        return ""
    out = _sf_chat(cfg, _JA_SYS.get(character) or _JA_SYS["anon"], f"原文：{clip.strip()}")
    _zh, ja = _parse_clip_json(out)
    if _looks_spoken(ja, clip):
        return normalize_ja_for_tts(ja)
    line = (out or "").splitlines()[0].strip() if out else ""
    spoken = normalize_ja_for_tts(line)
    return spoken if _looks_spoken(spoken, clip) else ""


def _sf_clip_and_translate(cfg: dict, character: str, raw: str) -> tuple[str, str]:
    """硅基流动：切片 + 完整日译。返回 (中文切片, 日文)。失败则空。"""
    if not (cfg.get("sf_key") and (raw or "").strip()):
        return "", ""
    sys_prompt = _CLIP_SYS.get(character) or _CLIP_SYS["anon"]
    out = _sf_chat(cfg, sys_prompt, f"角色：{character}\n原文：{raw.strip()}")
    zh, ja = _parse_clip_json(out)
    ja = normalize_ja_for_tts(ja)
    if not _looks_spoken(ja, zh or raw):
        if ja_has_zh_leftover(ja, zh or raw):
            logger.info(f"siliconflow leftover ja={ja!r} zh={zh!r}")
        ja = _sf_translate(cfg, character, zh or first_voice_clip(raw) or raw)
    if not _looks_spoken(ja, zh or raw):
        return zh, ""
    return zh, ja


def _to_spoken_ja(manager: Any, character: str, clip: str, cfg: Optional[dict] = None) -> str:
    spoken = clip_to_japanese(clip, character)
    if not _looks_spoken(spoken, clip) and cfg:
        spoken = _sf_translate(cfg, character, clip)
    if not _looks_spoken(spoken, clip):
        spoken = _llm_to_ja(manager, character, clip)
    spoken = normalize_ja_for_tts(spoken)
    if not _looks_spoken(spoken, clip):
        return ""
    return spoken


_TTS_LOCK = threading.Lock()


def _tts(api_url: str, character: str, text: str, timeout: int) -> Optional[bytes]:
    payload = json.dumps({"character": character, "text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        api_url + "/tts",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "kirara-character-voice"},
        method="POST",
    )
    try:
        with _TTS_LOCK:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                data = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        logger.warning(f"tts http {exc.code}: {detail}")
        return None
    except Exception as exc:
        logger.warning(f"tts request failed: {exc}")
        return None
    if not data or "json" in ctype:
        logger.warning("tts returned no audio")
        return None
    return data


def _voice_element(audio: bytes, character: str, media_manager: Any = None) -> Optional[VoiceMessage]:
    kwargs: Dict[str, Any] = {
        "data": audio,
        "format": "wav",
        "description": f"{character} tts",
    }
    if media_manager is not None:
        kwargs["media_manager"] = media_manager
    try:
        voice = VoiceMessage(**kwargs)
    except Exception as exc:
        logger.warning(f"VoiceMessage init failed: {exc}")
        return None
    voice.url = "base64://" + base64.b64encode(audio).decode("ascii")
    return voice


# env/场面/故事/丢弃不出声。peer / env_peer / direct 都出声，但语音不挡文字发送。
_SKIP_VOICE_MODES = {
    "env",
    "scene",
    "discard",
    "story",
    "story_end",
}

_FALLBACK_IM = {
    "anon": "qq_user_bot",
    "soyo": "qq_soyo",
}


def _voice_im_name(character: str) -> str:
    im = str(get_character(character).get("im_name") or "").strip()
    if im and im != "qq_official_bot":
        return im
    return _FALLBACK_IM.get(character, "")


def _capture_send_ctx(container: DependencyContainer, character: str) -> Optional[Dict[str, Any]]:
    try:
        from kirara_ai.im.manager import IMManager
        from kirara_ai.llm.llm_manager import LLMManager
    except Exception as exc:
        logger.warning(f"voice send import failed: {exc}")
        return None
    im_name = _voice_im_name(character)
    if not im_name:
        logger.warning(f"skip voice character={character} reason=no_im")
        return None
    try:
        adapter = container.resolve(IMManager).get_adapter(im_name)
        loop = container.resolve(asyncio.AbstractEventLoop)
        incoming = container.resolve(IMMessage)
        recipient = getattr(incoming, "sender", None)
    except Exception as exc:
        logger.warning(f"voice send ctx failed: {exc}")
        return None
    if adapter is None or loop is None or recipient is None:
        logger.warning(f"skip voice character={character} reason=send_ctx")
        return None
    llm_manager = None
    try:
        llm_manager = container.resolve(LLMManager)
    except Exception:
        llm_manager = None
    media_manager = None
    if MediaManager is not None:
        try:
            media_manager = container.resolve(MediaManager)
        except Exception:
            media_manager = None
    return {
        "adapter": adapter,
        "im_name": im_name,
        "loop": loop,
        "recipient": recipient,
        "llm_manager": llm_manager,
        "media_manager": media_manager,
    }


def _schedule_voice(
    character: str,
    raw: str,
    cfg: dict,
    outgoing_sender: Any,
    ctx: Dict[str, Any],
) -> None:
    def worker() -> None:
        try:
            clip = ""
            spoken = ""
            zh, ja = _sf_clip_and_translate(cfg, character, raw)
            if ja:
                clip = zh or first_voice_clip(raw) or raw[:80]
                spoken = ja
                logger.info(
                    f"siliconflow clip character={character} zh={clip!r} ja={spoken!r}"
                )
            if not spoken:
                clip = first_voice_clip(raw)
                if len(clip) < cfg["min_chars"]:
                    logger.info(
                        f"skip voice character={character} reason=empty clip raw={raw!r}"
                    )
                    return
                spoken = _to_spoken_ja(ctx["llm_manager"], character, clip, cfg)
            if not spoken:
                logger.info(f"skip voice character={character} reason=no_ja clip={clip!r}")
                return
            audio = _tts(cfg["api_url"], character, spoken, cfg["timeout"])
            if not audio:
                logger.warning(
                    f"skip voice character={character} reason=tts_fail ja={spoken!r} clip={clip!r}"
                )
                return
            voice = _voice_element(audio, character, ctx["media_manager"])
            if voice is None:
                logger.warning(f"skip voice character={character} reason=voice_init ja={spoken!r}")
                return
            voice_msg = IMMessage(sender=outgoing_sender, message_elements=[voice])

            async def _send() -> None:
                # 让工作流里先入队的文字发送跑完，避免语音条抢在互聊原文前面。
                await asyncio.sleep(1.2)
                await ctx["adapter"].send_message(voice_msg, ctx["recipient"])

            fut = asyncio.run_coroutine_threadsafe(_send(), ctx["loop"])
            fut.result(timeout=max(30, int(cfg["timeout"]) + 15))
            logger.info(
                f"sent voice character={character} bytes={len(audio)} clip={clip!r} ja={spoken!r}"
            )
        except Exception as exc:
            logger.warning(f"async voice failed character={character}: {exc}")

    threading.Thread(target=worker, name=f"character-voice-{character}", daemon=True).start()


class AttachCharacterVoice(Block):
    """文字原样放行；peer/direct 在后台另发一条语音。失败不影响互聊发送。"""

    name = "attach_voice"
    inputs = {
        "msg": Input("msg", "IM 消息", IMMessage, "待发送的文字回复"),
        "message_mode": Input(
            "message_mode",
            "消息模式",
            str,
            "env/scene/story 不出声；peer/direct 后台另发语音",
            nullable=True,
        ),
    }
    outputs = {
        "msg": Output("msg", "IM 消息", IMMessage, "原文字消息，不附带语音"),
    }
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[str, ParamMeta(label="角色", description="anon / soyo")] = "anon",
    ):
        self.character = (character or "anon").strip() or "anon"

    def execute(self, msg: IMMessage, message_mode: Optional[str] = None) -> Dict[str, Any]:
        cfg = _load_config()
        if msg is None:
            return {"msg": msg}
        mode = (message_mode or "").strip()
        if mode in _SKIP_VOICE_MODES:
            logger.info(f"skip voice character={self.character} reason=mode mode={mode}")
            return {"msg": msg}
        if not cfg["enabled"]:
            logger.info("skip voice: disabled or missing CHARACTER_TTS_URL")
            return {"msg": msg}
        raw = _first_utterance(msg, cfg["max_chars"])
        if raw.strip() in ("", "[NO_REPLY]"):
            logger.info(f"skip voice character={self.character} reason=empty clip raw={raw!r}")
            return {"msg": msg}
        ctx = _capture_send_ctx(self.container, self.character)
        if ctx is None:
            return {"msg": msg}
        _schedule_voice(self.character, raw, cfg, getattr(msg, "sender", None), ctx)
        logger.info(
            f"scheduled voice character={self.character} mode={mode or '-'} "
            f"sf={'1' if cfg.get('sf_key') else '0'} raw={raw[:80]!r}"
        )
        return {"msg": msg}
