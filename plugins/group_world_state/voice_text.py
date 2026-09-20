"""群聊里的语音条：不进记忆、不打断互聊。"""
from __future__ import annotations

import re
from typing import Any, List, Optional

_VOICE_PLAIN = re.compile(r"\[(?:语音|语音消息|语音条)[^\]]*\]|\[CQ:record[^\]]*\]", re.I)
_HAN_KANA = re.compile(r"[\u4e00-\u9fffA-Za-z0-9ぁ-んァ-ン]")
_JA_KANA = re.compile(r"[\u3040-\u30ff]")
_ZH_HAN = re.compile(r"[\u4e00-\u9fff]")


def _type_name(el: Any) -> str:
    return type(el).__name__.lower()


def is_voice_element(el: Any) -> bool:
    name = _type_name(el)
    if "voice" in name or "record" in name:
        return True
    desc = str(getattr(el, "description", "") or "").lower()
    if "tts" in desc or "语音" in desc:
        return True
    try:
        plain = str(el.to_plain() or "")
    except Exception:
        plain = ""
    return bool(_VOICE_PLAIN.search(plain))


def has_voice(msg: Any) -> bool:
    for el in list(getattr(msg, "message_elements", None) or []):
        if is_voice_element(el):
            return True
    raw = getattr(msg, "raw_message", None)
    blobs = [str(getattr(msg, "content", "") or "")]
    if isinstance(raw, dict):
        blobs.append(str(raw.get("raw_message") or raw.get("message") or ""))
        segs = raw.get("message")
        if isinstance(segs, list):
            for seg in segs:
                typ = str((seg or {}).get("type") if isinstance(seg, dict) else getattr(seg, "type", "") or "")
                if typ.lower() in ("record", "voice"):
                    return True
    return any(_VOICE_PLAIN.search(b) for b in blobs)


def spoken_text(msg: Any, content: Optional[str] = None) -> str:
    bits: List[str] = []
    for el in list(getattr(msg, "message_elements", None) or []):
        if is_voice_element(el):
            continue
        try:
            from kirara_ai.im.message import TextMessage

            if isinstance(el, TextMessage):
                bits.append(str(getattr(el, "text", "") or el.to_plain() or ""))
                continue
        except Exception:
            pass
        try:
            bits.append(str(el.to_plain() or ""))
        except Exception:
            continue
    text = "".join(bits) if bits else str(content if content is not None else getattr(msg, "content", "") or "")
    text = _VOICE_PLAIN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_tts_caption(text: str) -> bool:
    """带假名的合成日文：群里互聊只发中文，这类文案不当新的一句。"""
    t = _VOICE_PLAIN.sub(" ", (text or "")).strip()
    if not t:
        return False
    return bool(_JA_KANA.search(t))


def is_voice_bar_event(msg: Any, content: Optional[str] = None) -> bool:
    """语音条不是一条新消息：它和前面那句中文是同一轮，不调度、不计数、不入库。"""
    text = spoken_text(msg, content)
    if has_voice(msg):
        if text and _ZH_HAN.search(text) and not is_tts_caption(text):
            return False
        return True
    if is_tts_caption(text):
        return True
    raw = str(content if content is not None else getattr(msg, "content", "") or "")
    return bool(_VOICE_PLAIN.search(raw) and not _ZH_HAN.search(raw))


def is_voice_only(msg: Any, content: Optional[str] = None) -> bool:
    return is_voice_bar_event(msg, content)


def strip_voice_message(msg: Any) -> Any:
    """去掉语音元素，只留文字。没有文字则返回原对象但调用方可据此跳过入库。"""
    if msg is None:
        return msg
    elements = list(getattr(msg, "message_elements", None) or [])
    kept = [el for el in elements if not is_voice_element(el)]
    if len(kept) == len(elements):
        return msg
    try:
        from kirara_ai.im.message import IMMessage

        return IMMessage(
            sender=getattr(msg, "sender", None),
            message_elements=kept,
            raw_message=getattr(msg, "raw_message", None),
        )
    except Exception:
        return msg
