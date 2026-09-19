"""Compile config_v2.yaml into the injected persona XML.

Rollback: set USE_COMPILER = False. PersonaLayers then falls back to
load_persona_module() for base / trigger / companion / scene / story / mode_phone.
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .persona_config import load_config
from .voice_pack import is_daily_register

# Flip to False to restore the old markdown injection path.
USE_COMPILER = True

REPLACED_MODULES = ("base", "trigger", "companion", "scene", "story", "mode_phone")

_FAMILY_HINTS = (
    "妈",
    "母亲",
    "爸爸",
    "父亲",
    "家人",
    "家里",
    "父母",
    "家长",
    "美智子",
)
_TASTE_HINTS = (
    "吃",
    "喝",
    "饿",
    "饭",
    "菜",
    "汤",
    "茶",
    "甜",
    "口味",
    "三明治",
    "通心粉",
    "三文鱼",
    "红茶",
    "菜单",
)
_AROMA_HINTS = (
    "香薰",
    "熏香",
    "精油",
    "扩香",
    "香氛",
    "气味",
)
_TASTE_FACT_MARK = (
    "红茶",
    "蔬菜汤",
    "三明治",
    "三文鱼",
    "通心粉",
    "内脏",
    "梅干",
    "口味锚点",
)
_AROMA_FACT_MARK = ("香薰",)

_BAND_HINTS = (
    "乐队",
    "MyGO",
    "mygo",
    "立希",
    "灯",
    "乐奈",
    "吉他",
    "贝斯",
    "排练",
    "演出",
    "成员",
)

_TOKEN_BUDGET = {"chat": 2200, "story": 1800, "phone": 1200}


def _xml(text: Any) -> str:
    raw = str(text or "")
    escaped = (
        raw.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    # Keep output control tags literal so the model can emit them.
    for tag in ("break", "memory_point", "/memory_point"):
        escaped = escaped.replace(f"&lt;{tag}&gt;", f"<{tag}>")
    return escaped


def _lines(items: Iterable[Any]) -> List[str]:
    out: List[str] = []
    for item in items or []:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def _estimate(text: str) -> int:
    try:
        from .token_meter import estimate_tokens

        return estimate_tokens(text)
    except Exception:
        raw = text or ""
        n_cjk = len(re.findall(r"[\u4e00-\u9fff]", raw))
        return max(1, int(round(n_cjk * 0.85 + (len(raw) - n_cjk) / 4.0))) if raw else 0


def _axioms(doc: Dict[str, Any]) -> List[str]:
    rows = _lines(doc.get("core_axioms") or [])
    if rows:
        return rows
    ident = doc.get("identity") or {}
    name = str(ident.get("name_full") or (doc.get("meta") or {}).get("display_name") or "角色")
    return [f"你是{name}。非AI、非助手、非扮演者。被质疑身份时以角色逻辑回应，不承认扮演。"]


def _peer_id(doc: Dict[str, Any]) -> str:
    routing = doc.get("routing") or {}
    pid = str(routing.get("peer_id") or "").strip().lower()
    if pid:
        return pid
    return ""


def _relations(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    social = doc.get("social_context") or {}
    rows = []
    for rel in social.get("peer_relations") or []:
        if isinstance(rel, dict):
            rows.append(rel)
    return rows


def _peer_rel(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    want = _peer_id(doc)
    rows = _relations(doc)
    if want:
        for rel in rows:
            if str(rel.get("target_id") or "").strip().lower() == want:
                return rel
    return rows[0] if rows else None


def _band_rels(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    peer = _peer_id(doc)
    out = []
    for rel in _relations(doc):
        tid = str(rel.get("target_id") or "").strip().lower()
        if peer and tid == peer:
            continue
        out.append(rel)
    return out


def _traits(doc: Dict[str, Any], *, include_medium: bool = False) -> List[Dict[str, Any]]:
    psych = doc.get("psychology") or {}
    wanted = {"Critical", "High"}
    if include_medium:
        wanted.add("Medium")
    out = []
    for item in psych.get("core_traits") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("priority") or "") not in wanted:
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        desc = str(item.get("description") or "").strip()
        if len(desc) > 72:
            desc = desc[:72].rstrip("，,。；; ") + "…"
        out.append({"label": label, "description": desc})
        if len(out) >= 4:
            break
    return out


def _speech_lines(doc: Dict[str, Any], mode: str) -> List[str]:
    rules = doc.get("behavioral_rules") or {}
    speech = dict(rules.get("speech_style") or {})
    lines: List[str] = []
    lang = str(speech.get("language") or "").strip()
    slen = str(speech.get("sentence_length") or "").strip()
    if lang or slen:
        lines.append(f"language={lang} sentence_length={slen}".strip())
    opening = str(speech.get("opening_constraints") or "").strip()
    if opening and mode != "phone":
        lines.append(opening)
    forbids = [str(x) for x in (speech.get("forbidden_patterns") or []) if x]
    if mode == "phone":
        forbids = [x for x in forbids if "告白" not in x and "CRYCHIC" not in x]
    # Slash-separated catchphrase dumps get copied verbatim; keep structural bans only.
    forbids = [x for x in forbids if not _looks_like_catchphrase_dump(x)]
    if forbids:
        lines.append("forbidden: " + "；".join(forbids))
    punct = speech.get("punctuation_usage") or {}
    if isinstance(punct, dict) and punct and mode != "phone":
        bits = [f"{k}={v}" for k, v in punct.items() if v is not None]
        if bits:
            lines.append("punctuation: " + "；".join(bits))
    if mode != "phone":
        # 风格与正例由 voice_pack 每轮给，这里只留串腔禁令和频率。
        thought = rules.get("inner_thought") or {}
        if isinstance(thought, dict) and thought:
            freq = str(thought.get("frequency") or "").strip()
            bits = ["用本人节奏，一拍就完，不要学同伴"]
            if freq:
                bits.append(freq)
            lines.append("内心括号：" + "；".join(bits))
    return lines


def _memory_lines(
    doc: Dict[str, Any],
    *,
    facts: int,
    triggers: int,
    flags: Optional[Dict[str, bool]] = None,
) -> List[str]:
    mem = doc.get("memory_anchors") or {}
    flags = flags or {}
    kept: List[str] = []
    for row in _lines(mem.get("long_term_facts") or []):
        is_taste = any(m in row for m in _TASTE_FACT_MARK)
        is_aroma = any(m in row for m in _AROMA_FACT_MARK)
        if is_taste and not flags.get("taste"):
            continue
        if is_aroma and not flags.get("aroma"):
            continue
        kept.append(row)
        if len(kept) >= facts:
            break
    kept.extend(_lines(mem.get("emotional_triggers") or [])[:triggers])
    return kept


def build_outsider_block(doc: Dict[str, Any]) -> str:
    """非同伴轮次：对外人得体社交。不覆盖同伴互聊。"""
    social = doc.get("social_context") or {}
    lines = _as_list(social.get("outsider_manner"))
    if not lines:
        image = str(social.get("public_image") or "").strip()
        if image:
            lines = [image]
    if not lines:
        return ""
    aside = "内心用本人节奏，一拍就完，不要学同伴。每轮最多一句。"
    body = "\n".join(f"- {_xml(row)}" for row in lines[:4])
    return (
        "<outsider>\n"
        + body
        + f"\n- {_xml(aside)}同伴听不见你的内心括号。手机不要括号。\n"
        + "</outsider>"
    )


def _family_block(doc: Dict[str, Any]) -> str:
    social = doc.get("social_context") or {}
    fam = social.get("family_status") or {}
    if not isinstance(fam, dict) or not fam:
        return ""
    lines = []
    for key in ("topic_handling", "interaction_mode", "parents_relationship"):
        val = str(fam.get(key) or "").strip()
        if val:
            lines.append(f"- {_xml(val)}")
    if not lines:
        return ""
    return "<family>\n" + "\n".join(lines) + "\n</family>"


def _band_block(doc: Dict[str, Any]) -> str:
    rows = _band_rels(doc)
    if not rows:
        return ""
    lines = []
    for rel in rows:
        tid = str(rel.get("target_id") or "").strip()
        kind = str(rel.get("relationship_type") or "").strip()
        dyn = str(rel.get("dynamic_description") or "").strip()
        addr = str(rel.get("address_rule") or "").strip()
        bit = f"- {tid}: {kind}"
        if addr:
            bit += f"。称呼：{addr}"
        if dyn:
            bit += f"。{dyn}"
        lines.append(_xml(bit))
    return "<band>\n" + "\n".join(lines) + "\n</band>"


def _as_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    return _lines(value or [])


def _example_lines(items: Any, *, mark: str, limit: int, shuffle: bool = False) -> List[str]:
    out: List[str] = []
    rows = list(items or [])
    if shuffle and len(rows) > limit:
        rows = random.sample(rows, limit)
    else:
        rows = rows[:limit]
    for item in rows:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if not text:
                continue
            suffix = f" [{reason}]" if reason else ""
            out.append(f"  {mark} {_xml(text)}{_xml(suffix) if suffix else ''}")
        else:
            text = str(item or "").strip()
            if text:
                out.append(f"  {mark} {_xml(text)}")
    return out


def _routing_peer_qq(doc: Dict[str, Any]) -> str:
    routing = doc.get("routing") or {}
    act = ((doc.get("companion_mode") or {}).get("activation") or {})
    return str(routing.get("peer_qq") or act.get("peer_qq") or "").strip()


def build_companion_block(doc: Dict[str, Any]) -> str:
    cm = doc.get("companion_mode") or {}
    if not isinstance(cm, dict) or not cm:
        return ""
    pc = cm.get("peer_chat") or {}
    if not isinstance(pc, dict):
        pc = {}
    attitude = pc.get("attitude") or {}
    if not isinstance(attitude, dict):
        attitude = {"default": str(attitude)}
    act = cm.get("activation") or {}
    peer_id = str(act.get("peer_id") or _peer_id(doc) or "peer")
    lines = [f'<companion_mode peer="{_xml(peer_id)}">']
    coexist = _as_list(cm.get("group_coexist"))
    if coexist:
        lines.append("<group>")
        lines.append("- " + _xml("；".join(coexist[:3])))
        lines.append("</group>")
    fmt = _as_list(pc.get("format"))[:3]
    if fmt:
        lines.append("<format>")
        lines.extend(f"- {_xml(row)}" for row in fmt)
        lines.append("</format>")
    addr = _as_list(pc.get("address"))[:2]
    if addr:
        lines.append("<address>")
        lines.extend(f"- {_xml(row)}" for row in addr)
        lines.append("</address>")
    if attitude:
        lines.append("<attitude>")
        for key, val in attitude.items():
            text = str(val or "").strip()
            if text:
                lines.append(f"- {_xml(key)}: {_xml(text)}")
        lines.append("</attitude>")
    limits = _as_list(pc.get("hard_limits"))
    if limits:
        lines.append("<hard_limits>")
        lines.extend(f"- {_xml(row)}" for row in limits)
        lines.append("</hard_limits>")
    close = _as_list(cm.get("close_rules"))
    if close:
        lines.append("<close>")
        lines.extend(f"- {_xml(row)}" for row in close)
        lines.append("</close>")
    resonate = _as_list(cm.get("resonate"))[:2]
    if resonate:
        lines.append("<resonate>")
        lines.extend(f"- {_xml(row)}" for row in resonate)
        lines.append("</resonate>")
    trig_lines = []
    for item in cm.get("behavior_triggers") or []:
        if not isinstance(item, dict):
            continue
        trig = str(item.get("trigger") or "").strip()
        action = str(item.get("action") or item.get("note") or "").strip()
        if trig or action:
            trig_lines.append(f"- {_xml(trig)} → {_xml(action)}")
    if trig_lines:
        lines.append("<triggers>")
        lines.extend(trig_lines)
        lines.append("</triggers>")
    lines.append("</companion_mode>")
    return "\n".join(lines)


def _append_list_section(lines: List[str], tag: str, items: Any, *, limit: int = 8) -> None:
    rows = _as_list(items)[:limit]
    if not rows:
        return
    lines.append(f"<{tag}>")
    lines.extend(f"- {_xml(row)}" for row in rows)
    lines.append(f"</{tag}>")


def _looks_like_catchphrase_dump(text: str) -> bool:
    """「禁A/B/C」这类列表会被模型当可抄台词。"""
    raw = text or ""
    return raw.count("/") >= 2 and any(ch in raw for ch in "？?（()「")


def _lock_lines(doc: Dict[str, Any], flags: Optional[Dict[str, bool]] = None) -> List[str]:
    lock = doc.get("identity_lock") or {}
    if not isinstance(lock, dict):
        return []
    flags = flags or {}
    out: List[str] = []
    for key in ("energy", "taste", "stance"):
        if key == "taste" and not flags.get("taste"):
            continue
        val = str(lock.get(key) or "").strip()
        if val:
            out.append(val)
    return out


def _append_style(
    lines: List[str],
    examples: Any,
    *,
    good: int = 3,
    bad: int = 2,
    daily: bool = False,
) -> None:
    """Quoted ✓/✗ lines teach the model to copy catchphrases. Rhythm is voice_pack only."""
    return


def build_scene_block(doc: Dict[str, Any], *, daily: bool = False) -> str:
    sm = doc.get("scene_mode") or {}
    if not isinstance(sm, dict) or not sm:
        return ""
    lines = ["<scene_mode>"]
    _append_list_section(lines, "read", sm.get("read"), limit=6)
    _append_list_section(lines, "idle", sm.get("idle"), limit=5)
    _append_list_section(lines, "usage", sm.get("usage"), limit=4)
    _append_list_section(lines, "allow", sm.get("allow"), limit=3)
    _append_list_section(lines, "forbid", sm.get("forbid"), limit=4)
    _append_style(lines, sm.get("style_examples"), good=3, bad=2, daily=daily)
    lines.append("</scene_mode>")
    if len(lines) == 2:
        return ""
    return "\n".join(lines)


def build_story_block(
    doc: Dict[str, Any],
    *,
    story_prompt: str = "",
    others: str = "",
) -> str:
    sm = doc.get("story_mode") or {}
    if not isinstance(sm, dict) or not sm:
        return ""
    lines = ["<story_mode>"]
    prompt = (story_prompt or "").strip() or "一段尚未命名的故事"
    lines.append(f"<brief>{_xml(prompt)}</brief>")
    others_txt = (others or "").strip()
    if others_txt:
        lines.append(f"<others>{_xml(others_txt)}</others>")
    _append_list_section(lines, "directive", sm.get("directive"), limit=8)
    _append_list_section(lines, "style", sm.get("style"), limit=6)
    _append_list_section(lines, "interaction", sm.get("interaction"), limit=6)
    lines.append("- 末尾必须输出 <memory_point>一句情节摘要</memory_point>")
    _append_style(lines, sm.get("style_examples"), good=2, bad=2)
    lines.append("</story_mode>")
    return "\n".join(lines)


def build_phone_block(doc: Dict[str, Any]) -> str:
    pm = doc.get("phone_mode") or {}
    if not isinstance(pm, dict) or not pm:
        return ""
    lines = ["<phone_mode priority=\"above_speech\">"]
    _append_list_section(lines, "format", pm.get("format"), limit=8)
    _append_list_section(lines, "behavior", pm.get("behavior"), limit=6)
    _append_style(lines, pm.get("style_examples"), good=4, bad=3)
    lines.append("</phone_mode>")
    if len(lines) == 2:
        return ""
    return "\n".join(lines)


def compile_module(character_id: str, module: str) -> str:
    """Static block used by the 人设正文 preview."""
    doc = load_config(character_id)
    mid = (module or "").strip()
    if mid == "scene":
        return build_scene_block(doc)
    if mid == "story":
        return build_story_block(doc, story_prompt="（预览：故事引子）", others="（预览：同场角色）")
    if mid == "mode_phone":
        return build_phone_block(doc)
    if mid == "companion":
        return build_companion_block(doc)
    if mid == "trigger":
        return build_trigger_block(doc)
    return compile_preview(character_id)


def build_trigger_block(doc: Dict[str, Any], *, daily: bool = False) -> str:
    tm = doc.get("trigger_mode") or {}
    if not isinstance(tm, dict) or not tm:
        return ""
    lines = ["<at_mode>"]
    for key, tag in (
        ("arbitration", "arbitration"),
        ("forbid", "forbid"),
        ("framework", "framework"),
        ("address", "address"),
        ("fact_rules", "facts"),
    ):
        rows = _as_list(tm.get(key))
        if not rows:
            continue
        lines.append(f"<{tag}>")
        lines.extend(f"- {_xml(row)}" for row in rows)
        lines.append(f"</{tag}>")
    trig_lines = []
    for item in tm.get("behavior_triggers") or []:
        if not isinstance(item, dict):
            continue
        trig = str(item.get("trigger") or "").strip()
        action = str(item.get("action") or item.get("note") or "").strip()
        if trig or action:
            trig_lines.append(f"- {_xml(trig)} → {_xml(action)}")
    if trig_lines:
        lines.append("<triggers>")
        lines.extend(trig_lines)
        lines.append("</triggers>")
    _append_style(lines, tm.get("style_examples"), good=3, bad=2, daily=daily)
    lines.append("</at_mode>")
    return "\n".join(lines)


def _peer_block(doc: Dict[str, Any]) -> str:
    rel = _peer_rel(doc)
    if not rel:
        return ""
    tid = str(rel.get("target_id") or "peer").strip()
    name = str(rel.get("address_rule") or tid)
    lines = []
    addr = str(rel.get("address_rule") or "").strip()
    if addr:
        lines.append(f"address: {_xml(addr)}")
    forbidden = rel.get("forbidden_names") or []
    if isinstance(forbidden, str):
        forbidden = [forbidden]
    names = [str(x) for x in forbidden if x]
    if names:
        lines.append("forbidden_names: " + "、".join(_xml(x) for x in names))
    called = str(rel.get("called_by") or "").strip()
    if called:
        lines.append(f"called_by: {_xml(called)}")
    dyn = str(rel.get("dynamic_description") or "").strip()
    if dyn:
        lines.append(_xml(dyn))
    rules = doc.get("behavioral_rules") or {}
    for rule in _lines(rules.get("multi_turn_rules") or []):
        lines.append(f"- {_xml(rule)}")
    if not lines:
        return ""
    return f'<peer id="{_xml(tid)}">\n' + "\n".join(lines) + "\n</peer>"


def _trigger_hits(doc: Dict[str, Any], context: str) -> List[str]:
    blob = context or ""
    if not blob.strip():
        return []
    rules = doc.get("behavioral_rules") or {}
    hits = []
    for item in rules.get("interaction_logic") or []:
        if not isinstance(item, dict):
            continue
        trig = str(item.get("trigger") or "").strip()
        resp = str(item.get("response") or "").strip()
        if not trig:
            continue
        keys = [k for k in re.split(r"[/、,，\s]+", trig) if len(k) >= 2]
        grams = []
        for key in keys:
            body = re.sub(r"^(被|有人|问及)", "", key)
            grams.append(body)
            grams.extend(body[i : i + 2] for i in range(0, max(0, len(body) - 1)) if len(body[i : i + 2]) == 2)
        if any(k and k in blob for k in keys + grams) or trig in blob:
            hits.append(f"- {_xml(trig)} -> {_xml(resp)}")
    return hits


def topic_flags(context: str) -> Dict[str, bool]:
    text = context or ""
    return {
        "family": any(h in text for h in _FAMILY_HINTS),
        "band": any(h in text for h in _BAND_HINTS),
        "taste": any(h in text for h in _TASTE_HINTS),
        "aroma": any(h in text for h in _AROMA_HINTS),
    }


def compile_persona(
    character_id: str,
    *,
    mode: str = "chat",
    peer_online: bool = False,
    context_text: str = "",
    interaction: str = "face",
    sender_qq: str = "",
    at_mode: bool = False,
    inject_scene: bool = False,
    story_prompt: str = "",
    story_others: str = "",
) -> str:
    """Return the XML role block. routing is read, never injected."""
    mode_l = (mode or "chat").strip().lower()
    if mode_l not in ("chat", "story", "phone"):
        mode_l = "story" if mode_l == "story" else "chat"
    if (interaction or "").strip().lower() == "phone" and mode_l == "chat":
        mode_l = "phone"

    doc = load_config(character_id)
    ident = doc.get("identity") or {}
    meta = doc.get("meta") or {}
    cid = str(meta.get("id") or character_id or "").strip().lower()
    name = str(ident.get("name_full") or meta.get("display_name") or cid)

    flags = topic_flags(context_text)
    optional: List[str] = []

    role_bits = [
        f'id="{_xml(cid)}"',
        f'name="{_xml(name)}"',
    ]
    lines = [f"<role {' '.join(role_bits)}>"]

    lines.append("<core>")
    for row in _axioms(doc):
        lines.append(f"- {_xml(row)}")
    lines.append("</core>")

    lock_rows = _lock_lines(doc, flags)
    if lock_rows:
        lines.append("<lock>")
        lines.extend(f"- {_xml(row)}" for row in lock_rows)
        lines.append("</lock>")

    ident_lines = []
    for key in ("name_full", "band_role", "instrument", "appearance", "residence"):
        val = str(ident.get(key) or "").strip()
        if val:
            ident_lines.append(f"{key}: {_xml(val)}")
    if not ident_lines:
        ident_lines.append(f"name: {_xml(name)}")
    lines.append("<identity>")
    lines.extend(ident_lines)
    lines.append("</identity>")

    trait_rows = _traits(doc, include_medium=False)
    if trait_rows:
        lines.append("<traits>")
        for item in trait_rows:
            label = str(item.get("label") or "").strip()
            desc = str(item.get("description") or "").strip()
            lines.append(f"- {_xml(label)}: {_xml(desc)}")
        lines.append("</traits>")

    if mode_l == "story":
        if not (doc.get("story_mode") or {}):
            lines.append("<story_override>")
            lines.append("- ACTION FREQUENCY: Moderate. Use () for subtle gestures.")
            lines.append("- LENGTH: Allow 2-4 segments. Sensory details encouraged.")
            lines.append("- FORBIDDEN: Ignore daily brevity. Focus on emotional depth.")
            lines.append("- OUTPUT: Must end with <memory_point>一句情节摘要</memory_point>")
            lines.append("</story_override>")
    else:
        speech = _speech_lines(doc, mode_l)
        if speech:
            lines.append("<speech>")
            lines.extend(f"- {_xml(row)}" if not row.startswith("-") else _xml(row) for row in speech)
            lines.append("</speech>")

    fact_n, trig_n = (3, 2) if mode_l == "chat" else ((2, 1) if mode_l == "phone" else (4, 2))
    mem = _memory_lines(doc, facts=fact_n, triggers=trig_n, flags=flags)
    if mem:
        lines.append("<memory>")
        lines.extend(f"- {_xml(row)}" for row in mem)
        lines.append("</memory>")

    lines.append("</role>")
    body = "\n".join(lines)

    peer_qq = _routing_peer_qq(doc)
    companion_turn = bool(
        mode_l != "story"
        and peer_online
        and sender_qq
        and peer_qq
        and str(sender_qq).strip() == peer_qq
    )
    # peer/triggers stay ahead of topic blocks so a long <family> cannot crowd them out.
    required_extra: List[str] = []
    mode_extra: List[str] = []
    if companion_turn:
        block = build_companion_block(doc)
        if block:
            mode_extra.append(block)
        else:
            peer = _peer_block(doc)
            if peer:
                required_extra.append(peer)
    elif peer_online and not at_mode:
        peer = _peer_block(doc)
        if peer:
            required_extra.append(peer)
    if not companion_turn and mode_l not in ("story", "phone"):
        block = build_outsider_block(doc)
        if block:
            mode_extra.append(block)
    daily = is_daily_register(context_text)
    if at_mode and mode_l != "story":
        block = build_trigger_block(doc, daily=daily)
        if block:
            mode_extra.append(block)
    if mode_l == "story":
        block = build_story_block(doc, story_prompt=story_prompt, others=story_others)
        if block:
            mode_extra.append(block)
    if inject_scene and mode_l != "story":
        block = build_scene_block(doc, daily=daily)
        if block:
            mode_extra.append(block)
    if (interaction or "").strip().lower() == "phone" or mode_l == "phone":
        block = build_phone_block(doc)
        if block:
            mode_extra.append(block)
    hits = _trigger_hits(doc, context_text)
    if hits and not (at_mode and mode_l != "story"):
        required_extra.append("<triggers>\n" + "\n".join(hits) + "\n</triggers>")
    if flags["family"]:
        fam = _family_block(doc)
        if fam:
            optional.append(fam)
    if flags["band"]:
        band = _band_block(doc)
        if band:
            optional.append(band)

    budget = _TOKEN_BUDGET.get(mode_l, 1500)

    def _join(parts: List[str]) -> str:
        return "\n".join(p for p in parts if p)

    text = _join([body] + required_extra + optional + mode_extra)
    if _estimate(text) <= budget:
        return text

    # Drop memory before topic blocks. Never drop <core>, <peer>, companion, or @.
    no_mem = re.sub(r"\n<memory>[\s\S]*?</memory>", "", body)
    text = _join([no_mem] + required_extra + optional + mode_extra)
    if _estimate(text) <= budget:
        return text

    kept_opt: List[str] = []
    base_plus = _join([no_mem] + required_extra)
    for block in optional:
        trial = _join([base_plus] + kept_opt + [block])
        if _estimate(trial) <= budget:
            kept_opt.append(block)
    trimmed = _join([base_plus] + kept_opt)
    # companion / @ blocks are turn-scoped and must not be trimmed away.
    return _join([trimmed] + mode_extra)


def compile_preview(character_id: str) -> str:
    """Static preview for the 人设正文 page: chat shell, no topic extras."""
    return compile_persona(character_id, mode="chat", peer_online=False, context_text="")
