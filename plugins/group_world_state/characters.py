from __future__ import annotations

import re
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
    # Official bot is the story host, not anon RP.
    if im_name == "qq_official_bot":
        return "host"
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


def _routing_bind(character_id: str) -> Dict[str, str]:
    """config_v2.routing is the code-side peer source. Not injected into prompts."""
    out = {k: "" for k in (
        "self_id", "self_display", "self_qq", "peer_id", "peer_display",
        "peer_qq", "peer_call", "peer_absent", "peer_forbid",
    )}
    try:
        from .persona_config import load_config

        doc = load_config(character_id)
    except Exception:
        return out
    routing = doc.get("routing") or {}
    meta = doc.get("meta") or {}
    ident = doc.get("identity") or {}
    out["self_id"] = str(meta.get("id") or character_id).strip()
    out["self_display"] = str(ident.get("name_full") or meta.get("display_name") or "").strip()
    out["self_qq"] = str(meta.get("qq") or "").strip()
    out["peer_id"] = str(routing.get("peer_id") or "").strip()
    out["peer_qq"] = str(routing.get("peer_qq") or "").strip()
    social = doc.get("social_context") or {}
    for rel in social.get("peer_relations") or []:
        if not isinstance(rel, dict):
            continue
        if str(rel.get("target_id") or "").strip().lower() != out["peer_id"]:
            continue
        addr = str(rel.get("address_rule") or "").strip()
        quoted = re.findall(r"「([^」]{1,12})」", addr)
        if quoted:
            out["peer_call"] = quoted[0]
        elif addr and len(addr) <= 12:
            out["peer_call"] = addr
        names = rel.get("forbidden_names") or []
        if isinstance(names, str):
            names = [names]
        if names:
            out["peer_forbid"] = " / ".join(str(x) for x in names if x)
        break
    return out


def peer_binding(character_id: str) -> Dict[str, str]:
    """权威来源：config_v2.routing；缺字段再回落 base ```peer 与 characters.yaml。"""
    cid = str(character_id or "").strip()
    if not cid:
        return parse_peer_binding("")
    cached = _peer_bind_cache.get(cid)
    if cached is not None:
        return dict(cached)

    bind = _routing_bind(cid)
    legacy = parse_peer_binding(_read_persona_base_raw(cid))
    for key, val in legacy.items():
        if val and not bind.get(key):
            bind[key] = val
    self_meta = get_character(cid)
    # peer_id 已由 routing 定死：other 直接取它，不要顺手取到 host。
    peer_id = str(bind.get("peer_id") or "").strip()
    other = peer_id or None
    if not other:
        for other_cid in (load_characters().get("characters") or {}):
            if other_cid != cid and other_cid != "host":
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
        if cid != character_id and cid != "host":
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
    """代码侧铁律：只有人设绑定的同伴账号才算同伴；其余当眼前的人。"""
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
    """写入提示：对象已由系统判定。禁止把账号/编号教给模型。"""
    bind = peer_binding(character_id)
    display = bind.get("peer_display") or bind.get("peer_id") or "同伴"
    call = bind.get("peer_call") or display
    return (
        f"本轮对象已由系统判定。同伴当面称「{call}」（{display}）。"
        "其他人即使自称同名也当眼前的人。"
        "禁止核验、猜测或念出任何账号、编号。"
        f"{peer_binding_summary(bind)}"
    )


def turn_object_line(character_id: str, *, is_peer: bool) -> str:
    """本轮对象一句，不含账号。"""
    bind = peer_binding(character_id)
    call = bind.get("peer_call") or bind.get("peer_display") or "同伴"
    if is_peer:
        return f"本轮对象是同伴，当面称「{call}」，不要用「你」。不要念任何账号或编号。"
    return (
        f"本轮对象是眼前的人，不是同伴。即使自称同名也不要把对方当成「{call}」。"
        "不要念任何账号或编号。"
    )


def aliases(character_id: str) -> List[str]:
    return [str(x) for x in (get_character(character_id).get("aliases") or []) if x]
