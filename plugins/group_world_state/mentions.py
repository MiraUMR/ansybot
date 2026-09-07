"""按 QQ 判断 @ / 引用：分发层和对话分流共用，避免两套逻辑漂移。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from kirara_ai.im.message import IMMessage, MentionElement
from kirara_ai.im.sender import ChatSender

from .characters import get_character, is_registered_bot_qq

_CQ_AT_RE = re.compile(r"\[CQ:at,[^\]]*qq=(\d+|all)[^\]]*\]", re.IGNORECASE)
_CQ_REPLY_RE = re.compile(r"\[CQ:reply,[^\]]*\]", re.IGNORECASE)


def _seg_type(seg: Any) -> str:
    if isinstance(seg, dict):
        return str(seg.get("type") or "")
    return str(getattr(seg, "type", "") or "")


def _seg_data(seg: Any) -> Dict[str, Any]:
    if isinstance(seg, dict):
        data = seg.get("data")
    else:
        data = getattr(seg, "data", None)
    return data if isinstance(data, dict) else {}


def _as_segment_list(msg: Any) -> List[Any]:
    if msg is None:
        return []
    if isinstance(msg, str):
        segs: List[Any] = []
        for match in _CQ_AT_RE.finditer(msg):
            segs.append({"type": "at", "data": {"qq": match.group(1)}})
        if _CQ_REPLY_RE.search(msg):
            segs.append({"type": "reply", "data": {}})
        return segs
    if isinstance(msg, (list, tuple)):
        return list(msg)
    try:
        return list(msg)
    except Exception:
        return []


def raw_text_blobs(user_msg: IMMessage) -> List[str]:
    blobs = [str(getattr(user_msg, "content", "") or "")]
    raw = getattr(user_msg, "raw_message", None)
    if raw is None:
        return blobs
    try:
        if isinstance(raw, dict):
            blobs.append(str(raw.get("raw_message") or raw.get("message") or ""))
        else:
            blobs.append(str(getattr(raw, "raw_message", "") or ""))
            msg = getattr(raw, "message", None)
            if isinstance(msg, str):
                blobs.append(msg)
    except Exception:
        pass
    return blobs


def raw_segments(user_msg: IMMessage) -> List[Any]:
    raw = getattr(user_msg, "raw_message", None)
    segs: List[Any] = []
    if raw is not None:
        try:
            if isinstance(raw, dict):
                segs.extend(_as_segment_list(raw.get("message") or raw.get("message_chain")))
                segs.extend(_as_segment_list(raw.get("raw_message")))
            else:
                segs.extend(_as_segment_list(getattr(raw, "message", None)))
                segs.extend(_as_segment_list(getattr(raw, "raw_message", None)))
                getter = getattr(raw, "get_message", None)
                if callable(getter):
                    segs.extend(_as_segment_list(getter()))
        except Exception:
            pass
    segs.extend(_as_segment_list(getattr(user_msg, "content", None)))
    return segs


def _digits_qq(raw: Any) -> str:
    s = str(raw or "").strip()
    if s.isdigit():
        return s
    match = re.search(r"(\d{5,})", s)
    return match.group(1) if match else s


def sender_qq_of(chat_sender: Optional[ChatSender], user_msg: Optional[IMMessage] = None) -> str:
    """发送者 QQ：优先白名单 Bot，避免 ChatSender / OneBot 字段不一致把互聊判成群友。"""
    cands: List[str] = []
    if chat_sender is not None:
        cands.append(_digits_qq(getattr(chat_sender, "user_id", "")))
    raw = getattr(user_msg, "raw_message", None) if user_msg is not None else None
    if isinstance(raw, dict):
        cands.append(_digits_qq(raw.get("user_id")))
        sender = raw.get("sender")
        if isinstance(sender, dict):
            cands.append(_digits_qq(sender.get("user_id") or sender.get("userId") or sender.get("qq")))
        elif sender is not None:
            cands.append(_digits_qq(getattr(sender, "user_id", "") or getattr(sender, "qq", "")))
    seen = []
    for qq in cands:
        if qq and qq not in seen:
            seen.append(qq)
    for qq in seen:
        if is_registered_bot_qq(qq):
            return qq
    return seen[0] if seen else ""


def self_qq(user_msg: IMMessage, character: str = "") -> str:
    """本账号 QQ：OneBot 事件的 self_id 最准，否则回落 characters.yaml。"""
    raw = getattr(user_msg, "raw_message", None)
    if raw is not None:
        try:
            sid = raw.get("self_id") if isinstance(raw, dict) else getattr(raw, "self_id", "")
            sid = str(sid or "").strip()
            if sid:
                return sid
        except Exception:
            pass
    return str(get_character(character).get("qq") or "").strip()


def at_target_qqs(user_msg: IMMessage) -> Tuple[set, bool]:
    """返回 (被@的QQ集合, 是否@全体)。"""
    targets = set()
    at_all = False
    for seg in raw_segments(user_msg):
        if _seg_type(seg) != "at":
            continue
        qq = str(
            _seg_data(seg).get("qq")
            or _seg_data(seg).get("user_id")
            or getattr(seg, "qq", "")
            or ""
        ).strip()
        if qq.lower() == "all":
            at_all = True
        elif qq and qq != "bot":
            targets.add(qq)
    for el in user_msg.message_elements or []:
        uid = str(getattr(el, "user_id", "") or "").strip()
        if uid.lower() == "all":
            at_all = True
        elif uid and uid != "bot":
            targets.add(uid)
        target = getattr(el, "target", None)
        if target is not None:
            tid = str(getattr(target, "user_id", "") or "").strip()
            if tid and tid != "bot":
                targets.add(tid)
    for blob in raw_text_blobs(user_msg):
        for match in _CQ_AT_RE.finditer(blob):
            qq = str(match.group(1) or "").strip()
            if qq.lower() == "all":
                at_all = True
            elif qq:
                targets.add(qq)
    return targets, at_all


def mentioned_bot(user_msg: IMMessage, character: str = "") -> bool:
    """只认 QQ：@ 到本账号才算被 @；@全体、@别人都不算。"""
    me = self_qq(user_msg, character)
    for seg in raw_segments(user_msg):
        if _seg_type(seg) != "at":
            continue
        data = _seg_data(seg)
        if data.get("is_bot"):
            qq = str(data.get("qq") or "").strip()
            if me and qq == me:
                return True
            continue
    targets, _ = at_target_qqs(user_msg)
    if me and me in targets:
        return True
    if targets:
        return False
    bot_sender = ChatSender.get_bot_sender()
    return any(
        isinstance(el, MentionElement) and el.target == bot_sender
        for el in (user_msg.message_elements or [])
    )


def mentioned_others(user_msg: IMMessage, character: str = "") -> bool:
    """群员 @ 的是别人：这轮不是冲你来的。"""
    targets, _ = at_target_qqs(user_msg)
    if not targets:
        return False
    me = self_qq(user_msg, character)
    return not (me and me in targets)


def is_reply_to_bot(user_msg: IMMessage, character: str = "") -> bool:
    """只有能确认引用对象是本账号时才算回复 Bot；默认不算。"""
    me = self_qq(user_msg, character)
    targets, _ = at_target_qqs(user_msg)
    has_reply = False
    for seg in raw_segments(user_msg):
        typ = _seg_type(seg)
        if typ != "reply" and type(seg).__name__ != "ReplyElement":
            continue
        has_reply = True
        data = _seg_data(seg)
        who = str(
            data.get("qq")
            or data.get("user_id")
            or data.get("sender_id")
            or getattr(seg, "user_id", "")
            or ""
        ).strip()
        if who:
            if me and who == me:
                return True
            continue
        if me and targets:
            return me in targets
    if not has_reply:
        for blob in raw_text_blobs(user_msg):
            if _CQ_REPLY_RE.search(blob):
                has_reply = True
                break
    if has_reply and me and me in targets:
        return True
    return False


def addressed_to_self(user_msg: IMMessage, character: str = "") -> bool:
    """本账号被 @ 或被确认引用。只 @ 别人时为 False。"""
    if mentioned_others(user_msg, character) and not mentioned_bot(user_msg, character):
        return False
    return mentioned_bot(user_msg, character) or is_reply_to_bot(user_msg, character)
