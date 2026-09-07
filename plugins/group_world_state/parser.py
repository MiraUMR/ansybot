from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

STATE_RE = re.compile(r"<<\s*STATE\s*(.*?)\s*>>", re.DOTALL | re.IGNORECASE)
LINE_RE = re.compile(
    r"^\s*(SET|DEL|DELETE|设定|删除)\s+([a-zA-Z0-9_\u4e00-\u9fff]+)(?:\s+(.+))?\s*$",
    re.IGNORECASE,
)


@dataclass
class StateOp:
    op: str  # set | del
    key: str
    text: str = ""


def parse_ops(body: str) -> List[StateOp]:
    text = (body or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|text)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            ops: List[StateOp] = []
            sets = data.get("set") or data.get("SET") or {}
            if isinstance(sets, dict):
                for key, value in sets.items():
                    ops.append(StateOp("set", str(key), str(value)))
            deletes = data.get("delete") or data.get("del") or data.get("DEL") or []
            if isinstance(deletes, list):
                for key in deletes:
                    ops.append(StateOp("del", str(key)))
            return ops
    ops = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        action, key, value = match.group(1), match.group(2), match.group(3) or ""
        action_l = action.lower()
        if action_l in ("del", "delete", "删除"):
            ops.append(StateOp("del", key))
        else:
            if value.strip():
                ops.append(StateOp("set", key, value.strip()))
    return ops


def strip_state(text: str) -> Tuple[str, List[StateOp]]:
    if not text or "<<STATE" not in text.upper().replace(" ", ""):
        return text or "", []
    ops: List[StateOp] = []

    def repl(match: re.Match) -> str:
        ops.extend(parse_ops(match.group(1)))
        return ""

    cleaned = STATE_RE.sub(repl, text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, ops


MEMORY_POINT_RE = re.compile(
    r"<memory_point>\s*(.*?)\s*</memory_point>",
    re.DOTALL | re.IGNORECASE,
)


def strip_memory_points(text: str) -> Tuple[str, List[str]]:
    points: List[str] = []

    def repl(match: re.Match) -> str:
        item = (match.group(1) or "").strip()
        if item:
            points.append(item)
        return ""

    cleaned = MEMORY_POINT_RE.sub(repl, text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, points


def extract_command(content: str) -> Optional[Tuple[str, List[str]]]:
    """Parse /长期记忆 or /world commands. Returns (verb, args) or None."""
    text = (content or "").strip()
    text = re.sub(r"^@\S+\s+", "", text).strip()
    for prefix in ("/长期记忆", "/worldstate", "/world"):
        if text == prefix or text.startswith(prefix + " "):
            rest = text[len(prefix):].strip()
            break
    else:
        return None
    if not rest or rest in ("查看", "list", "show"):
        return "show", []
    parts = rest.split(None, 2)
    verb = parts[0]
    if verb in ("设定", "set", "添加", "改"):
        if len(parts) < 3:
            return "usage", []
        return "set", [parts[1], parts[2]]
    if verb in ("删除", "del", "delete", "rm"):
        if len(parts) < 2:
            return "usage", []
        return "del", [parts[1]]
    if verb in ("清空", "clear", "reset"):
        return "clear", []
    if verb in ("帮助", "help"):
        return "help", []
    return "usage", []
