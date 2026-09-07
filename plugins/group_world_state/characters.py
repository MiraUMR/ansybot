from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from .persona_text import parse_peer_binding, peer_binding_summary

CHARACTERS_PATH = Path("data/characters.yaml")
PERSONA_ROOT = Path("data/persona")

_peer_bind_cache: Dict[str, Dict[str, str]] = {}


def load_characters() -> Dict[str, Any]:
    if not CHARACTERS_PATH.exists():
        return {"characters": {}, "peer": {}, "immersion": {}}
    data = yaml.safe_load(CHARACTERS_PATH.read_text(encoding="utf-8")) or {}
    data.setdefault("characters", {})
    data.setdefault("peer", {})
    data.setdefault("immersion", {})
    return data


def get_character(character_id: str) -> Dict[str, Any]:
    data = load_characters()
    chars = data.get("characters") or {}
    return dict(chars.get(character_id) or {})


def peer_config() -> Dict[str, Any]:
    data = load_characters()
    peer = dict(data.get("peer") or {})
    peer.setdefault("max_rounds", 3)
    peer.setdefault("cooldown_seconds", 180)
    peer.setdefault("chain_ttl_seconds", 600)
    return peer


def immersion_config() -> Dict[str, Any]:
    data = load_characters()
    cfg = dict(data.get("immersion") or {})
    cfg.setdefault("enabled", True)
    cfg.setdefault("extra_bot_qqs", [])
    cfg.setdefault("short_text_max_len", 4)
    cfg.setdefault("scene_buffer_max", 5)
    cfg.setdefault("narration_llm_min_len", 12)
    cfg.setdefault("narration_model", "")
    cfg.setdefault("discard_only_emoji", True)
    cfg.setdefault("env_reply_chance", 100)
    # 环境随机闲聊时，约 N% 允许 @/点名同伴续聊（仍受 peer.max_rounds 约束）
    cfg.setdefault("env_peer_ping_chance", 40)
    return cfg


def bot_qq_whitelist() -> Set[str]:
    """Bot 身份：characters.yaml 本号 + 人设绑定的同伴 QQ + extra_bot_qqs。"""
    data = load_characters()
    out: Set[str] = set()
    for meta in (data.get("characters") or {}).values():
        qq = str((meta or {}).get("qq") or "").strip()
        if qq:
            out.add(qq)
    for cid in (data.get("characters") or {}):
        bind = peer_binding(str(cid))
        for key in ("self_qq", "peer_qq"):
            qq = str(bind.get(key) or "").strip()
            if qq:
                out.add(qq)
    for raw in immersion_config().get("extra_bot_qqs") or []:
        qq = str(raw or "").strip()
        if qq:
            out.add(qq)
    return out


def is_registered_bot_qq(qq: str) -> bool:
    return str(qq or "").strip() in bot_qq_whitelist()


def character_by_im(im_name: str) -> Optional[str]:
    im_name = str(im_name or "").strip()
    if not im_name:
        return None
    if im_name == "qq_official_bot":
        return "anon"
    for cid, meta in (load_characters().get("characters") or {}).items():
        if str(meta.get("im_name") or "") == im_name:
            return cid
    return None


def character_by_qq(qq: str) -> Optional[str]:
    qq = str(qq or "").strip()
    if not qq:
        return None
    for cid, meta in (load_characters().get("characters") or {}).items():
        if str(meta.get("qq") or "").strip() == qq:
            return cid
    for cid in (load_characters().get("characters") or {}):
        bind = peer_binding(str(cid))
        if bind.get("self_qq") == qq:
            return str(cid)
        if bind.get("peer_qq") == qq:
            return bind.get("peer_id") or None
    return None


def invalidate_peer_binding(character_id: Optional[str] = None) -> None:
    if character_id:
        _peer_bind_cache.pop(str(character_id), None)
    else:
        _peer_bind_cache.clear()


