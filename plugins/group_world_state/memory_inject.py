"""群聊近期记忆注入：去重、截短、丢掉空回声。"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

MAX_MEMORY_TURNS = 6
MAX_USER_CHARS = 80
MAX_REPLY_CHARS = 120
MAX_ENTRY_CHARS = 160

_TIME_PREFIX_RE = re.compile(r"^(刚刚|\d+分钟前|\d+小时前|\d+天前)，")
_EMPTY_SAY_RE = re.compile(r"^[^:\n]{1,32}\s*说:\s*(你回答:\s*)?$")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("<break>", " ")).strip()


def strip_time_prefix(content: str) -> Tuple[str, str]:
    raw = (content or "").strip()
    match = _TIME_PREFIX_RE.match(raw)
    if not match:
        return "", raw
    return match.group(0), raw[match.end() :].strip()


def memory_payload(content: str) -> str:
    _, body = strip_time_prefix(content)
    if "你回答:" in body:
        return _flat(body.split("你回答:", 1)[1])
    if "说:" in body:
        return _flat(body.split("说:", 1)[-1])
    return _flat(body)


def user_blob(content: str) -> str:
    _, body = strip_time_prefix(content)
    head = body.split("你回答:", 1)[0]
    if "说:" in head:
        head = head.split("说:", 1)[-1]
    return re.sub(r"\s+", "", head)


def payload_key(content: str) -> str:
    return re.sub(r"\s+", "", memory_payload(content))[:80]


def is_empty_memory(content: str) -> bool:
    raw = (content or "").strip()
    if not raw:
        return True
    _, body = strip_time_prefix(raw)
    if not body or _EMPTY_SAY_RE.match(body):
        return True
    return not memory_payload(raw)


def clip_memory_text(text: str, limit: int = MAX_ENTRY_CHARS) -> str:
    t = _flat(text)
    if len(t) <= limit:
        return t
    parts = re.split(r"(?<=[。！？!?])", t)
    acc: List[str] = []
    n = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        room = limit - n
        if room <= 0:
            break
        if len(part) <= room:
            acc.append(part)
            n += len(part)
            continue
        if not acc or room >= 24:
            acc.append(part[:room].rstrip("…，, ") + "…")
        elif not str(acc[-1]).endswith("…"):
            acc[-1] = str(acc[-1]).rstrip("…") + "…"
        n = limit
        break
    out = "".join(acc) if acc else t[:limit] + "…"
    if len(t) > len(out.rstrip("…")) and not out.endswith("…"):
        out = out.rstrip() + "…"
    return out


def clip_memory_entry_text(content: str) -> str:
    prefix, body = strip_time_prefix(content)
    if not body:
        return (content or "").strip()
    if "你回答:" in body:
        user, ans = body.split("你回答:", 1)
        user = clip_memory_text(user, MAX_USER_CHARS)
        ans = clip_memory_text(ans, MAX_REPLY_CHARS)
        clipped = f"{user}\n你回答: {ans}".strip()
    else:
        clipped = clip_memory_text(body, MAX_ENTRY_CHARS)
    return f"{prefix}{clipped}"


def _entry_content(entry: Any) -> str:
    if isinstance(entry, str):
        return entry
    return str(getattr(entry, "content", "") or "")


def compact_memory_entries(
    entries: Optional[Sequence[Any]],
    *,
    max_turns: int = MAX_MEMORY_TURNS,
) -> List[Any]:
    """按时间顺序保留最近几条；同一句话只留一份，优先带「你回答」的完整轮。"""
    items = [e for e in (entries or []) if not is_empty_memory(_entry_content(e))]
    reply_payloads: set[str] = set()
    reply_users: set[str] = set()
    chosen: dict[int, Any] = {}

    for idx, entry in enumerate(items):
        content = _entry_content(entry)
        if "你回答:" not in content:
            continue
        key = payload_key(content)
        user = user_blob(content)
        prev_idx = next((i for i, e in chosen.items() if payload_key(_entry_content(e)) == key), None)
        if prev_idx is not None:
            del chosen[prev_idx]
        chosen[idx] = entry
        if key:
            reply_payloads.add(key)
        if user:
            reply_users.add(user)

    for idx, entry in enumerate(items):
        content = _entry_content(entry)
        if "你回答:" in content:
            continue
        key = payload_key(content)
        user = user_blob(content)
        if key and key in reply_payloads:
            continue
        if user and user in reply_users:
            continue
        if any(payload_key(_entry_content(e)) == key for e in chosen.values()):
            continue
        chosen[idx] = entry

    ordered = [chosen[i] for i in sorted(chosen)]
    return ordered[-max(1, int(max_turns)) :]


def compact_memory_content(memory_content: Any, *, max_turns: int = MAX_MEMORY_TURNS) -> Any:
    if memory_content is None:
        return []
    if not isinstance(memory_content, list):
        return memory_content
    if not memory_content:
        return []
    if all(isinstance(item, str) for item in memory_content):
        picked = compact_memory_entries(memory_content, max_turns=max_turns)
        return [clip_memory_entry_text(item) for item in picked]
    return memory_content
