"""把角色回复合成语音条，挂到 NapCat 发出的 IMMessage 上。"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import yaml

from kirara_ai.im.message import IMMessage, TextMessage, VoiceMessage
from kirara_ai.ioc.container import DependencyContainer
from kirara_ai.logger import get_logger
from kirara_ai.workflow.core.block import Block, Input, Output, ParamMeta

from .ja_phrases import clip_to_japanese, first_voice_clip, normalize_ja_for_tts

try:
    from kirara_ai.media.manager import MediaManager
except Exception:  # pragma: no cover
    MediaManager = None  # type: ignore

logger = get_logger("CharacterVoice")

CONFIG_PATH = Path("data/tts/config.yaml")
_PLACEHOLDER = re.compile(r"\[(图片|语音|语音消息|系统提示)[^\]]*\]")
_INNER = re.compile(r"[（(][^）)]{0,80}[）)]")
_SKIP_ONLY = re.compile(r"^[\s\[\]【】.。!！?？~～、,，]+$")


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


_JA_SYS = {
    "anon": (
        "把下面这句中文口语译成自然日文短句。"
        "必须保留原文里的具体事物（店、食物、人名、地点），不要概括成别的意思。"
        "不要添加原文没有的 え、マジ、なにそれ。"
        "只输出一行日文（假名+常用汉字），不要中文简体，不要解释，不要引号。"
    ),
    "soyo": (
        "把下面这句中文口语译成自然日文短句。"
        "必须保留原文里的具体事物（店、食物、人名、地点），不要概括成别的意思。"
        "不要添加原文没有的语气词。"
        "只输出一行日文（假名+常用汉字），不要中文简体，不要解释，不要引号。"
    ),
}


def _llm_to_ja(container: DependencyContainer, character: str, clip: str) -> str:
    try:
        from kirara_ai.llm.format.message import LLMChatMessage, LLMChatTextContent
        from kirara_ai.llm.format.request import LLMChatRequest
        from kirara_ai.llm.llm_manager import LLMManager
    except Exception as exc:
        logger.warning(f"tts ja import failed: {exc}")
        return ""
    try:
        manager = container.resolve(LLMManager)
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
            req = LLMChatRequest(messages=prompt, model=mid, max_tokens=80)
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


def _to_spoken_ja(container: DependencyContainer, character: str, clip: str) -> str:
    spoken = clip_to_japanese(clip, character)
    if not _looks_ja(spoken):
        spoken = _llm_to_ja(container, character, clip)
    spoken = normalize_ja_for_tts(spoken)
    if not _looks_ja(spoken):
        return ""
    return spoken


def _tts(api_url: str, character: str, text: str, timeout: int) -> Optional[bytes]:
    payload = json.dumps({"character": character, "text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        api_url + "/tts",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "kirara-character-voice"},
        method="POST",
    )
    try:
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


def _voice_element(audio: bytes, character: str, container: DependencyContainer) -> Optional[VoiceMessage]:
    kwargs: Dict[str, Any] = {
        "data": audio,
        "format": "wav",
        "description": f"{character} tts",
    }
    if MediaManager is not None:
        try:
            kwargs["media_manager"] = container.resolve(MediaManager)
        except Exception:
            pass
    try:
        voice = VoiceMessage(**kwargs)
    except Exception as exc:
        logger.warning(f"VoiceMessage init failed: {exc}")
        return None
    voice.url = "base64://" + base64.b64encode(audio).decode("ascii")
    return voice


class AttachCharacterVoice(Block):
    """给角色回复附加一条合成语音。失败则原样放行文字。"""

    name = "attach_voice"
    inputs = {
        "msg": Input("msg", "IM 消息", IMMessage, "待发送的文字回复"),
    }
    outputs = {
        "msg": Output("msg", "IM 消息", IMMessage, "附带语音条的消息"),
    }
    container: DependencyContainer

    def __init__(
        self,
        character: Annotated[str, ParamMeta(label="角色", description="anon / soyo")] = "anon",
    ):
        self.character = (character or "anon").strip() or "anon"

    def execute(self, msg: IMMessage) -> Dict[str, Any]:
        cfg = _load_config()
        if msg is None:
            return {"msg": msg}
        if not cfg["enabled"]:
            logger.info("skip voice: disabled or missing CHARACTER_TTS_URL")
            return {"msg": msg}
        raw = _first_utterance(msg, cfg["max_chars"])
        clip = first_voice_clip(raw)
        if len(clip) < cfg["min_chars"]:
            logger.info(f"skip voice character={self.character} reason=empty clip raw={raw!r}")
            return {"msg": msg}
        spoken = _to_spoken_ja(self.container, self.character, clip)
        if not spoken:
            logger.info(f"skip voice character={self.character} reason=no_ja clip={clip!r}")
            return {"msg": msg}
        audio = _tts(cfg["api_url"], self.character, spoken, cfg["timeout"])
        if not audio:
            logger.warning(
                f"skip voice character={self.character} reason=tts_fail ja={spoken!r} clip={clip!r}"
            )
            return {"msg": msg}
        voice = _voice_element(audio, self.character, self.container)
        if voice is None:
            logger.warning(f"skip voice character={self.character} reason=voice_init ja={spoken!r}")
            return {"msg": msg}
        elements = list(msg.message_elements or [])
        if not cfg["keep_text"]:
            elements = [el for el in elements if not isinstance(el, TextMessage)]
        elements.append(voice)
        logger.info(
            f"attached voice character={self.character} bytes={len(audio)} clip={clip!r} ja={spoken!r}"
        )
        return {
            "msg": IMMessage(
                sender=msg.sender,
                message_elements=elements,
                raw_message=getattr(msg, "raw_message", None),
            )
        }
