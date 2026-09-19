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
    }


def _clean_text(text: str) -> str:
    t = (text or "").replace("\r", " ").replace("\n", " ")
    t = _PLACEHOLDER.sub(" ", t)
    t = _INNER.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace("<break>", " ")
    return t


def _spoken_from(msg: IMMessage, max_chars: int) -> str:
    chunks: List[str] = []
    for el in list(getattr(msg, "message_elements", None) or []):
        if isinstance(el, TextMessage):
            piece = _clean_text(getattr(el, "text", "") or "")
            if piece and not _SKIP_ONLY.match(piece):
                chunks.append(piece)
    spoken = "。".join(chunks).strip("。").strip()
    if len(spoken) > max_chars:
        spoken = spoken[:max_chars].rsplit("。", 1)[0] or spoken[:max_chars]
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
        if not cfg["enabled"] or msg is None:
            return {"msg": msg}
        spoken = _spoken_from(msg, cfg["max_chars"])
        if len(spoken) < cfg["min_chars"]:
            return {"msg": msg}
        audio = _tts(cfg["api_url"], self.character, spoken, cfg["timeout"])
        if not audio:
            return {"msg": msg}
        voice = _voice_element(audio, self.character, self.container)
        if voice is None:
            return {"msg": msg}
        elements = list(msg.message_elements or [])
        if not cfg["keep_text"]:
            elements = [el for el in elements if not isinstance(el, TextMessage)]
        elements.append(voice)
        logger.info(
            f"attached voice character={self.character} bytes={len(audio)} chars={len(spoken)}"
        )
        return {
            "msg": IMMessage(
                sender=msg.sender,
                message_elements=elements,
                raw_message=getattr(msg, "raw_message", None),
            )
        }
