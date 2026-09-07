"""交互模式（face / phone）：按群+角色持久化，命令切换。"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

ROOT = Path("data/world_state/_interaction_mode")
_lock = threading.RLock()

# 开启
_PHONE_ON = re.compile(
    r"(?i)(?:^|[\s　])(?:/phone(?:\s+on)?|/mode\s+phone|"
    r"\[手机模式\]|【手机模式】|\[phone\s*mode\])(?:\s|$|[，,。.!！？?])"
)
# 关闭
_PHONE_OFF = re.compile(
    r"(?i)(?:^|[\s　])(?:/phone\s+off|/mode\s+(?:face|f2f|normal|default)|"
    r"\[关闭手机模式\]|【关闭手机模式】|\[face\s*mode\])(?:\s|$|[，,。.!！？?])"
)
# 从正文剥离命令，避免再当聊天内容
_STRIP = re.compile(
    r"(?i)(?:/phone(?:\s+(?:on|off))?|/mode\s+(?:phone|face|f2f|normal|default)|"
    r"\[手机模式\]|【手机模式】|\[关闭手机模式\]|【关闭手机模式】|"
    r"\[phone\s*mode\]|\[face\s*mode\])"
)


def _path(character: str, group_id: str) -> Path:
    safe_c = re.sub(r"[^a-zA-Z0-9_-]+", "_", (character or "anon").strip())[:40]
    safe_g = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(group_id or "dm"))[:80]
    return ROOT / f"{safe_c}__{safe_g or 'dm'}.yaml"


def get_interaction_mode(character: str, group_id: str) -> str:
    path = _path(character, group_id)
    with _lock:
        if not path.exists():
            return "face"
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return "face"
    mode = str(data.get("mode") or "face").strip().lower()
    return "phone" if mode == "phone" else "face"


def set_interaction_mode(character: str, group_id: str, mode: str) -> str:
    mode = "phone" if (mode or "").strip().lower() == "phone" else "face"
    path = _path(character, group_id)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {"character": character, "group_id": str(group_id), "mode": mode},
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    return mode


def parse_mode_command(text: str) -> Optional[str]:
    """返回 'phone' / 'face' / None（无切换命令）。关闭优先。"""
    raw = text or ""
    if _PHONE_OFF.search(raw):
        return "face"
    if _PHONE_ON.search(raw):
        return "phone"
    return None


def strip_mode_command(text: str) -> str:
    t = _STRIP.sub(" ", text or "")
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def resolve_interaction_mode(
    character: str, group_id: str, content: str
) -> Tuple[str, Optional[str], str]:
    """返回 (mode, toggled_to|None, content_after_strip)。"""
    toggled = parse_mode_command(content)
    cleaned = strip_mode_command(content) if toggled else (content or "")
    if toggled:
        mode = set_interaction_mode(character, group_id, toggled)
    else:
        # 剧情文案里写了 [手机模式] 且本轮未关 → 本轮临时视为 phone（不强制持久也可持久）
        mode = get_interaction_mode(character, group_id)
        if mode != "phone" and re.search(r"\[手机模式\]|【手机模式】", content or ""):
            mode = "phone"
    return mode, toggled, cleaned


def phone_toggle_notice(character: str, toggled_to: str) -> str:
    call = "小爱音" if (character or "").strip() != "anon" else "soyorin"
    if toggled_to == "phone":
        return (
            "[SYSTEM: interaction_mode=phone]\n"
            "对方切换到手机/即时通讯语境。用角色手机口吻短回确认（1-2条，可用<break>），"
            f"不要解释「模式」二字，不要元对话。称呼仍守 Base（{call}）。\n"
        )
    return (
        "[SYSTEM: interaction_mode=face]\n"
        "对方切回当面/普通群聊语境。用角色正常当面口吻短回即可，不要解释模式。\n"
    )


def attach_interaction_mode(
    bundle: Dict[str, Any],
    *,
    character: str,
    group_id: str,
    content: str,
) -> Dict[str, Any]:
    mode, toggled, _cleaned = resolve_interaction_mode(character, group_id, content)
    bundle["interaction_mode"] = mode
    if toggled:
        notice = phone_toggle_notice(character, toggled)
        prompt = str(bundle.get("user_prompt_text") or "")
        bundle["user_prompt_text"] = (notice + prompt).strip()
        # 若剥离后几乎无内容，仍让角色短确认
        rest = strip_mode_command(content)
        if not rest or rest in ("@", "＠"):
            bundle["user_prompt_text"] = (
                notice
                + "触发内容：（对方只切换了聊天界面，没有别的话）\n"
                "只回一条很短的手机/当面确认，禁止讲解。\n"
            ).strip()
            if (bundle.get("message_mode") or "") == "discard":
                bundle["message_mode"] = "direct"
                bundle["skip_chat_memory"] = "false"
    return bundle
