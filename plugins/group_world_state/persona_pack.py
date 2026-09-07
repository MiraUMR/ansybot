"""人设模块机器块 PERSONA_PACK / base XML <role>：解析 / 格式化 / 旧 Markdown 迁移。"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Tuple

_PACK_RE = re.compile(r"\[PERSONA_PACK\]([\s\S]*?)\[/PERSONA_PACK\]", re.I)
_PEER_FENCE = re.compile(r"```peer\s*\n([\s\S]*?)\n```", re.I)
_NOTE_SEP = " :: "
_HEADER_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$")

# 模块 → [(section_key, 表单标题, kind)]；kind: fact|item
MODULE_SECTIONS: Dict[str, List[Tuple[str, str, str]]] = {
    "base": [
        ("peer", "同伴绑定", "fact"),
        ("hard_rules", "不可推翻设定", "item"),
        ("identity", "你是谁", "fact"),
        ("family_context", "家庭语境", "item"),
        ("personality", "性格", "item"),
        ("about_peer", "关于同伴", "item"),
        ("band_members", "乐队成员", "item"),
        ("address", "称呼规则", "item"),
        ("mygo", "关于乐队", "item"),
        ("speech", "说话方式", "item"),
        ("memory", "事实与记忆", "item"),
        ("image", "看图反应", "item"),
        ("presence", "同伴在场", "item"),
        ("allow", "允许", "item"),
        ("forbid", "禁止", "item"),
        ("tone", "语气标签", "item"),
        ("behaviors", "行为规则", "item"),
        ("ex_ok", "正例", "item"),
        ("ex_bad", "反例", "item"),
    ],
    "companion": [
        ("group_chat", "普通群聊", "item"),
        ("peer_chat", "同伴互聊", "item"),
        ("close_rules", "互聊收束", "item"),
        ("resonate", "互聊强化", "item"),
        ("allow", "允许", "item"),
        ("forbid", "禁止", "item"),
        ("tone", "语气", "item"),
        ("behaviors", "行为规则", "item"),
        ("ex_ok", "正例", "item"),
        ("ex_bad", "反例", "item"),
    ],
    "trigger": [
        ("forbid", "绝对禁止", "item"),
        ("arbitration", "规则仲裁", "item"),
        ("framework", "响应优先级", "item"),
        ("judge", "判断铁律", "item"),
        ("address", "称呼规则", "item"),
        ("fact_rules", "事实类处理", "item"),
        ("lifestyle_facts", "生活类事实转化", "item"),
        ("allow", "允许", "item"),
        ("behaviors", "行为规则", "item"),
        ("ex_ok", "正例", "item"),
        ("ex_bad", "反例", "item"),
    ],
    "scene": [
        ("scene_read", "场景读取", "item"),
        ("idle_react", "idle场面反应", "item"),
        ("scene_slot", "当前场景槽", "fact"),
        ("allow", "允许", "item"),
        ("forbid", "禁止", "item"),
        ("behaviors", "行为规则", "item"),
        ("ex_ok", "正例", "item"),
        ("ex_bad", "反例", "item"),
    ],
    "story": [
        ("context", "故事上下文", "fact"),
        ("rules", "响应规则", "item"),
        ("close_beat", "本轮收束", "item"),
        ("style", "风格锚点", "item"),
        ("allow", "允许", "item"),
        ("forbid", "禁止", "item"),
        ("behaviors", "行为规则", "item"),
        ("ex_ok", "正例", "item"),
        ("ex_bad", "反例", "item"),
    ],
}

_HEADER_MAP = {
    "同伴绑定": "peer",
    "不可推翻的强设定": "hard_rules",
    "不可推翻的强设定（最高优先级）": "hard_rules",
    "你是谁": "identity",
    "性格": "personality",
    "性格（要演出来，不要自我介绍式背设定）": "personality",
    "千早爱音": "about_peer",
    "长崎素世": "about_peer",
    "乐队其他人": "band_members",
    "乐队其他人（认识，但不要变成百科）": "band_members",
    "对乐队成员的称呼": "address",
    "称呼执行铁律": "address",
    "关于 mygo!!!!!": "mygo",
    "关于 MyGO!!!!!": "mygo",
    "说话方式": "speech",
    "说话方式（主调：微信闲聊的大姐姐，不是人设朗读）": "speech",
    "说话方式（主调：微信闲聊，不是人设朗读）": "speech",
    "口吻样本": "ex_ok",
    "口吻样本（学味道，不要背清单）": "ex_ok",
    "开头别定式": "forbid",
    "开头别定式（重要）": "forbid",
    "少一点讲解腔": "forbid",
    "事实与记忆的表达方式": "memory",
    "看到图片时": "image",
    "同伴在场": "presence",
    "普通群聊": "group_chat",
    "普通群聊（无标签 / 非@消息）": "group_chat",
    "与小爱音互聊": "peer_chat",
    "与 soyorin 互聊": "peer_chat",
    "互聊口吻": "ex_ok",
    "互聊口吻（学味道）": "ex_ok",
    "互聊适可而止": "close_rules",
    "bot互聊互动强化": "resonate",
    "Bot互聊互动强化": "resonate",
    "场景记忆读取规则": "scene_read",
    "环境/场面反应": "idle_react",
    "环境/场面反应（无爱好命中 = idle 时强制）": "idle_react",
    "当前场景": "scene_slot",
    "响应规则": "rules",
    "绝对禁止": "forbid",
    "情境自适应响应框架": "framework",
    "判断铁律": "judge",
    "称呼规则": "address",
    "事实查询/纠错类消息的特殊处理": "fact_rules",
    "本轮收束": "close_beat",
    "风格锚点": "style",
}

_PEER_KEYS = (
    "self_id",
    "self_display",
    "self_qq",
    "peer_id",
    "peer_display",
    "peer_qq",
    "peer_call",
    "peer_absent",
    "peer_forbid",
)


def empty_persona_pack(module: str = "base") -> Dict[str, Any]:
    mid = (module or "base").strip() or "base"
    out: Dict[str, Any] = {"module": mid}
    for key, _label, _kind in MODULE_SECTIONS.get(mid, MODULE_SECTIONS["base"]):
        out[key] = []
    return out


def _parse_annotated(raw: str) -> Dict[str, str]:
    s = (raw or "").strip()
    note = ""
    if _NOTE_SEP in s:
        s, note = s.split(_NOTE_SEP, 1)
        s, note = s.strip(), note.strip()
        if note.lower().startswith("note="):
            note = note.split("=", 1)[1].strip()
    key = ""
    value = s
    if "=" in s and not s.upper().startswith("IF "):
        left, right = s.split("=", 1)
        if left.strip() and " " not in left.strip():
            key, value = left.strip(), right.strip()
    return {"key": key, "value": value, "note": note}


def normalize_items(items: Any, as_fact: bool = False) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if items is None:
        return out
    if isinstance(items, str):
        items = [ln.strip() for ln in items.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not isinstance(items, list):
        return out
    for x in items:
        if isinstance(x, dict):
            key = str(x.get("key") or "").strip()
            value = str(x.get("value") or x.get("text") or "").strip()
            note = str(x.get("note") or "").strip()
            if not value and not key:
                continue
            if as_fact and not key and "=" in value:
                out.append(_parse_annotated(f"{value}{_NOTE_SEP}{note}" if note else value))
            else:
                out.append({"key": key, "value": value, "note": note})
            continue
        parsed = _parse_annotated(str(x))
        if parsed["value"] == "(none)" and not parsed["note"]:
            continue
        if parsed["value"] or parsed["key"]:
            out.append(parsed)
    return out


def _format_item_line(it: Dict[str, str], as_fact: bool = False, include_note: bool = True) -> str:
    if as_fact and it.get("key"):
        body = f"{it['key']}={it.get('value') or ''}"
    else:
        body = it.get("value") or it.get("key") or ""
    note = (it.get("note") or "").strip()
    if include_note and note:
        return f"{body}{_NOTE_SEP}{note}"
    return body


def _section_kind(module: str, key: str) -> str:
    for sk, _label, kind in MODULE_SECTIONS.get(module, []):
        if sk == key:
            return kind
    return "item"


def pack_from_request(data: Dict[str, Any], module: str) -> Dict[str, Any]:
    mid = (module or "base").strip() or "base"
    src = data.get("pack") if isinstance(data.get("pack"), dict) else data
    out = empty_persona_pack(mid)
    if not isinstance(src, dict):
        return out
    for key, _label, kind in MODULE_SECTIONS.get(mid, []):
        if key in src and src[key] is not None:
            out[key] = normalize_items(src[key], as_fact=(kind == "fact"))
    return out


def _emit_peer_fence(peer_items: List[Dict[str, str]]) -> str:
    if not peer_items:
        return ""
    lines = ["```peer"]
    for it in peer_items:
        k = (it.get("key") or "").strip()
        v = (it.get("value") or "").strip()
        if not k:
            continue
        # QQ 等保持引号风格可读
        if k.endswith("_qq") and v and not (v.startswith('"') or v.startswith("'")):
            lines.append(f'{k}: "{v}"')
        else:
            lines.append(f"{k}: {v}")
    lines.append("```")
    return "\n".join(lines) + "\n\n"


def format_persona_pack(pack: Dict[str, Any], *, strip_notes: bool = False) -> str:
    mid = str((pack or {}).get("module") or "base").strip() or "base"
    data = empty_persona_pack(mid)
    if isinstance(pack, dict):
        for key, _label, kind in MODULE_SECTIONS.get(mid, []):
            data[key] = normalize_items(pack.get(key), as_fact=(kind == "fact"))
        data["module"] = mid

    # base / trigger 用紧凑 XML（省 token）
    if mid == "base":
        return format_role_xml(data)
    if mid == "trigger":
        return format_trigger_xml(data)

    include_note = not strip_notes
    parts: List[str] = []
    lines = [
        "[PERSONA_PACK]",
        f"module: {mid}",
        "",
    ]
    for key, _label, kind in MODULE_SECTIONS.get(mid, []):
        items = data.get(key) or []
        lines.append(f"{key}:")
        if items:
            lines.extend(
                f"- {_format_item_line(it, as_fact=(kind == 'fact'), include_note=include_note)}"
                for it in items
            )
        else:
            lines.append("- (none)")
        lines.append("")
    lines.append("[/PERSONA_PACK]")
    parts.append("\n".join(lines) + "\n")
    return "".join(parts)


def parse_persona_pack(text: str, module: str = "base") -> Dict[str, Any]:
    raw = (text or "").replace("\r\n", "\n").strip()
    mid = (module or "base").strip() or "base"
    if "<role" in raw.lower():
        return parse_role_xml(raw, mid)
    if "<trigger" in raw.lower() or mid == "trigger" and re.search(r"<trigger\b", raw, re.I):
        return parse_trigger_xml(raw, mid)
    m = _PACK_RE.search(raw)
    if m:
        pack = _parse_pack_body(m.group(1), mid)
        # 若正文前有 peer fence，合并
        if mid == "base" and not any(
            (it.get("key") or "") == "peer_qq" for it in (pack.get("peer") or [])
        ):
            fence = _PEER_FENCE.search(raw)
            if fence:
                try:
                    import yaml

                    data = yaml.safe_load(fence.group(1)) or {}
                except Exception:
                    data = {}
                if isinstance(data, dict):
                    for k in _PEER_KEYS:
                        if data.get(k) is not None and str(data.get(k)).strip():
                            pack.setdefault("peer", []).append(
                                {"key": k, "value": str(data.get(k)).strip(), "note": ""}
                            )
        return pack
    return migrate_legacy_markdown(raw, mid)


def _parse_pack_body(body: str, module: str) -> Dict[str, Any]:
    pack = empty_persona_pack(module)
    section = ""
    for line in (body or "").splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("module:"):
            pack["module"] = s.split(":", 1)[1].strip() or module
            section = ""
            continue
        # section header
        if s.endswith(":") and not s.startswith("-"):
            key = s[:-1].strip().lower()
            # allow exact keys
            keys = {k for k, _l, _k in MODULE_SECTIONS.get(pack["module"], MODULE_SECTIONS["base"])}
            if key in keys:
                section = key
                continue
        item = s[2:].strip() if s.startswith("- ") else s
        if not item or item in ("-", "(none)"):
            continue
        if not section:
            continue
        kind = _section_kind(pack["module"], section)
        pack[section].extend(normalize_items([item], as_fact=(kind == "fact")))
    # 若 pack 内 peer 空，尝试正文外 fence（format 会把 fence 放在 pack 前）
    return pack


def _map_header(title: str) -> Optional[str]:
    t = (title or "").strip()
    if t in _HEADER_MAP:
        return _HEADER_MAP[t]
    # 模糊：去掉括号说明
    base = re.sub(r"[（(].*$", "", t).strip()
    if base in _HEADER_MAP:
        return _HEADER_MAP[base]
    low = t.lower()
    for k, v in _HEADER_MAP.items():
        if k.lower() in low or low in k.lower():
            return v
    return None


def _bullet_to_item(line: str, as_fact: bool) -> Dict[str, str]:
    s = line.strip()
    if s.startswith("- "):
        s = s[2:].strip()
    elif re.match(r"^\d+\.\s+", s):
        s = re.sub(r"^\d+\.\s+", "", s).strip()
    # 「姓名：xxx」→ name=xxx
    if as_fact and ("：" in s or ": " in s):
        for sep in ("：", ": "):
            if sep in s:
                left, right = s.split(sep, 1)
                left, right = left.strip(), right.strip()
                if left and len(left) <= 12 and " " not in left:
                    # map common chinese keys
                    key_map = {
                        "姓名": "name",
                        "别人怎么叫": "called_as",
                        "外表印象": "look",
                        "生日": "birthday",
                        "现居": "live",
                        "经历": "history",
                        "家庭": "family",
                        "一句话身份": "role_one_liner",
                        "你称呼千早爱音固定为": "call_peer",
                        "你称呼长崎素世固定为": "call_peer",
                    }
                    key = key_map.get(left, re.sub(r"\W+", "_", left) or "fact")
                    return {"key": key, "value": right, "note": left}
    return _parse_annotated(s)


def migrate_legacy_markdown(text: str, module: str) -> Dict[str, Any]:
    """旧 Markdown → 结构化 pack（仅内存迁移，保存后落盘为 PERSONA_PACK）。"""
    mid = (module or "base").strip() or "base"
    pack = empty_persona_pack(mid)
    raw = (text or "").replace("\r\n", "\n")

    # peer fence
    pm = _PEER_FENCE.search(raw)
    if pm and mid == "base":
        try:
            import yaml

            data = yaml.safe_load(pm.group(1)) or {}
        except Exception:
            data = {}
        if isinstance(data, dict):
            for k in _PEER_KEYS:
                if data.get(k) is not None and str(data.get(k)).strip():
                    pack["peer"].append(
                        {"key": k, "value": str(data.get(k)).strip(), "note": ""}
                    )
        raw = _PEER_FENCE.sub("", raw)

    section = "personality" if mid == "base" else "rules"
    known = {k for k, _l, _kd in MODULE_SECTIONS.get(mid, [])}
    if section not in known:
        section = next(iter(known), "rules")

    buf: List[str] = []

    def flush():
        nonlocal buf
        if not buf:
            return
        kind = _section_kind(mid, section)
        for ln in buf:
            ln = ln.strip()
            if not ln:
                continue
            if ln.startswith("✅"):
                pack.setdefault("ex_ok", []).append(
                    _bullet_to_item(ln.lstrip("✅").strip(), False)
                )
                continue
            if ln.startswith("❌"):
                pack.setdefault("ex_bad", []).append(
                    _bullet_to_item(ln.lstrip("❌").strip(), False)
                )
                continue
            it = _bullet_to_item(ln, as_fact=(kind == "fact"))
            if it.get("value") or it.get("key"):
                pack.setdefault(section, []).append(it)
        buf = []

    for line in raw.splitlines():
        hm = _HEADER_RE.match(line.strip())
        if hm:
            flush()
            mapped = _map_header(hm.group(1))
            if mapped and mapped in known:
                section = mapped
            else:
                # 未知标题：归入 behaviors，并把标题当 note 的一条
                section = "behaviors" if "behaviors" in known else section
                title = hm.group(1).strip()
                pack.setdefault(section, []).append(
                    {"key": "", "value": f"[section] {title}", "note": "原标题"}
                )
            continue
        if line.strip():
            buf.append(line)
    flush()

    # 清理空 peer 以外的 (none)
    for key, _l, kind in MODULE_SECTIONS.get(mid, []):
        pack[key] = normalize_items(pack.get(key), as_fact=(kind == "fact"))
    return pack


def peer_dict_from_pack(pack: Dict[str, Any]) -> Dict[str, str]:
    out = {k: "" for k in _PEER_KEYS}
    for it in normalize_items((pack or {}).get("peer"), as_fact=True):
        k = (it.get("key") or "").strip()
        if k in out:
            out[k] = (it.get("value") or "").strip()
    return out


def _peer_get(pack: Dict[str, Any], key: str, default: str = "") -> str:
    for it in normalize_items((pack or {}).get("peer"), as_fact=True):
        if (it.get("key") or "").strip() == key:
            return (it.get("value") or "").strip() or default
    return default


def _xml_esc(s: str) -> str:
    return html.escape((s or "").strip(), quote=True)


def _strip_note(value: str) -> str:
    s = (value or "").strip()
    if _NOTE_SEP in s:
        s = s.split(_NOTE_SEP, 1)[0].strip()
    return s


def _item_text(it: Dict[str, str], as_fact: bool = False) -> str:
    if as_fact and it.get("key"):
        return f"{it['key']}: {_strip_note(it.get('value') or '')}"
    return _strip_note(it.get("value") or it.get("key") or "")


def _bullets(items: List[Dict[str, str]], as_fact: bool = False) -> str:
    lines = []
    for it in items or []:
        t = _item_text(it, as_fact=as_fact)
        if t:
            lines.append(f"- {t}")
    return "\n".join(lines)


def _behavior_arrow(raw: str) -> str:
    s = _strip_note(raw)
    # IF a THEN b THEN c  →  a → b → c
    m = re.match(r"^IF\s+(.+)$", s, re.I)
    if not m:
        return s
    rest = m.group(1).strip()
    parts = re.split(r"\s+THEN\s+", rest, flags=re.I)
    return " → ".join(p.strip() for p in parts if p.strip())


def _behavior_from_arrow(raw: str) -> str:
    s = (raw or "").strip()
    if "→" not in s and "->" not in s:
        return s
    s = s.replace("->", "→")
    parts = [p.strip() for p in s.split("→") if p.strip()]
    if len(parts) < 2:
        return s
    out = f"IF {parts[0]}"
    for p in parts[1:]:
        out += f" THEN {p}"
    return out


def format_trigger_xml(pack: Dict[str, Any]) -> str:
    """trigger 模块紧凑 XML（无 :: 备注）。"""
    p = pack or {}
    parts: List[str] = ["<trigger>"]

    def add_list(tag: str, items: List[Dict[str, str]], *, arrows: bool = False) -> None:
        lines = []
        for it in items or []:
            if arrows:
                t = _behavior_arrow(_item_text(it))
            elif it.get("key"):
                t = f"{it['key']}={_strip_note(it.get('value') or '')}"
            else:
                t = _item_text(it)
            if t:
                lines.append(f"- {t}")
        if not lines:
            return
        parts.append(f"<{tag}>")
        parts.append("\n".join(lines))
        parts.append(f"</{tag}>")
        parts.append("")

    add_list("forbid", p.get("forbid") or [])
    # arbitration 可整段或列表
    arb = p.get("arbitration") or []
    if arb:
        parts.append('<arbitration priority="absolute">')
        if len(arb) == 1 and "\n" in (arb[0].get("value") or ""):
            parts.append((arb[0].get("value") or "").strip())
        else:
            for it in arb:
                t = _item_text(it)
                if t:
                    parts.append(f"- {t}" if not t.startswith("-") else t)
        parts.append("</arbitration>")
        parts.append("")
    add_list("framework", p.get("framework") or [])
    add_list("judge", p.get("judge") or [])
    add_list("address", p.get("address") or [])
    add_list("fact_rules", p.get("fact_rules") or [])
    add_list("lifestyle_facts", p.get("lifestyle_facts") or [])

    allow_vals = []
    for it in p.get("allow") or []:
        v = _strip_note(it.get("value") or "")
        if v:
            allow_vals.append(v)
    if allow_vals:
        parts.append("<allow>")
        parts.append("- " + " / ".join(allow_vals))
        parts.append("</allow>")
        parts.append("")

    add_list("behavior_triggers", p.get("behaviors") or [], arrows=True)

    goods = []
    for it in p.get("ex_ok") or []:
        t = _item_text(it)
        if t:
            goods.append(f"<good>{_xml_esc(t)}</good>")
    bads = []
    for it in p.get("ex_bad") or []:
        t = _item_text(it)
        reason = (it.get("note") or "").strip()
        if t:
            if reason:
                bads.append(f'<bad reason="{_xml_esc(reason)}">{_xml_esc(t)}</bad>')
            else:
                bads.append(f"<bad>{_xml_esc(t)}</bad>")
    if goods or bads:
        parts.append("<style_examples>")
        parts.append("\n".join(goods + bads))
        parts.append("</style_examples>")

    parts.append("</trigger>")
    text = "\n".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def parse_trigger_xml(text: str, module: str = "trigger") -> Dict[str, Any]:
    mid = (module or "trigger").strip() or "trigger"
    pack = empty_persona_pack(mid)
    raw = (text or "").strip()
    m = re.search(r"<trigger\b[^>]*>([\s\S]*?)</trigger>", raw, re.I)
    if not m:
        return pack
    body = m.group(1)

    def section(tag: str) -> str:
        mm = re.search(rf"<{tag}\b[^>]*>([\s\S]*?)</{tag}>", body, re.I)
        return mm.group(1) if mm else ""

    mapping = {
        "forbid": "forbid",
        "arbitration": "arbitration",
        "framework": "framework",
        "judge": "judge",
        "address": "address",
        "fact_rules": "fact_rules",
        "lifestyle_facts": "lifestyle_facts",
        "allow": "allow",
        "behavior_triggers": "behaviors",
    }
    for tag, key in mapping.items():
        sub = section(tag)
        if not sub.strip():
            continue
        if key == "arbitration":
            pack[key].append({"key": "", "value": sub.strip(), "note": "arbitration"})
            continue
        for line in _parse_list_block(sub):
            if key == "behaviors":
                pack[key].append(
                    {"key": "", "value": _behavior_from_arrow(line), "note": ""}
                )
            elif key == "allow" and " / " in line:
                for piece in re.split(r"\s*/\s*", line):
                    piece = piece.strip()
                    if piece:
                        pack[key].append({"key": "", "value": piece, "note": ""})
            elif key == "framework" and "=" in line and not line.upper().startswith("IF "):
                left, right = line.split("=", 1)
                if left.strip() and " " not in left.strip():
                    pack[key].append(
                        {"key": left.strip(), "value": right.strip(), "note": ""}
                    )
                else:
                    pack[key].append({"key": "", "value": line, "note": ""})
            else:
                pack[key].append({"key": "", "value": line, "note": ""})

    style = section("style_examples")
    for gm in re.finditer(r"<good>([\s\S]*?)</good>", style, re.I):
        t = gm.group(1).strip()
        if t:
            pack["ex_ok"].append({"key": "", "value": t, "note": ""})
    for bm in re.finditer(
        r'<bad(?:\s+reason="([^"]*)")?\s*>([\s\S]*?)</bad>', style, re.I
    ):
        reason, t = (bm.group(1) or "").strip(), (bm.group(2) or "").strip()
        if t:
            pack["ex_bad"].append({"key": "", "value": t, "note": reason})
    return pack


def format_role_xml(pack: Dict[str, Any]) -> str:
    """base 模块紧凑 XML（v3：expression_spectrum / style_boundary；兼容 v2 style_anchor）。"""
    p = pack or {}
    sid = _peer_get(p, "self_id", "anon")
    sname = _peer_get(p, "self_display", "")
    sqq = _peer_get(p, "self_qq", "")
    pid = _peer_get(p, "peer_id", "")
    pname = _peer_get(p, "peer_display", "")
    pqq = _peer_get(p, "peer_qq", "")
    pcall = _peer_get(p, "peer_call", "")
    pabs = _peer_get(p, "peer_absent", pcall)
    pforbid = _peer_get(p, "peer_forbid", "")

    core_lines = []
    for it in p.get("hard_rules") or []:
        t = _item_text(it)
        if t:
            t = re.sub(r"^\d+\.\s*", "", t)
            core_lines.append(f"- {t}")

    id_lines = []
    for it in p.get("identity") or []:
        k = (it.get("key") or "").strip()
        v = _strip_note(it.get("value") or "")
        if not v and not k:
            continue
        if k == "name":
            id_lines.append(f"- 全名：{v}")
            continue
        if k:
            label = {
                "called_as": "称呼",
                "call_peer": "称同伴",
                "look": "外貌",
                "birthday": "生日",
                "live": "现居",
                "history": "经历",
                "family": "家庭",
                "family_policy": "家庭与过去",
                "role_one_liner": "身份",
                "prefer": "偏好",
                "dislike": "厌恶",
            }.get(k, k)
            id_lines.append(f"- {label}：{v}")
        else:
            id_lines.append(f"- {v}")

    # personality：有 key 的按 trait 输出，否则扁平列表
    trait_blocks: List[str] = []
    flat_pers: List[str] = []
    for it in p.get("personality") or []:
        k = (it.get("key") or "").strip()
        v = (it.get("value") or "").strip()
        note = (it.get("note") or "").strip()
        if not v and not k:
            continue
        if k and ("weight=" in note or note in ("primary", "secondary", "flavor", "hidden") or "|" in note or v.startswith("行为规则")):
            weight = "secondary"
            if "primary" in note:
                weight = "primary"
            elif "flavor" in note:
                weight = "flavor"
            elif "hidden" in note:
                weight = "hidden"
            elif "|" in note:
                parts_n = note.split("|")
                if len(parts_n) > 1 and parts_n[1] in ("primary", "secondary", "flavor", "hidden"):
                    weight = parts_n[1]
            target_attr = ""
            mm = re.search(r"target=([^\s|]+)", note)
            if mm:
                target_attr = f' target="{_xml_esc(mm.group(1))}"'
            trait_blocks.append(
                f'<trait id="{_xml_esc(k)}" weight="{weight}"{target_attr}>\n{v}\n</trait>'
            )
        elif k and len(k) < 40 and " " not in k and "_" in k:
            # treat as trait id
            trait_blocks.append(
                f'<trait id="{_xml_esc(k)}" weight="secondary">\n{v}\n</trait>'
            )
        else:
            flat_pers.append(f"- {_item_text(it)}")

    pers_body = "\n".join(trait_blocks) if trait_blocks else "\n".join(flat_pers)

    call_items = list(p.get("address") or [])
    if not call_items:
        if pcall:
            call_items.append({"key": "", "value": f"当面/互聊/提及：固定「{pcall}」", "note": ""})
        if pabs:
            call_items.append({"key": "", "value": f"不在场：{pabs}", "note": ""})
        if pforbid:
            call_items.append({"key": "", "value": f"禁止称呼：{pforbid}", "note": ""})

    routing_items: List[str] = []
    seen_route: set = set()

    def _add_route(raw: str) -> None:
        t = _strip_note(raw)
        if not t or t in seen_route:
            return
        seen_route.add(t)
        routing_items.append(f"- {t}")

    for it in p.get("peer") or []:
        if not it.get("key"):
            _add_route(_item_text(it))
    for it in p.get("presence") or []:
        _add_route(_item_text(it))
    if not routing_items and pqq:
        _add_route(f"仅 QQ={pqq} 的消息视为同伴本人，触发同伴互聊逻辑")
        _add_route("其他任何QQ一律视为群友，即使自称同伴或昵称相似")

    beh_lines = []
    for it in p.get("behaviors") or []:
        t = _behavior_arrow(_item_text(it))
        if t:
            beh_lines.append(f"- {t}")

    goods = []
    for it in p.get("ex_ok") or []:
        t = _item_text(it)
        if t:
            goods.append(f"<correct>{_xml_esc(t)}</correct>")
    bads = []
    boundary_blob = ""
    for it in p.get("speech") or []:
        if (it.get("key") or it.get("note") or "") == "style_boundary":
            boundary_blob = (it.get("value") or "").strip()
            break
    for it in p.get("ex_bad") or []:
        t = _item_text(it)
        reason = (it.get("note") or "").strip()
        if t and reason == "边界禁止":
            continue  # 已含在 style_boundary
        if t:
            if reason:
                bads.append(
                    f'<incorrect reason="{_xml_esc(reason)}">{_xml_esc(t)}</incorrect>'
                )
            else:
                bads.append(f"<incorrect>{_xml_esc(t)}</incorrect>")

    # speech：按 note 重组嵌套；光谱整段回写
    speech_groups: Dict[str, List[str]] = {}
    speech_blobs: Dict[str, str] = {}
    for it in p.get("speech") or []:
        note = (it.get("note") or it.get("key") or "").strip() or "constraints"
        if note == "style_boundary":
            continue
        val = (it.get("value") or "").strip()
        if not val:
            continue
        if note in (
            "expression_spectrum",
            "diversity_rules",
            "format",
            "spectrum",
            "diversity",
            "forbid",
        ):
            speech_blobs[note] = val
        else:
            speech_groups.setdefault(note, []).append(f"- {val}")

    speech_parts: List[str] = ["<speech>"]
    for tag in (
        "format",
        "spectrum",
        "expression_spectrum",
        "diversity",
        "diversity_rules",
        "rhythm",
        "constraints",
        "forbid",
    ):
        if tag in speech_blobs:
            speech_parts.append(f"<{tag}>")
            speech_parts.append(speech_blobs[tag])
            speech_parts.append(f"</{tag}>")
            speech_parts.append("")
        elif tag in speech_groups:
            speech_parts.append(f"<{tag}>")
            speech_parts.append("\n".join(speech_groups[tag]))
            speech_parts.append(f"</{tag}>")
            speech_parts.append("")
    if len(speech_parts) == 1:
        speech_parts.append(_bullets(p.get("speech") or []))
    speech_parts.append("</speech>")

    parts = [
        f'<role id="{_xml_esc(sid)}" display="{_xml_esc(sname)}" qq="{_xml_esc(sqq)}">',
        "",
        '<core priority="absolute">',
        "\n".join(core_lines),
        "</core>",
        "",
        "<identity>",
        "\n".join(id_lines),
        "</identity>",
        "",
        "<family_context>",
        _bullets(p.get("family_context") or []),
        "</family_context>",
        "",
        "<personality>",
        pers_body,
        "</personality>",
        "",
        f'<peer id="{_xml_esc(pid)}" display="{_xml_esc(pname)}" qq="{_xml_esc(pqq)}">',
        "<routing>",
        "\n".join(routing_items),
        "</routing>",
        "<address>",
        _bullets(call_items),
        "</address>",
        "<relationship_rules>",
        _bullets(p.get("about_peer") or []),
        "</relationship_rules>",
        "</peer>",
        "",
        "<band>",
        _bullets(p.get("band_members") or []),
        "</band>",
        "",
        "<mygo>",
        _bullets(p.get("mygo") or []),
        "</mygo>",
        "",
        "\n".join(speech_parts),
        "",
        "<memory_expression>",
        _bullets(p.get("memory") or []),
        "</memory_expression>",
        "",
        "<image_response>",
        _bullets(p.get("image") or []),
        "</image_response>",
        "",
        "<behavior_map>",
        "\n".join(beh_lines),
        "</behavior_map>",
        "",
    ]
    if boundary_blob:
        parts.extend(["<style_boundary>", boundary_blob, "</style_boundary>", ""])
    elif goods or bads:
        parts.extend(
            ["<style_anchor>", "\n".join(goods + bads), "</style_anchor>", ""]
        )
    parts.append("</role>")
    text = "\n".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _parse_list_block(text: str) -> List[str]:
    out: List[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("- "):
            s = s[2:].strip()
        elif re.match(r"^\d+\.\s+", s):
            s = re.sub(r"^\d+\.\s+", "", s).strip()
        if s:
            out.append(s)
    return out


def _identity_line_to_fact(line: str) -> Dict[str, str]:
    s = line.strip()
    label_map = {
        "称呼": "called_as",
        "别人怎么叫": "called_as",
        "称同伴": "call_peer",
        "外表": "look",
        "外貌": "look",
        "生日": "birthday",
        "现居": "live",
        "经历": "history",
        "家庭": "family",
        "家庭与过去": "family_policy",
        "身份": "role_one_liner",
        "一句话身份": "role_one_liner",
        "全名": "name",
        "偏好": "prefer",
        "厌恶": "dislike",
    }
    for sep in ("：", ": ", ":"):
        if sep in s:
            left, right = s.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left in label_map:
                return {"key": label_map[left], "value": right, "note": left}
            if left and len(left) <= 16 and " " not in left:
                return {"key": re.sub(r"\W+", "_", left), "value": right, "note": left}
    return {"key": "", "value": s, "note": ""}


def _ingest_address_line(line: str, pack: Dict[str, Any], peer_facts: List[Dict[str, str]]) -> None:
    pack["address"].append({"key": "", "value": line, "note": ""})
    if ("禁用" in line or "禁止称呼" in line or "🚫" in line) and not any(
        it.get("key") == "peer_forbid" for it in peer_facts
    ):
        body_f = re.sub(r"^.*?(?:禁用|禁止称呼)[:：]?\s*", "", line)
        body_f = re.sub(r"^🚫\s*", "", body_f).strip()
        if body_f:
            peer_facts.append(
                {"key": "peer_forbid", "value": body_f.replace("/", " / "), "note": ""}
            )
    if ("当面" in line or "互聊" in line or "提及" in line) and not any(
        it.get("key") == "peer_call" for it in peer_facts
    ):
        mm = re.search(r"[「\"']([^」\"']+)[」\"']", line)
        if mm:
            peer_facts.append({"key": "peer_call", "value": mm.group(1), "note": ""})
    if "不在场" in line and not any(it.get("key") == "peer_absent" for it in peer_facts):
        mm = re.search(r"[「\"']([^」\"']+)[」\"']", line)
        val = mm.group(1) if mm else re.sub(r"^.*?[:：]\s*", "", line)
        if val:
            peer_facts.append({"key": "peer_absent", "value": val.strip(), "note": ""})


def parse_role_xml(text: str, module: str = "base") -> Dict[str, Any]:
    """解析 <role>…</role>（兼容 v1 name/good 与 v2 display/trait/style_anchor）。"""
    mid = (module or "base").strip() or "base"
    pack = empty_persona_pack(mid)
    raw = (text or "").strip()
    m = re.search(r"<role\b([^>]*)>([\s\S]*?)</role>", raw, re.I)
    if not m:
        return pack
    attrs_s, body = m.group(1), m.group(2)

    def attr(name: str, src: str = attrs_s) -> str:
        mm = re.search(rf'\b{name}\s*=\s*"([^"]*)"', src, re.I)
        if not mm:
            mm = re.search(rf"\b{name}\s*=\s*'([^']*)'", src, re.I)
        return (mm.group(1) if mm else "").strip()

    sid = attr("id")
    sname = attr("display") or attr("name")
    sqq = attr("qq")

    peer_m = re.search(r"<peer\b([^>]*)>([\s\S]*?)</peer>", body, re.I)
    pid = pname = pqq = ""
    peer_inner = ""
    if peer_m:
        pid = attr("id", peer_m.group(1))
        pname = attr("display", peer_m.group(1)) or attr("name", peer_m.group(1))
        pqq = attr("qq", peer_m.group(1))
        peer_inner = peer_m.group(2)

    peer_facts: List[Dict[str, str]] = []
    for k, v in (
        ("self_id", sid),
        ("self_display", sname),
        ("self_qq", sqq),
        ("peer_id", pid),
        ("peer_display", pname),
        ("peer_qq", pqq),
    ):
        if v:
            peer_facts.append({"key": k, "value": v, "note": ""})

    def section(tag: str, src: str = body) -> str:
        mm = re.search(rf"<{tag}\b[^>]*>([\s\S]*?)</{tag}>", src, re.I)
        return mm.group(1) if mm else ""

    for line in _parse_list_block(section("core")):
        pack["hard_rules"].append({"key": "", "value": line, "note": ""})

    if sname:
        pack["identity"].append({"key": "name", "value": sname, "note": "全名"})
    for line in _parse_list_block(section("identity")):
        pack["identity"].append(_identity_line_to_fact(line))

    for line in _parse_list_block(section("family_context")):
        pack["family_context"].append({"key": "", "value": line, "note": ""})

    # personality: trait 块优先，否则扁平列表
    pers = section("personality")
    traits = list(re.finditer(r"<trait\b([^>]*)>([\s\S]*?)</trait>", pers, re.I))
    if traits:
        for tm in traits:
            tid = attr("id", tm.group(1)) or "trait"
            weight = attr("weight", tm.group(1)) or "secondary"
            target = attr("target", tm.group(1))
            content = tm.group(2).strip()
            note = f"{tid}|{weight}"
            if target:
                note += f"|target={target}"
            pack["personality"].append(
                {"key": tid, "value": content, "note": note}
            )
    else:
        for line in _parse_list_block(pers):
            pack["personality"].append({"key": "", "value": line, "note": ""})

    # address: v2 <address> 或 v1 <call_rules>
    addr_body = section("address", peer_inner) or section("call_rules", peer_inner)
    for line in _parse_list_block(addr_body):
        _ingest_address_line(line, pack, peer_facts)

    rel_body = section("relationship_rules", peer_inner) or section(
        "relationship", peer_inner
    )
    for line in _parse_list_block(rel_body):
        pack["about_peer"].append({"key": "", "value": line, "note": ""})

    for line in _parse_list_block(section("routing", peer_inner)):
        pack["presence"].append({"key": "", "value": line, "note": "分流"})

    for line in _parse_list_block(section("band")):
        pack["band_members"].append({"key": "", "value": line, "note": ""})
    for line in _parse_list_block(section("mygo")):
        pack["mygo"].append({"key": "", "value": line, "note": ""})

    # speech: 紧凑 spectrum/diversity/forbid 或旧版 expression_spectrum…
    speech_body = section("speech")
    nested = False
    blob_tags = (
        "format",
        "spectrum",
        "diversity",
        "forbid",
        "expression_spectrum",
        "diversity_rules",
        "rhythm",
        "constraints",
        "opening_variants",
    )
    for sub in blob_tags:
        sub_txt = section(sub, speech_body)
        if not sub_txt:
            continue
        nested = True
        blob = sub_txt.strip()
        if sub in (
            "format",
            "spectrum",
            "diversity",
            "forbid",
            "expression_spectrum",
            "diversity_rules",
        ):
            # 紧凑单行/短段整存；旧列表式也整存以免拆碎
            if blob:
                pack["speech"].append({"key": sub, "value": blob, "note": sub})
        else:
            for line in _parse_list_block(sub_txt):
                pack["speech"].append({"key": "", "value": line, "note": sub})
    if not nested:
        for line in _parse_list_block(speech_body):
            pack["speech"].append({"key": "", "value": line, "note": ""})

    mem_body = section("memory_expression") or section("memory")
    for line in _parse_list_block(mem_body):
        pack["memory"].append({"key": "", "value": line, "note": ""})

    img_body = section("image_response") or section("image")
    for line in _parse_list_block(img_body):
        pack["image"].append({"key": "", "value": line, "note": ""})

    beh_body = section("behavior_map") or section("behavior_triggers")
    for line in _parse_list_block(beh_body):
        pack["behaviors"].append(
            {"key": "", "value": _behavior_from_arrow(line), "note": ""}
        )

    # style: v3 style_boundary（边界描述）/ v2 style_anchor / v1 style_examples
    boundary = section("style_boundary")
    if boundary:
        pack["speech"].append(
            {"key": "style_boundary", "value": boundary.strip(), "note": "style_boundary"}
        )
        for line in _parse_list_block(boundary):
            if line.startswith("禁止") or "禁止" in line[:6]:
                pack["ex_bad"].append({"key": "", "value": line, "note": "边界禁止"})
    style = section("style_anchor") or section("style_examples")
    for gm in re.finditer(r"<(?:correct|good)>([\s\S]*?)</(?:correct|good)>", style, re.I):
        t = gm.group(1).strip()
        if t:
            pack["ex_ok"].append({"key": "", "value": t, "note": ""})
    for bm in re.finditer(
        r'<(?:incorrect|bad)(?:\s+reason="([^"]*)")?\s*>([\s\S]*?)</(?:incorrect|bad)>',
        style,
        re.I,
    ):
        reason, t = (bm.group(1) or "").strip(), (bm.group(2) or "").strip()
        if t:
            pack["ex_bad"].append({"key": "", "value": t, "note": reason})

    for line in _parse_list_block(section("signals")):
        low = line.lower()
        for key in ("allow", "forbid", "tone"):
            if low.startswith(key + ":") or low.startswith(key + "："):
                body_s = line.split(":", 1)[-1] if ":" in line else line.split("：", 1)[-1]
                for piece in re.split(r"\s*/\s*", body_s.strip()):
                    piece = piece.strip()
                    if not piece:
                        continue
                    note = ""
                    mm = re.match(r"^([^\(]+)\((.+)\)$", piece)
                    if mm:
                        piece, note = mm.group(1).strip(), mm.group(2).strip()
                    pack[key].append({"key": "", "value": piece, "note": note})

    if not any(it.get("key") == "peer_call" for it in peer_facts):
        for it in pack.get("address") or []:
            mm = re.search(r"固定[「\"']([^」\"']+)[」\"']", it.get("value") or "")
            if mm:
                peer_facts.append({"key": "peer_call", "value": mm.group(1), "note": ""})
                break
    pack["peer"] = peer_facts
    return pack