def _read_persona_base_raw(character_id: str) -> str:
    path = PERSONA_ROOT / character_id / "modules" / f"{character_id}_base.md"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def peer_binding(character_id: str) -> Dict[str, str]:
    """权威来源：角色人设 base 的 ```peer 块；缺字段再回落 characters.yaml。"""
    cid = str(character_id or "").strip()
    if not cid:
        return parse_peer_binding("")
    cached = _peer_bind_cache.get(cid)
    if cached is not None:
        return dict(cached)

    bind = parse_peer_binding(_read_persona_base_raw(cid))
    self_meta = get_character(cid)
    other = None
    for other_cid in (load_characters().get("characters") or {}):
        if other_cid != cid:
            other = other_cid
            break
    other_meta = get_character(other) if other else {}

    if not bind.get("self_id"):
        bind["self_id"] = cid
    if not bind.get("self_display"):
        bind["self_display"] = str(self_meta.get("display") or cid)
    if not bind.get("self_qq"):
        bind["self_qq"] = str(self_meta.get("qq") or "").strip()
    if not bind.get("peer_id") and other:
        bind["peer_id"] = str(other)
    if not bind.get("peer_display"):
        bind["peer_display"] = str(other_meta.get("display") or bind.get("peer_id") or "")
    if not bind.get("peer_qq"):
        # 兼容旧 characters.yaml peer.by_character
        override = (peer_config().get("by_character") or {}).get(cid)
        if override:
            bind["peer_qq"] = str(override).strip()
        elif other:
            bind["peer_qq"] = str(other_meta.get("qq") or "").strip()
    if not bind.get("peer_call"):
        defaults = {
            "soyo": "小爱音",
            "anon": "soyorin",
        }
        bind["peer_call"] = defaults.get(cid, bind.get("peer_display") or "")
    if not bind.get("peer_absent"):
        defaults = {
            "soyo": "「某人」或「小爱音」",
            "anon": "soyorin",
        }
        bind["peer_absent"] = defaults.get(cid, bind.get("peer_call") or "")
    if not bind.get("peer_forbid"):
        defaults = {
            "soyo": "爱音 / 爱音酱 / Anon / 千早",
            "anon": "素世 / 素世世 / soyo",
        }
        bind["peer_forbid"] = defaults.get(cid, "")

    _peer_bind_cache[cid] = dict(bind)
    return dict(bind)


def peer_id_for(character_id: str) -> Optional[str]:
    pid = peer_binding(character_id).get("peer_id") or ""
    if pid:
        return pid
    chars = load_characters().get("characters") or {}
    if character_id not in chars:
        return None
    for cid in chars:
        if cid != character_id:
            return cid
    return None


def peer_qq(character_id: str) -> str:
    """本角色唯一同伴 QQ：优先人设【同伴绑定】，不认昵称。"""
    return str(peer_binding(character_id).get("peer_qq") or "").strip()


def peer_address(character_id: str) -> Dict[str, str]:
    bind = peer_binding(character_id)
    return {
        "call": bind.get("peer_call") or "",
        "absent": bind.get("peer_absent") or bind.get("peer_call") or "",
        "forbid": bind.get("peer_forbid") or "",
    }


def self_qq(character_id: str) -> str:
    qq = peer_binding(character_id).get("self_qq") or ""
    if qq:
        return str(qq).strip()
    return str(get_character(character_id).get("qq") or "").strip()


def is_peer_qq(character_id: str, qq: str) -> bool:
    """全局铁律：只有人设绑定的同伴 QQ 才算同伴；其余一律群友。"""
    peer = peer_qq(character_id)
    sender = str(qq or "").strip()
    return bool(peer and sender and sender == peer)


def classify_sender_qq(character_id: str, qq: str) -> str:
    """按 QQ 分类发送者：peer / self / member。"""
    sender = str(qq or "").strip()
    if not sender:
        return "member"
    if sender == self_qq(character_id):
        return "self"
    if is_peer_qq(character_id, sender):
        return "peer"
    return "member"


def peer_identity_lock(character_id: str) -> str:
    """写入提示：同伴只认配置 QQ（来源：人设绑定）。"""
    bind = peer_binding(character_id)
    display = bind.get("peer_display") or bind.get("peer_id") or "同伴"
    pqq = bind.get("peer_qq") or "（未配置）"
    call = bind.get("peer_call") or display
    return (
        f"【QQ身份铁律｜人设绑定】同伴只认 QQ {pqq}（{display}，当面称「{call}」）。"
        "每句话先看发送者 QQ："
        f"等于 {pqq} → 同伴互聊；"
        "其它任何 QQ（含同名昵称、未登记 Bot、群友）一律当群友。"
        "禁止用昵称/显示名判断同伴。"
        f"{peer_binding_summary(bind)}"
    )


def aliases(character_id: str) -> List[str]:
    return [str(x) for x in (get_character(character_id).get("aliases") or []) if x]
