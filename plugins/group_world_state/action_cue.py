"""F2F 括号动作稀疏化：轮次计数 + 冷却软提示；Phone 强制禁括号。"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Optional, Tuple

import yaml

ROOT = Path("data/world_state/_action_cue")
_lock = threading.RLock()

# ()（）【】；方括号 [图片] 类由调用方过滤
_BRACKET_RE = re.compile(r"[（(【\[]([^）)】\]]{1,40})[）)】\]]")


def _path(character: str, group_id: str) -> Path:
    safe_c = re.sub(r"[^a-zA-Z0-9_-]+", "_", (character or "anon").strip())[:40]
    safe_g = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(group_id or "dm"))[:80]
    return ROOT / f"{safe_c}__{safe_g or 'dm'}.yaml"


def _load(character: str, group_id: str) -> dict:
    path = _path(character, group_id)
    with _lock:
        if not path.exists():
            return {
                "turn": 0,
                "last_action_turn": -999,
                "last_inner_turn": -999,
                "last_address_turn": -999,
            }
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {
                "turn": 0,
                "last_action_turn": -999,
                "last_inner_turn": -999,
                "last_address_turn": -999,
            }
    return {
        "turn": int(data.get("turn") or 0),
        "last_action_turn": int(data.get("last_action_turn") or -999),
        "last_inner_turn": int(data.get("last_inner_turn") or -999),
        "last_address_turn": int(data.get("last_address_turn") or -999),
    }


def _save(character: str, group_id: str, doc: dict) -> None:
    path = _path(character, group_id)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {
                    "character": character,
                    "group_id": str(group_id),
                    "turn": int(doc.get("turn") or 0),
                    "last_action_turn": int(doc.get("last_action_turn") or -999),
                    "last_inner_turn": int(doc.get("last_inner_turn") or -999),
                    "last_address_turn": int(doc.get("last_address_turn") or -999),
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )


def cooldown_window(character: str) -> int:
    """动作括号：Soyo 每5轮；Anon 每3轮。"""
    return 3 if (character or "").strip() == "anon" else 5


def inner_cooldown_window(character: str) -> int:
    """内心括号：爱音更碎可稍密，素世更淡更稀。"""
    return 4 if (character or "").strip() == "anon" else 6


def bump_turn(character: str, group_id: str) -> int:
    doc = _load(character, group_id)
    doc["turn"] = int(doc.get("turn") or 0) + 1
    _save(character, group_id, doc)
    return int(doc["turn"])


def mark_action_used(character: str, group_id: str) -> None:
    doc = _load(character, group_id)
    doc["last_action_turn"] = int(doc.get("turn") or 0)
    _save(character, group_id, doc)


def mark_inner_used(character: str, group_id: str) -> None:
    doc = _load(character, group_id)
    doc["last_inner_turn"] = int(doc.get("turn") or 0)
    _save(character, group_id, doc)


def reply_has_inner_aside(text: str) -> bool:
    for m in _BRACKET_RE.finditer(text or ""):
        inner = (m.group(1) or "").strip()
        raw = m.group(0)
        if _is_inner_thought(raw, inner):
            return True
    return False


def inner_allowed(character: str, group_id: str) -> bool:
    doc = _load(character, group_id)
    turn = int(doc.get("turn") or 0)
    last = int(doc.get("last_inner_turn") or -999)
    return (turn - last) >= inner_cooldown_window(character)


def address_cooldown_window(character: str) -> int:
    """互聊点名：素世更淡，隔一轮再叫；爱音可稍密。"""
    return 2 if (character or "").strip() == "anon" else 2


def mark_address_used(character: str, group_id: str) -> None:
    doc = _load(character, group_id)
    doc["last_address_turn"] = int(doc.get("turn") or 0)
    _save(character, group_id, doc)


def reply_has_peer_call(character: str, text: str) -> bool:
    raw = text or ""
    if (character or "").strip() == "anon":
        return bool(re.search(r"(?i)soyorin", raw))
    return "小爱音" in raw


def address_allowed(character: str, group_id: str) -> bool:
    doc = _load(character, group_id)
    turn = int(doc.get("turn") or 0)
    last = int(doc.get("last_address_turn") or -999)
    return (turn - last) >= address_cooldown_window(character)


def reply_has_action_bracket(text: str) -> bool:
    for m in _BRACKET_RE.finditer(text or ""):
        inner = (m.group(1) or "").strip()
        raw = m.group(0)
        if raw.startswith("[") and (
            "图片" in inner or "语音" in inner or "系统" in inner or "分享" in inner or "加载" in inner
        ):
            continue
        if _is_inner_thought(raw, inner):
            continue
        return True
    return False


def _is_inner_thought(raw: str, inner: str) -> bool:
    """识别内心旁白（非动作）。"""
    if not raw.startswith(("（", "(")):
        return False
    compact = re.sub(r"\s+", "", inner or "")
    if not (4 <= len(compact) <= 40):
        return False
    if re.search(r"看着|转身|微笑|伸手|低头|点头|握住|走过来|别过脸", inner):
        return False
    return bool(
        re.search(
            r"不想|在意|其实|心里|才不|才要|不能让|别让|不让|某人|别把|还是别|偷偷|看出来|误会|顺手|识货|不理我",
            inner,
        )
    )


def long_bracket_hits(text: str) -> list:
    """F2F：动作括号超过6字违规；内心括号允许，由冷却层控制。"""
    hits = []
    for m in _BRACKET_RE.finditer(text or ""):
        inner = (m.group(1) or "").strip()
        raw = m.group(0)
        if raw.startswith("[") and (
            "图片" in inner or "语音" in inner or "系统" in inner or "分享" in inner or "加载" in inner
        ):
            continue
        if _is_inner_thought(raw, inner):
            continue
        if len(re.sub(r"\s+", "", inner)) > 6:
            hits.append(f"括号过长:{inner[:10]}")
    return hits


def _is_im_placeholder_bracket(raw: str, inner: str) -> bool:
    return raw.startswith("[") and (
        "图片" in inner
        or "语音" in inner
        or "系统" in inner
        or "分享" in inner
        or "加载" in inner
        or "正在" in inner
    )


def drop_long_brackets(text: str) -> str:
    """本地去掉过长动作括号；内心旁白保留。"""

    def repl(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        raw = m.group(0)
        if _is_im_placeholder_bracket(raw, inner):
            return raw
        if _is_inner_thought(raw, inner):
            return raw
        if len(re.sub(r"\s+", "", inner)) > 6:
            return ""
        return raw

    out = _BRACKET_RE.sub(repl, text or "")
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", out)).strip()


def drop_inner_asides(text: str) -> str:
    """冷却中：去掉全部内心括号。"""

    def repl(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        raw = m.group(0)
        if _is_im_placeholder_bracket(raw, inner):
            return raw
        if _is_inner_thought(raw, inner):
            return ""
        return raw

    out = _BRACKET_RE.sub(repl, text or "")
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", out)).strip()


def keep_one_inner_aside(text: str) -> str:
    """每轮最多一句内心括号。"""
    seen = False

    def repl(m: re.Match) -> str:
        nonlocal seen
        inner = (m.group(1) or "").strip()
        raw = m.group(0)
        if not _is_inner_thought(raw, inner):
            return raw
        if seen:
            return ""
        seen = True
        return raw

    out = _BRACKET_RE.sub(repl, text or "")
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", out)).strip()


def strip_stage_brackets(text: str) -> str:
    """Phone：去掉 ()（）【】 动作括号；保留 [图片] 类占位。"""
    out = re.sub(r"[（(【]([^）)】]{0,40})[）)】]", "", text or "")
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", out)).strip()


def any_stage_bracket_hits(text: str) -> list:
    """Phone：任何圆括号/【】动作都违规；保留 [图片] 类占位。"""
    hits = []
    for m in re.finditer(r"[（(【]([^）)】]{0,40})[）)】]", text or ""):
        hits.append("Phone禁括号动作")
        break
    return hits


def assemble_action_note(
    character: str,
    group_id: str,
    interaction_mode: str,
    *,
    bump: bool = True,
) -> str:
    """注入到 critical / persona 尾部的软约束。"""
    imode = (interaction_mode or "face").strip().lower()
    if imode == "phone":
        if bump:
            bump_turn(character, group_id)
        return (
            "[SYSTEM OVERRIDE: BRACKET_ACTIONS_DISABLED]\n"
            "PHONE MODE：严禁 ()【】（）动作/神态。用 emoji 或纯文字暗示。\n"
        )
    turn = bump_turn(character, group_id) if bump else _load(character, group_id)["turn"]
    doc = _load(character, group_id)
    last = int(doc.get("last_action_turn") or -999)
    window = cooldown_window(character)
    gap = turn - last
    last_inner = int(doc.get("last_inner_turn") or -999)
    iwin = inner_cooldown_window(character)
    igap = turn - last_inner
    inner_note = f"Inner （）: {'OK' if igap >= iwin else f'cooling {igap}/{iwin}'}."
    if gap < window:
        return f"[NOTE: Action brackets cooling — {gap}/{window}. Prefer pure text. {inner_note}]\n"
    return (
        f"[NOTE: F2F sparse actions OK — ≤1 gesture / {window} turns, ≤6 chars. "
        f"{inner_note}]\n"
    )


def note_after_reply(character: str, group_id: str, reply: str, interaction_mode: str) -> None:
    if (interaction_mode or "").strip().lower() == "phone":
        return
    if reply_has_action_bracket(reply):
        mark_action_used(character, group_id)
    if reply_has_inner_aside(reply):
        mark_inner_used(character, group_id)
    if reply_has_peer_call(character, reply):
        mark_address_used(character, group_id)
