"""Atomic persona config_v2: load, save, and subset rendering for prompts."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import yaml

PERSONA_ROOT = Path("data/persona")
ALLOWED = ("anon", "soyo")
PRIORITIES = ("Critical", "High", "Medium", "Low")

# Daily-only forbid tokens dropped in story mode (substring match).
_DAILY_FORBID_HINTS = (
    "书面语",
    "长篇",
    "抢话",
    "大声",
    "直接告白",
)


def config_path(character_id: str) -> Path:
    cid = _cid(character_id)
    return PERSONA_ROOT / cid / "config_v2.yaml"


def _cid(character_id: str) -> str:
    cid = (character_id or "").strip().lower()
    if cid not in ALLOWED:
        raise ValueError(f"unknown character: {character_id}")
    return cid


def load_config(character_id: str) -> Dict[str, Any]:
    path = config_path(character_id)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config_v2 must be a mapping")
    return data


def save_config(character_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    cid = _cid(character_id)
    if not isinstance(data, dict):
        raise ValueError("body must be an object")
    meta = dict(data.get("meta") or {})
    mid = str(meta.get("id") or "").strip().lower()
    if mid and mid != cid:
        raise ValueError(f"meta.id must be {cid}")
    meta["id"] = cid
    if not meta.get("version"):
        meta["version"] = "2.0"
    data = dict(data)
    data["meta"] = meta
    path = config_path(cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    try:
        from .characters import invalidate_peer_binding

        invalidate_peer_binding(cid)
    except Exception:
        pass
    return data


def _split_freq(raw: Any) -> Dict[str, str]:
    text = str(raw or "").strip()
    daily, story = text, text
    if "|" in text:
        left, right = text.split("|", 1)
        daily = left.replace("Daily:", "").replace("Daily：", "").strip()
        story = right.replace("Story:", "").replace("Story：", "").strip()
    return {"daily": daily, "story": story}


def _traits(doc: Dict[str, Any], *, include_low: bool) -> List[Dict[str, Any]]:
    psych = doc.get("psychology") or {}
    out: List[Dict[str, Any]] = []
    for item in psych.get("core_traits") or []:
        if not isinstance(item, dict):
            continue
        pri = str(item.get("priority") or "Medium")
        if not include_low and pri == "Low":
            continue
        out.append(item)
    return out


def _section_keys(sections: Sequence[str]) -> set:
    keys = set()
    for raw in sections:
        key = (raw or "").strip()
        if key:
            keys.add(key)
    return keys


def _wants(wanted: set, *names: str) -> bool:
    if not wanted:
        return True
    for name in names:
        if name in wanted:
            return True
        # parent request includes child
        if any(name.startswith(w + ".") or w.startswith(name + ".") for w in wanted):
            return True
    return False


def get_persona_subset(
    character_id: str,
    sections: Optional[Iterable[str]] = None,
    *,
    mode: Optional[str] = None,
) -> str:
    doc = load_config(character_id)
    mode_l = (mode or "chat").strip().lower()
    wanted = _section_keys(list(sections or []))
    include_low = "psychology" in wanted
    lines: List[str] = []

    ident = doc.get("identity") or {}
    if _wants(wanted, "identity"):
        aliases = "、".join(str(x) for x in (ident.get("name_aliases") or []) if x)
        bits = [
            str(ident.get("name_full") or ""),
            f"年龄{ident.get('age')}" if ident.get("age") not in (None, "") else "",
            str(ident.get("occupation") or ""),
            str(ident.get("band_role") or ""),
            str(ident.get("instrument") or ""),
        ]
        head = "；".join(b for b in bits if b)
        if aliases:
            head += f"。别名：{aliases}"
        if head:
            lines.append(f"身份：{head}")

    if _wants(wanted, "psychology", "psychology.core_traits"):
        traits = _traits(doc, include_low=include_low or "psychology" in wanted)
        if "psychology" not in wanted and "psychology.core_traits" in wanted:
            traits = [t for t in traits if str(t.get("priority")) != "Low"]
        for t in traits:
            label = str(t.get("label") or t.get("id") or "").strip()
            desc = str(t.get("description") or "").strip()
            pri = str(t.get("priority") or "")
            if not label:
                continue
            extra = f"：{desc}" if desc else ""
            tag = f"[{pri}] " if pri else ""
            lines.append(f"特质：{tag}{label}{extra}")
        if "psychology" in wanted:
            psych = doc.get("psychology") or {}
            fears = [str(x) for x in (psych.get("fears") or []) if x]
            desires = [str(x) for x in (psych.get("desires") or []) if x]
            defense = str(psych.get("defense_mechanism") or "").strip()
            if fears:
                lines.append("恐惧：" + "；".join(fears))
            if desires:
                lines.append("欲求：" + "；".join(desires))
            if defense:
                lines.append(f"防御：{defense}")

    if _wants(wanted, "social_context"):
        social = doc.get("social_context") or {}
        fam = social.get("family_status") or {}
        if isinstance(fam, dict) and fam:
            fam_bits = [str(v) for v in fam.values() if v]
            if fam_bits:
                lines.append("家庭：" + "；".join(fam_bits))
        image = str(social.get("public_image") or "").strip()
        if image:
            lines.append(f"对外：{image}")
        for rel in social.get("peer_relations") or []:
            if not isinstance(rel, dict):
                continue
            tid = str(rel.get("target_id") or "")
            kind = str(rel.get("relationship_type") or "")
            dyn = str(rel.get("dynamic_description") or "")
            lines.append(f"关系/{tid}：{kind}。{dyn}".rstrip("。"))

    rules = doc.get("behavioral_rules") or {}
    if _wants(wanted, "behavioral_rules", "behavioral_rules.speech_style"):
        speech = dict(rules.get("speech_style") or {})
        lang = str(speech.get("language") or "")
        slen = str(speech.get("sentence_length") or "")
        if lang or slen:
            lines.append(f"说话：{lang} / {slen}".strip(" /"))
        punct = speech.get("punctuation_usage") or {}
        if isinstance(punct, dict) and punct:
            lines.append(
                "标点："
                + "；".join(f"{k}={v}" for k, v in punct.items() if v is not None)
            )
        forbids = [str(x) for x in (speech.get("forbidden_patterns") or []) if x]
        if mode_l == "story":
            forbids = [
                x
                for x in forbids
                if not any(h in x for h in _DAILY_FORBID_HINTS)
            ]
        if forbids:
            lines.append("禁止：" + "；".join(forbids))
        thought = rules.get("inner_thought") or {}
        if isinstance(thought, dict) and thought and mode_l != "phone":
            style = str(thought.get("style") or "").strip()
            allow = [str(x) for x in (thought.get("allow") or []) if x][:3]
            forbid = [str(x) for x in (thought.get("forbid") or []) if x][:3]
            freq = str(thought.get("frequency") or "").strip()
            bits = []
            if style:
                bits.append(style)
            if allow:
                bits.append("例" + " / ".join(allow))
            if forbid:
                bits.append("禁" + " / ".join(forbid))
            if freq:
                bits.append(freq)
            if bits:
                lines.append("内心括号：" + "；".join(bits))

    if _wants(wanted, "behavioral_rules", "behavioral_rules.action_style"):
        if mode_l != "phone":
            action = rules.get("action_style") or {}
            freq = _split_freq(action.get("frequency_limit"))
            if mode_l == "story":
                lines.append(f"动作频率：{freq['story']}")
            else:
                lines.append(f"动作频率：{freq['daily']}")
            focus = [str(x) for x in (action.get("visual_focus") or []) if x]
            if focus:
                lines.append("动作焦点：" + "；".join(focus))

    if _wants(wanted, "behavioral_rules", "behavioral_rules.interaction_logic"):
        for item in rules.get("interaction_logic") or []:
            if not isinstance(item, dict):
                continue
            trig = str(item.get("trigger") or item.get("trigger_condition") or "")
            resp = str(item.get("response") or item.get("response_pattern") or "")
            if trig or resp:
                lines.append(f"若{trig}：{resp}")

    if _wants(wanted, "memory_anchors"):
        mem = doc.get("memory_anchors") or {}
        facts = [str(x) for x in (mem.get("long_term_facts") or []) if x]
        trigs = [str(x) for x in (mem.get("emotional_triggers") or []) if x]
        if facts:
            lines.append("锚点：" + "；".join(facts))
        if trigs:
            lines.append("触发：" + "；".join(trigs))

    return "\n".join(lines).strip()


def identity_header(character_id: str) -> Optional[str]:
    """Name + up to 3 Critical/High trait labels. None if no config file."""
    try:
        doc = load_config(character_id)
    except (FileNotFoundError, ValueError):
        return None
    ident = doc.get("identity") or {}
    name = str(ident.get("name_full") or (doc.get("meta") or {}).get("display_name") or "").strip()
    if not name:
        return None
    labels: List[str] = []
    for item in (doc.get("psychology") or {}).get("core_traits") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("priority") or "") not in ("Critical", "High"):
            continue
        label = str(item.get("label") or "").strip()
        if label:
            labels.append(label)
        if len(labels) >= 3:
            break
    if labels:
        return f"{name}（关键词：{'、'.join(labels)}）"
    return name
