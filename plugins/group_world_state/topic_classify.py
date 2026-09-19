"""爱好/话题语义分类 + 按命中注入爱好模块。

规格（Prompt A–F，agent 可执行）：
A) 每角色 hobbies.yaml：categories[] + detector{mode,embed_model,embed_threshold,keyword_min_score}
   category 字段：id/display_name/priority/keywords/aliases/reply_stance/mode_hints/
   sample_lines/forbid_pivot；必含 band_practice/fashion_live/food/peer_bond/idle_ambient/game_blocked
B) 检测：jieba 关键词快路径；不足时用 DashScope 兼容 /embeddings（text-embedding-v3）
   对「关键词+样本+爱好模块摘要」原型做余弦匹配；失败则回退关键词/idle
C) 爱好正文拆到 hobby_modules/{id}.md；base 禁止堆爱好长文；本轮只注入命中类全文
D) DialogueContext 分类后：user_prompt 追加【本轮话题锁】+【本轮爱好设定】（仅命中模块）
E) 人设网页「爱好设定」编辑 taxonomy+模块正文，替换原 base 爱好段
F) 验收：新闻三要素→idle 且不注入吉他模块；吉他排练→band 模块；原神→ignore；食物→food
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

logger = logging.getLogger("WorldState.Topic")

_WHAT_DOING_NEEDLES = (
    "在干嘛",
    "在干什么",
    "在做什么",
    "干嘛呢",
    "干什么呢",
    "做什么呢",
    "忙什么",
    "在干啥",
    "你在干",
    "在搞什么",
    "现在干嘛",
    "在忙啥",
    "做什么呀",
    "干嘛呀",
)


def _looks_asked_what_doing(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    return any(n in raw for n in _WHAT_DOING_NEEDLES)

PERSONA_ROOT = Path("data/persona")
CONFIG_PATH = Path("data/config.yaml")
TOPIC_MARKER_RE = re.compile(
    r"\[TOPIC(?:_LOCK)?[^\]]*\][\s\S]*?\bid:\s*(?P<id>[\w\-]+)[\s\S]*?\bstance:\s*(?P<stance>[\w\-]+)",
    re.I,
)
TOPIC_MARKER_LEGACY_RE = re.compile(
    r"\[TOPIC\s+id=(?P<id>[\w\-]+)\s+stance=(?P<stance>[\w\-]+)",
    re.I,
)

_SHELL_PATTERNS = [
    re.compile(r"空气里隐约有人说起"),
    re.compile(r"并不是在叫谁"),
    re.compile(r"\[环境描写\]"),
    re.compile(r"这类话"),
    re.compile(r"【当前环境】"),
    re.compile(r"不是某个具体"),
    re.compile(r"此刻的空气与声响"),
    re.compile(r"【当前场面】"),
]
_QUOTE_RE = re.compile(r"[「『\"“](.{1,80}?)[」』\"”]")

_doc_cache: Dict[str, Dict[str, Any]] = {}
_module_cache: Dict[str, str] = {}
_proto_cache: Dict[str, Dict[str, List[float]]] = {}
_cache_lock = threading.RLock()


@dataclass
class TopicHit:
    category_id: str
    score: float
    matched_terms: List[str] = field(default_factory=list)
    stance: str = "deflect"
    display_name: str = ""
    sample_lines: List[str] = field(default_factory=list)
    forbid_pivot_ids: List[str] = field(default_factory=list)
    detector: str = "keyword"  # keyword | embed | idle

    @property
    def is_idle(self) -> bool:
        return self.category_id == "idle_ambient"


def hobbies_path(character: str) -> Path:
    return PERSONA_ROOT / character / "hobbies.yaml"


def hobby_module_path(character: str, category_id: str) -> Path:
    return PERSONA_ROOT / character / "hobby_modules" / f"{category_id}.md"


def invalidate_taxonomy(character: Optional[str] = None) -> None:
    with _cache_lock:
        if character:
            cid = character.strip()
            _doc_cache.pop(cid, None)
            _proto_cache.pop(cid, None)
            prefix = f"{cid}:"
            for key in [k for k in _module_cache if k.startswith(prefix)]:
                _module_cache.pop(key, None)
        else:
            _doc_cache.clear()
            _proto_cache.clear()
            _module_cache.clear()


def load_hobbies_doc(character: str) -> Dict[str, Any]:
    cid = (character or "").strip() or "anon"
    with _cache_lock:
        cached = _doc_cache.get(cid)
    if cached is not None:
        return cached
    path = hobbies_path(cid)
    doc: Dict[str, Any] = {"detector": {}, "categories": []}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            doc = {
                "detector": dict(raw.get("detector") or {}),
                "categories": list(raw.get("categories") or []),
            }
    except FileNotFoundError:
        logger.warning(f"hobbies.yaml missing for {cid}")
    except Exception as exc:
        logger.warning(f"load hobbies.yaml {cid} failed: {exc}")
    with _cache_lock:
        _doc_cache[cid] = doc
    return doc


def load_taxonomy(character: str) -> List[Dict[str, Any]]:
    return list(load_hobbies_doc(character).get("categories") or [])


def save_hobbies_doc(character: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    cid = (character or "").strip()
    if cid not in ("soyo", "anon"):
        raise ValueError("未知角色")
    categories = list((doc or {}).get("categories") or [])
    detector = dict((doc or {}).get("detector") or {})
    body = yaml.safe_dump(
        {"detector": detector, "categories": categories},
        allow_unicode=True,
        sort_keys=False,
    )
    path = hobbies_path(cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)
    invalidate_taxonomy(cid)
    load_hobbies_doc(cid)
    return {"character": cid, "bytes": path.stat().st_size, "categories": len(categories)}


def load_hobby_module(character: str, category_id: str) -> str:
    cid = (character or "").strip() or "anon"
    hid = (category_id or "").strip()
    if not hid:
        return ""
    key = f"{cid}:{hid}"
    with _cache_lock:
        cached = _module_cache.get(key)
    if cached is not None:
        return cached
    path = hobby_module_path(cid, hid)
    try:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    except FileNotFoundError:
        text = ""
    except Exception as exc:
        logger.warning(f"load hobby module {key} failed: {exc}")
        text = ""
    with _cache_lock:
        _module_cache[key] = text
    return text


def save_hobby_module(character: str, category_id: str, text: str) -> Dict[str, Any]:
    cid = (character or "").strip()
    hid = (category_id or "").strip()
    if cid not in ("soyo", "anon"):
        raise ValueError("未知角色")
    if not hid or not re.match(r"^[\w\-]+$", hid):
        raise ValueError("非法爱好 id")
    body = (text or "").replace("\r\n", "\n").strip()
    if len(body) > 100_000:
        raise ValueError("爱好模块过长")
    path = hobby_module_path(cid, hid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(body + ("\n" if body else ""), encoding="utf-8")
    tmp.replace(path)
    invalidate_taxonomy(cid)
    load_hobby_module(cid, hid)
    return {
        "character": cid,
        "id": hid,
        "bytes": int(path.stat().st_size),
        "text": body,
    }


def list_hobby_ids(character: str) -> List[str]:
    return [str(c.get("id") or "") for c in load_taxonomy(character) if c.get("id")]


_PACK_BLOCK_RE = re.compile(
    r"\[HOBBY_PACK\]([\s\S]*?)\[/HOBBY_PACK\]", re.I
)
_NOTE_SEP = " :: "


def _split_policy_line(raw: str) -> List[str]:
    parts = re.split(r"[|,，、]", raw or "")
    return [p.strip() for p in parts if p.strip()]


def _parse_annotated(raw: str) -> Dict[str, str]:
    """解析 `value :: note` 或 `key=value :: note`。"""
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
        # fact 风格 key=value；行为规则含 IF 不拆
        left, right = s.split("=", 1)
        if left.strip() and " " not in left.strip():
            key, value = left.strip(), right.strip()
    return {"key": key, "value": value, "note": note}


def normalize_items(items: Any, as_fact: bool = False) -> List[Dict[str, str]]:
    """统一成 [{key,value,note}, ...]；兼容旧字符串列表。"""
    out: List[Dict[str, str]] = []
    if items is None:
        return out
    if isinstance(items, str):
        lines = (
            _split_policy_line(items)
            if ("|" in items or "，" in items or "," in items) and "\n" not in items
            else [ln.strip() for ln in items.replace("\r\n", "\n").split("\n") if ln.strip()]
        )
        items = lines
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
                parsed = _parse_annotated(value if not note else f"{value}{_NOTE_SEP}{note}")
                out.append(parsed)
            else:
                out.append({"key": key, "value": value, "note": note})
            continue
        parsed = _parse_annotated(str(x))
        if as_fact and not parsed["key"] and parsed["value"] and parsed["value"] != "(none)":
            # 纯字符串事实：整段当 value
            pass
        if parsed["value"] or parsed["key"]:
            if parsed["value"] == "(none)" and not parsed["note"]:
                continue
            out.append(parsed)
    return out


def item_values(items: Any) -> List[str]:
    """检测/匹配只用 value（或 key=value）。"""
    out: List[str] = []
    for it in normalize_items(items):
        if it.get("key") and it.get("value"):
            out.append(f"{it['key']}={it['value']}")
        elif it.get("value"):
            out.append(it["value"])
        elif it.get("key"):
            out.append(it["key"])
    return out


def _format_item_line(it: Dict[str, str], as_fact: bool = False) -> str:
    if as_fact and it.get("key"):
        body = f"{it['key']}={it.get('value') or ''}"
    else:
        body = it.get("value") or it.get("key") or ""
    note = (it.get("note") or "").strip()
    if note:
        return f"{body}{_NOTE_SEP}{note}"
    return body


def empty_hobby_pack(category_id: str = "", stance: str = "soft") -> Dict[str, Any]:
    return {
        "id": category_id or "",
        "stance": stance or "soft",
        "scope": "ON_HIT_ONLY",
        "facts": [],
        "allow": [],
        "forbid": [],
        "tone": [],
        "behaviors": [],
        "ex_ok": [],
        "ex_bad": [],
    }


def parse_hobby_pack(text: str) -> Dict[str, Any]:
    """从 [HOBBY_PACK] 抽出表单字段；条目为 {key,value,note}。"""
    raw = (text or "").replace("\r\n", "\n").strip()
    pack = empty_hobby_pack()
    if not raw:
        return pack
    m = _PACK_BLOCK_RE.search(raw)
    body = m.group(1).strip() if m else raw
    if not m and raw:
        pack["facts"] = normalize_items(
            [f"legacy={line}" for line in body.splitlines() if line.strip()],
            as_fact=True,
        )
        return pack

    section = ""
    policy_list_mode = ""  # allow/forbid/tone when using list form
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("id:"):
            pack["id"] = s.split(":", 1)[1].strip()
            section = ""
            policy_list_mode = ""
            continue
        if low.startswith("stance:"):
            pack["stance"] = s.split(":", 1)[1].strip() or "soft"
            section = ""
            policy_list_mode = ""
            continue
        if low.startswith("scope:"):
            pack["scope"] = s.split(":", 1)[1].strip() or "ON_HIT_ONLY"
            section = ""
            policy_list_mode = ""
            continue
        if low in ("facts:", "facts"):
            section = "facts"
            policy_list_mode = ""
            continue
        if low in ("policy:", "policy"):
            section = "policy"
            policy_list_mode = ""
            continue
        if low in ("behavior:", "behaviors:", "behavior", "behaviors"):
            section = "behaviors"
            policy_list_mode = ""
            continue
        if low in ("ex_ok:", "ex_ok"):
            section = "ex_ok"
            policy_list_mode = ""
            continue
        if low in ("ex_bad:", "ex_bad"):
            section = "ex_bad"
            policy_list_mode = ""
            continue
        if section == "policy":
            if low in ("allow:", "allow"):
                policy_list_mode = "allow"
                rest = s.split(":", 1)[1].strip() if ":" in s else ""
                if rest:
                    pack["allow"].extend(normalize_items(_split_policy_line(rest)))
                continue
            if low in ("forbid:", "forbid"):
                policy_list_mode = "forbid"
                rest = s.split(":", 1)[1].strip() if ":" in s else ""
                if rest:
                    pack["forbid"].extend(normalize_items(_split_policy_line(rest)))
                continue
            if low in ("tone:", "tone"):
                policy_list_mode = "tone"
                rest = s.split(":", 1)[1].strip() if ":" in s else ""
                if rest:
                    pack["tone"].extend(normalize_items(_split_policy_line(rest)))
                continue
            if low.startswith("allow:"):
                pack["allow"] = normalize_items(_split_policy_line(s.split(":", 1)[1]))
                policy_list_mode = ""
                continue
            if low.startswith("forbid:"):
                pack["forbid"] = normalize_items(_split_policy_line(s.split(":", 1)[1]))
                policy_list_mode = ""
                continue
            if low.startswith("tone:"):
                pack["tone"] = normalize_items(_split_policy_line(s.split(":", 1)[1]))
                policy_list_mode = ""
                continue
            item = s[2:].strip() if s.startswith("- ") else s
            if policy_list_mode and item and item not in ("-", "(none)"):
                pack[policy_list_mode].extend(normalize_items([item]))
            continue
        item = s[2:].strip() if s.startswith("- ") else s
        if not item or item in ("-", "(none)"):
            continue
        if section == "facts":
            pack["facts"].extend(normalize_items([item], as_fact=True))
        elif section == "behaviors":
            pack["behaviors"].extend(normalize_items([item]))
        elif section == "ex_ok":
            pack["ex_ok"].extend(normalize_items([item]))
        elif section == "ex_bad":
            pack["ex_bad"].extend(normalize_items([item]))
    return pack


def format_hobby_pack(pack: Dict[str, Any]) -> str:
    """表单字段 → [HOBBY_PACK]；每条可带 :: 备注。"""
    data = empty_hobby_pack()
    if isinstance(pack, dict):
        data["id"] = str(pack.get("id") or "").strip()
        data["stance"] = str(pack.get("stance") or "soft").strip() or "soft"
        data["scope"] = str(pack.get("scope") or "ON_HIT_ONLY").strip() or "ON_HIT_ONLY"
        data["facts"] = normalize_items(pack.get("facts"), as_fact=True)
        for key in ("allow", "forbid", "tone", "behaviors", "ex_ok", "ex_bad"):
            data[key] = normalize_items(pack.get(key))

    lines = [
        "[HOBBY_PACK]",
        f"id: {data['id'] or 'unknown'}",
        f"stance: {data['stance']}",
        f"scope: {data['scope']}",
        "",
        "facts:",
    ]
    if data["facts"]:
        lines.extend(f"- {_format_item_line(it, as_fact=True)}" for it in data["facts"])
    else:
        lines.append("- (none)")

    def emit_policy(title: str, items: List[Dict[str, str]]) -> None:
        lines.append(f"{title}:")
        if items:
            lines.extend(f"- {_format_item_line(it)}" for it in items)
        else:
            lines.append("- (none)")

    lines.append("")
    lines.append("policy:")
    emit_policy("ALLOW", data["allow"])
    emit_policy("FORBID", data["forbid"])
    emit_policy("TONE", data["tone"])
    lines.append("")
    lines.append("behavior:")
    if data["behaviors"]:
        lines.extend(f"- {_format_item_line(it)}" for it in data["behaviors"])
    else:
        lines.append("- IF hit THEN react_in_character")
    lines.append("")
    lines.append("ex_ok:")
    if data["ex_ok"]:
        lines.extend(f"- {_format_item_line(it)}" for it in data["ex_ok"])
    else:
        lines.append("- （暂无）")
    lines.append("ex_bad:")
    if data["ex_bad"]:
        lines.extend(f"- {_format_item_line(it)}" for it in data["ex_bad"])
    else:
        lines.append("- （暂无）")
    lines.append("[/HOBBY_PACK]")
    return "\n".join(lines) + "\n"


def pack_from_request(data: Dict[str, Any], category_id: str, stance: str = "") -> Dict[str, Any]:
    """合并 PUT 的 pack 或扁平字段。"""
    src = data.get("pack") if isinstance(data.get("pack"), dict) else data
    out = empty_hobby_pack(category_id, stance or "soft")
    if not isinstance(src, dict):
        return out
    out["id"] = str(src.get("id") or category_id or "").strip()
    if src.get("stance"):
        out["stance"] = str(src.get("stance")).strip()
    elif stance:
        out["stance"] = stance
    if src.get("scope"):
        out["scope"] = str(src.get("scope")).strip()
    out["facts"] = normalize_items(src.get("facts"), as_fact=True)
    for key in ("allow", "forbid", "tone", "behaviors", "ex_ok", "ex_bad"):
        if key in src and src[key] is not None:
            out[key] = normalize_items(src[key])
    return out


def _strip_shell(text: str) -> str:
    t = text or ""
    for pat in _SHELL_PATTERNS:
        t = pat.sub(" ", t)
    return t.strip()


def classify_source_text(text: str) -> str:
    raw = text or ""
    quotes = _QUOTE_RE.findall(raw)
    if quotes:
        return max(quotes, key=len).strip()
    return _strip_shell(raw)


def _tokenize(text: str) -> List[str]:
    t = (text or "").strip()
    if not t:
        return []
    try:
        import jieba  # type: ignore

        return [w.strip() for w in jieba.lcut(t) if w and w.strip()]
    except Exception:
        parts = re.findall(r"[\u4e00-\u9fff]{1,8}|[A-Za-z0-9_]+", t)
        return parts or [t]


def _category_score(
    cat: Dict[str, Any], text_lower: str, tokens: Sequence[str]
) -> Tuple[float, List[str]]:
    cid = str(cat.get("id") or "")
    if cid == "idle_ambient":
        return 0.0, []
    terms = item_values(cat.get("keywords")) + item_values(cat.get("aliases"))
    if not terms:
        return 0.0, []
    token_set = {tok.lower() for tok in tokens}
    matched: List[str] = []
    hits = 0
    for term in terms:
        tl = term.lower()
        if len(tl) <= 1:
            continue
        if tl in token_set or tl in text_lower:
            hits += 1
            matched.append(term)
            continue
        if any(tl in tok.lower() or tok.lower() in tl for tok in tokens if len(tok) > 1):
            hits += 1
            matched.append(term)
    if hits <= 0:
        return 0.0, []
    priority = int(cat.get("priority") or 3)
    return float(hits) * float(priority), matched


def _idle_category(cats: List[Dict[str, Any]]) -> Dict[str, Any]:
    for cat in cats:
        if str(cat.get("id") or "") == "idle_ambient":
            return cat
    return {
        "id": "idle_ambient",
        "display_name": "无爱好命中",
        "reply_stance": "deflect",
        "sample_lines": [],
        "priority": 1,
    }


def _forbid_pivot_ids(cats: List[Dict[str, Any]]) -> List[str]:
    return [
        str(cat.get("id"))
        for cat in cats
        if cat.get("forbid_pivot") and str(cat.get("id") or "") != "idle_ambient"
    ]


def _hit_from_cat(
    cat: Dict[str, Any],
    score: float,
    matched: List[str],
    cats: List[Dict[str, Any]],
    detector: str,
) -> TopicHit:
    return TopicHit(
        category_id=str(cat.get("id") or "unknown"),
        score=score,
        matched_terms=matched,
        stance=str(cat.get("reply_stance") or "soft"),
        display_name=str(cat.get("display_name") or cat.get("id") or ""),
        sample_lines=item_values(cat.get("sample_lines"))[:4],

        forbid_pivot_ids=_forbid_pivot_ids(cats),
        detector=detector,
    )


def _idle_hit(cats: List[Dict[str, Any]], detector: str = "idle") -> TopicHit:
    idle = _idle_category(cats)
    return TopicHit(
        category_id="idle_ambient",
        score=0.0,
        matched_terms=[],
        stance=str(idle.get("reply_stance") or "deflect"),
        display_name=str(idle.get("display_name") or "无爱好命中"),
        sample_lines=item_values(idle.get("sample_lines"))[:4],

        forbid_pivot_ids=_forbid_pivot_ids(cats),
        detector=detector,
    )


def _keyword_classify(character: str, source: str) -> TopicHit:
    cats = load_taxonomy(character)
    tokens = _tokenize(source)
    text_lower = source.lower()
    best: Optional[TopicHit] = None
    best_priority = -1
    for cat in cats:
        score, matched = _category_score(cat, text_lower, tokens)
        if score <= 0:
            continue
        priority = int(cat.get("priority") or 0)
        hit = _hit_from_cat(cat, score, matched, cats, "keyword")
        if best is None or hit.score > best.score or (
            hit.score == best.score and priority > best_priority
        ):
            best = hit
            best_priority = priority
    return best or _idle_hit(cats, "idle")


def _prototype_text(character: str, cat: Dict[str, Any]) -> str:
    cid = str(cat.get("id") or "")
    parts = [
        str(cat.get("display_name") or ""),
        " ".join(item_values(cat.get("keywords"))),
        " ".join(item_values(cat.get("aliases"))),
        " ".join(item_values(cat.get("sample_lines"))),
    ]
    mod = load_hobby_module(character, cid)
    if mod:
        parts.append(_strip_hobby_examples(mod)[:400])
    return "\n".join(p for p in parts if p).strip()


def _load_embed_backend() -> Tuple[str, str]:
    """从 data/config.yaml 取 DashScope 兼容 api_base + api_key。不写日志密钥。"""
    try:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return "", ""
    backends = ((raw.get("llms") or {}).get("api_backends") or [])
    for backend in backends:
        if not backend.get("enable", True):
            continue
        conf = backend.get("config") or {}
        base = str(conf.get("api_base") or "").rstrip("/")
        key = str(conf.get("api_key") or "").strip()
        name = str(backend.get("name") or "")
        if key and base and ("dashscope" in base.lower() or "dashscope" in name.lower()):
            return key, base
    for backend in backends:
        conf = backend.get("config") or {}
        key = str(conf.get("api_key") or "").strip()
        base = str(conf.get("api_base") or "").rstrip("/")
        if key and base:
            return key, base
    return "", ""


def _embed_texts(texts: List[str], model: str) -> List[List[float]]:
    api_key, api_base = _load_embed_backend()
    if not api_key or not api_base or not texts:
        return []
    url = api_base + "/embeddings"
    payload = json.dumps(
        {"model": model, "input": texts, "encoding_format": "float"},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        logger.warning(f"embed request failed: {type(exc).__name__}")
        return []
    items = data.get("data") or []
    items = sorted(items, key=lambda x: int(x.get("index") or 0))
    out: List[List[float]] = []
    for item in items:
        emb = item.get("embedding")
        if isinstance(emb, list) and emb:
            out.append([float(x) for x in emb])
    return out


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / math.sqrt(na * nb)


def _ensure_prototypes(character: str, model: str) -> Dict[str, List[float]]:
    cid = (character or "").strip() or "anon"
    with _cache_lock:
        cached = _proto_cache.get(cid)
    if cached is not None:
        return cached
    cats = [c for c in load_taxonomy(cid) if str(c.get("id") or "") != "idle_ambient"]
    texts = [_prototype_text(cid, c) or str(c.get("id")) for c in cats]
    vectors = _embed_texts(texts, model) if texts else []
    mapping: Dict[str, List[float]] = {}
    if len(vectors) == len(cats):
        for cat, vec in zip(cats, vectors):
            mapping[str(cat.get("id"))] = vec
    with _cache_lock:
        _proto_cache[cid] = mapping
    return mapping


def _embed_classify(character: str, source: str, threshold: float, model: str) -> Optional[TopicHit]:
    cats = load_taxonomy(character)
    by_id = {str(c.get("id")): c for c in cats}
    prototypes = _ensure_prototypes(character, model)
    if not prototypes:
        return None
    vecs = _embed_texts([source], model)
    if not vecs:
        return None
    query = vecs[0]
    best_id = ""
    best_sim = -1.0
    for hid, proto in prototypes.items():
        sim = _cosine(query, proto)
        if sim > best_sim:
            best_sim = sim
            best_id = hid
    if best_sim < threshold or best_id not in by_id:
        return None
    cat = by_id[best_id]
    return _hit_from_cat(
        cat,
        score=float(best_sim) * 100.0,
        matched=[f"embed:{best_sim:.3f}"],
        cats=cats,
        detector="embed",
    )


def classify_text(character: str, raw_text: str) -> TopicHit:
    """关键词快路径；不足时 embedding；仍无 → idle_ambient。"""
    cid = (character or "").strip() or "anon"
    doc = load_hobbies_doc(cid)
    detector = dict(doc.get("detector") or {})
    mode = str(detector.get("mode") or "hybrid").strip().lower()
    keyword_min = float(detector.get("keyword_min_score") or 8)
    embed_threshold = float(detector.get("embed_threshold") or 0.45)
    embed_model = str(detector.get("embed_model") or "text-embedding-v3")

    source = classify_source_text(raw_text)
    kw = _keyword_classify(cid, source)
    if mode == "keyword":
        return kw
    if kw.category_id != "idle_ambient" and kw.score >= keyword_min:
        return kw
    if mode in ("hybrid", "embed"):
        emb = _embed_classify(cid, source, embed_threshold, embed_model)
        if emb is not None:
            # game_blocked 关键词未命中但 embed 误吸时：若原文无游戏词且 kw 是 idle，仍用 embed
            return emb
    return kw if kw.category_id != "idle_ambient" else _idle_hit(load_taxonomy(cid), "idle")


# 语义分类 API 约定名
classify = classify_text


def parse_topic_from_prompt(prompt_blob: str) -> Optional[Tuple[str, str]]:
    m = TOPIC_MARKER_LEGACY_RE.search(prompt_blob or "")
    if m:
        return m.group("id"), m.group("stance")
    m = TOPIC_MARKER_RE.search(prompt_blob or "")
    if not m:
        return None
    return m.group("id"), m.group("stance")


_HOBBY_EX_RE = re.compile(
    r"\n(?:ex_ok|ex_bad):[\s\S]*?(?=\n\[/HOBBY_PACK\])",
    re.I,
)


def _strip_hobby_examples(body: str) -> str:
    """Prompt 里不放可抄的正/反例句，只留 policy/behavior。"""
    return _HOBBY_EX_RE.sub("\n", body or "").strip()


def hobby_module_inject(character: str, hit: TopicHit) -> str:
    """仅注入本轮命中爱好模块。idle 是缺省分流，不再塞爱好包，避免把话题收进茶/排练/想同伴。"""
    if hit.is_idle or hit.category_id == "idle_ambient":
        return ""
    body = load_hobby_module(character, hit.category_id)
    if not body:
        return ""
    body = _strip_hobby_examples(body)
    return (
        "[HOBBY_CONTEXT]\n"
        f"ACTIVE_ID: {hit.category_id}\n"
        f"DISPLAY: {hit.display_name or hit.category_id}\n"
        f"STANCE: {hit.stance}\n"
        "OTHER_PACKS: NOT_LOADED\n"
        "INSTRUCTION: obey [HOBBY_PACK] policy/behavior; ignore unloaded hobbies.\n"
        f"{body.strip()}\n"
        "[/HOBBY_CONTEXT]"
    ).strip()


def source_mentions_peer(character: str, text: str) -> bool:
    """EXTERNAL_TRIGGER 短路用：文本是否点到同伴（称呼/全名/别名），不要求 vocative 停顿。"""
    raw = (text or "").strip()
    if not raw:
        return False
    cid = (character or "").strip() or "anon"
    raw_l = raw.lower()
    # 硬编码兜底：覆盖「电话轰炸长崎素世」等非称呼句
    needles = (
        ["soyorin", "长崎素世", "素世世", "素世酱", "素世"]
        if cid == "anon"
        else ["小爱音", "千早爱音", "anon", "爱音酱", "爱音"]
    )
    for n in needles:
        if all(ord(c) < 128 for c in n):
            if n.lower() in raw_l:
                return True
        elif n in raw:
            return True

    try:
        from .characters import aliases, peer_id_for, peer_qq
        from .peer import alias_hit
    except Exception:
        return False
    pid = peer_id_for(cid)
    if not pid:
        return False
    pqq = str(peer_qq(cid) or "").strip()
    if pqq and pqq in raw:
        return True
    for name in sorted({a for a in (aliases(pid) or []) if a}, key=len, reverse=True):
        if alias_hit(raw, name):
            return True
    return False


_SCENE_CONTINUE_RE = re.compile(
    r"(你正好|你刚好|你看到|你看见|你望见|你说你|你告诉|你强行|你打开|你推开|"
    r"你走进|你走过去|你挤|挤了进去|闯进去|来借宿|借住|正在敲|敲你家门|敲你门|"
    r"站在门口|门开了|把门|开门的|看见开门|看到开门|"
    r"继续|接着|然后你|于是你)"
)


def is_directed_scene_continue(text: str) -> bool:
    """群友第二人称场面续写：应自由发挥接拍，禁止 idle 收束。"""
    raw = (text or "").strip()
    if not raw:
        return False
    # 去掉 @bot / @昵称 后再判
    raw = re.sub(r"[@＠]\S+\s*", "", raw).strip()
    if not raw:
        return False
    return bool(_SCENE_CONTINUE_RE.search(raw))


def scene_continue_lock_text(character: str, mode: str = "") -> str:
    call = "soyorin" if (character or "").strip() == "anon" else "小爱音"
    return (
        "[TOPIC_LOCK]\n"
        "id: scene_continue\n"
        "stance: engage\n"
        f"mode: {mode or 'direct'}\n"
        "mode_hint: scene_continue\n"
        "reply_stance: engage\n"
        "detector: directed_scene_continue\n"
        "ACTION: continue_scene_beat\n"
        "FORBID: idle_ambient|deflect|daily_close|收束结束|这样啊|知道了收口|priority4沉默\n"
        "HOBBY_PACK: NOT_LOADED\n"
        f"OUTPUT: 1-3 short in-scene lines; improvise next beat; if peer present call {call}; "
        "NO wrap-up; NO answer the narrator\n"
        "NOTE: 第二人称场面续写→自由发挥接下去，禁止收束到结束\n"
        "[/TOPIC_LOCK]"
    ).strip()


def force_scene_continue_override(
    character: str,
    *,
    mode: str = "",
    user_prompt: str = "",
    source_text: str = "",
) -> Optional[str]:
    """DIRECT@ 第二人称场面引导：跳过 idle/deflect，强制续写。"""
    prompt = user_prompt or ""
    if "[SYSTEM: EXTERNAL_TRIGGER]" not in prompt:
        return None
    if not is_directed_scene_continue(source_text):
        return None
    return scene_continue_lock_text(character, mode=mode)


def peer_interaction_lock_text(character: str, mode: str = "") -> str:
    call = "soyorin" if (character or "").strip() == "anon" else "小爱音"
    return (
        "[TOPIC_LOCK]\n"
        "id: peer_interaction\n"
        "stance: engage\n"
        f"mode: {mode or 'direct'}\n"
        "mode_hint: peer_interaction\n"
        "reply_stance: engage\n"
        "detector: external_trigger_shortcircuit\n"
        "ACTION: engage_peer_directed\n"
        "FORBID: idle_ambient|deflect|unload_topic|daily_close|收束结束\n"
        "HOBBY_PACK: NOT_LOADED\n"
        f"OUTPUT: 1-3 short WeChat lines to {call}; type3_ok; no_QA_to_crowd; continue_not_close\n"
        "NOTE: EXTERNAL_TRIGGER+peer mention → 忽略分类器 idle/deflect；禁止权衡规则冲突；禁止收束收口\n"
        "[/TOPIC_LOCK]"
    ).strip()


def peer_distress_lock_text(character: str, mode: str = "") -> str:
    call = "soyorin" if (character or "").strip() == "anon" else "小爱音"
    return (
        "[TOPIC_LOCK]\n"
        "id: peer_distress\n"
        "stance: engage\n"
        f"mode: {mode or 'direct'}\n"
        "mode_hint: peer_interaction\n"
        "reply_stance: engage\n"
        "detector: peer_distress_cue\n"
        "ACTION: chase_now\n"
        "FORBID: idle_ambient|activity_menu|deflect|daily_close|算了明天见|麻烦死了|鞋带借口\n"
        "HOBBY_PACK: NOT_LOADED\n"
        f"OUTPUT: 1-3 short lines going after {call} now; type3_ok; no_QA_to_crowd; no_wrap_up\n"
        "NOTE: 上文若有「算了明天见/鞋带没系/麻烦」是口误，这轮作废。立刻追，不要停。\n"
        "[/TOPIC_LOCK]"
    ).strip()


def chase_scene_lock_text(character: str, mode: str = "") -> str:
    """互聊续追：爱音是追的人，素世是跑开/被追的人。"""
    cid = (character or "").strip()
    if cid == "soyo":
        return (
            "[TOPIC_LOCK]\n"
            "id: chase_scene\n"
            "stance: engage\n"
            f"mode: {mode or 'peer'}\n"
            "mode_hint: peer_interaction\n"
            "reply_stance: engage\n"
            "detector: chase_in_flight\n"
            "ACTION: being_chased\n"
            "ROLE: 你是跑开/被追的那一方；小爱音在追你，不是你去追她\n"
            "FORBID: idle_ambient|deflect|也好收束|追到了|去追小爱音|activity_menu\n"
            "HOBBY_PACK: NOT_LOADED\n"
            "OUTPUT: 接住她「别跑/等等我」：停、回头、别扭、还在生气都可以；"
            "禁止说自己追到了；禁止闲聊收束成也好/吃的/时间\n"
            "NOTE: 不要客串成追人的那个。\n"
            "[/TOPIC_LOCK]"
        ).strip()
    return (
        "[TOPIC_LOCK]\n"
        "id: chase_scene\n"
        "stance: engage\n"
        f"mode: {mode or 'peer'}\n"
        "mode_hint: peer_interaction\n"
        "reply_stance: engage\n"
        "detector: chase_in_flight\n"
        "ACTION: still_chasing\n"
        "ROLE: 你在追 soyorin；对面的「你」就是她。鞋带散了是你自己的\n"
        "FORBID: idle_ambient|你比soyorin|把soyorin当第三人称|鞋带怪她|activity_menu\n"
        "HOBBY_PACK: NOT_LOADED\n"
        "OUTPUT: 对她说话（可用你）；禁止「你鞋带散着都比soyorin跑得快」这种把她说成旁边第三人\n"
        "NOTE: 不要跟旁边的人比谁跑得快。\n"
        "[/TOPIC_LOCK]"
    ).strip()


def force_peer_interaction_override(
    character: str,
    *,
    mode: str = "",
    user_prompt: str = "",
    source_text: str = "",
) -> Optional[str]:
    """DIRECT@ + 点名同伴：跳过 topic_classify，强制 peer_interaction/engage。"""
    prompt = user_prompt or ""
    is_trigger = "[SYSTEM: EXTERNAL_TRIGGER]" in prompt
    is_peer_chat = "Bot 互聊" in prompt
    if not is_trigger and not is_peer_chat:
        return None
    try:
        from .style_guard import looks_chase_in_flight, looks_peer_distress_cue

        if is_peer_chat and (
            looks_chase_in_flight(source_text) or looks_peer_distress_cue(source_text)
        ):
            return chase_scene_lock_text(character, mode=mode or "peer")
        if is_trigger and looks_peer_distress_cue(source_text):
            return peer_distress_lock_text(character, mode=mode)
    except Exception:
        pass
    if not is_trigger:
        return None
    if not source_mentions_peer(character, source_text):
        # 触发器已判定 TYPE3 时同样强制
        if "轻提开关=TYPE3" not in prompt and "必须选类型3" not in prompt:
            return None
    return peer_interaction_lock_text(character, mode=mode)


def topic_lock_text(
    character: str,
    hit: TopicHit,
    mode: str = "",
    source_text: str = "",
    group_id: str = "",
) -> str:
    cid = (character or "").strip() or "anon"
    mode = (mode or "").strip()
    if mode == "peer":
        try:
            from .style_guard import looks_chase_in_flight, looks_peer_distress_cue

            if looks_chase_in_flight(source_text) or looks_peer_distress_cue(
                source_text
            ):
                return chase_scene_lock_text(character, mode=mode)
        except Exception:
            pass
    matched = ",".join(hit.matched_terms[:6]) or "-"
    pivot = ",".join(hit.forbid_pivot_ids) or "primary_hobby"
    stance_raw = str(hit.stance or "soft")
    stance_base = stance_raw
    try:
        from kirara_ai.plugins.semantic_classify.yaml_store import resolve_reply_stance_base

        stance_base = resolve_reply_stance_base(cid, stance_raw)
    except Exception:
        try:
            from semantic_classify.yaml_store import resolve_reply_stance_base  # type: ignore

            stance_base = resolve_reply_stance_base(cid, stance_raw)
        except Exception:
            if stance_raw not in ("engage", "soft", "deflect", "ignore"):
                stance_base = "soft"
    samples = ""
    if (
        hit.sample_lines
        and stance_base in ("engage", "soft")
        and hit.category_id not in ("food", "aroma", "idle_ambient")
    ):
        samples = "SAMPLE: " + " | ".join(hit.sample_lines[:2]) + "\n"

    # 群友@（direct）：peer_bond 会把「提到同伴名字」演成偶遇/告白戏，必须卸载
    if mode == "direct" and hit.category_id == "peer_bond":
        return (
            "[TOPIC_LOCK]\n"
            "id: peer_bond_suppressed\n"
            "stance: deflect\n"
            f"mode: {mode}\n"
            f"detector: {hit.detector}\n"
            f"matched: {matched}\n"
            "ACTION: unload_peer_bond\n"
            "HOBBY_PACK: NOT_LOADED\n"
            "FORBID: dramatize_meet_cute|RP_scene_answer|FAQ|question_to_crowd|encyclopedia\n"
            "OUTPUT: 1-2 short self WeChat lines; no_QA; no_full_reunion_skit\n"
            "NOTE: 点到同伴名字≠要演完整偶遇/约会；称呼与轻提以 EXTERNAL_TRIGGER/P0 为准\n"
            "[/TOPIC_LOCK]"
        ).strip()

    if hit.category_id == "game_blocked" or stance_base == "ignore":
        rules = (
            "ACTION: deflect_or_skip\n"
            "FORBID: guide|gacha_advice|FAQ\n"
        )
    elif hit.is_idle or stance_base == "deflect":
        ban = (
            "FORBID_PIVOT: guitar_retune_drill|practice_schedule_talk"
            if cid == "anon"
            else "FORBID_PIVOT: tea_menu_lecture|rehearsal_schedule_filler"
        )
        env = (
            "ENV: not_a_question; react_mood_time_object_only; no_speaker_hunt\n"
            if mode in ("env", "env_peer", "scene")
            else ""
        )
        if mode == "direct":
            distress = False
            try:
                from .style_guard import looks_peer_distress_cue

                distress = looks_peer_distress_cue(source_text)
            except Exception:
                distress = False
            if distress:
                rules = (
                    "ACTION: chase_now\n"
                    f"{ban}\n"
                    "FORBID: activity_menu|算了明天见|麻烦死了|鞋带借口\n"
                    "OUTPUT: 1-3 short lines going after peer now; no_QA; no_wrap_up\n"
                )
            elif _looks_asked_what_doing(source_text):
                wx_off = ""
                try:
                    from .weather import weather_on_cooldown

                    if weather_on_cooldown(character, group_id, source_text):
                        wx_off = "FORBID: weather_talk|cold_hot_sky_filler\nACTION: skip_weather\n"
                except Exception:
                    wx_off = ""
                rules = (
                    "ACTION: answer_now_doing\n"
                    f"{ban}\n"
                    f"{wx_off}"
                    "OUTPUT: 1-3 short self lines; invent one small thing happening now; "
                    "no_fixed_activity_menu; no_default_tea_rehearsal_phone_or_thinking_of_peer; "
                    "no_QA; no_schedule; skip_weather unless asked\n"
                )
            else:
                wx_off = ""
                try:
                    from .weather import weather_on_cooldown

                    if weather_on_cooldown(character, group_id, source_text):
                        wx_off = "FORBID: weather_talk|cold_hot_sky_filler\nACTION: skip_weather\n"
                except Exception:
                    wx_off = ""
                rules = (
                    "ACTION: reply_this_line\n"
                    f"{ban}\n"
                    f"{wx_off}"
                    "OUTPUT: 1-3 short self lines answering this message; "
                    "do_not_invent_solo_activity; do_not_pick_up_old_topics_unless_this_line_is_about_them; "
                    "no_QA; no_schedule; skip_weather unless asked\n"
                )
        else:
            wx_off = ""
            try:
                from .weather import weather_on_cooldown

                if weather_on_cooldown(character, group_id, source_text):
                    wx_off = "FORBID: weather_talk|cold_hot_sky_filler\nACTION: skip_weather\n"
            except Exception:
                wx_off = ""
            rules = (
                f"ACTION: deflect\n"
                f"UNLOADED_PRIMARY: {pivot}\n"
                f"{ban}\n"
                f"{env}"
                f"{wx_off}"
                "OUTPUT: 1-2 short self lines; no_QA; no_schedule\n"
            )
    elif stance_base == "engage":
        rules = (
            "ACTION: engage_topic\n"
            "ALLOW: elaborate_in_character\n"
            "FORBID: encyclopedia|FAQ|bullet_list_answer\n"
        )
    else:
        rules = (
            "ACTION: soft_touch\n"
            "ALLOW: one_related_line\n"
            "FORBID: tutorial|long_explain\n"
        )

    lock = (
        f"[TOPIC_LOCK]\n"
        f"id: {hit.category_id}\n"
        f"stance: {stance_raw}\n"
        f"stance_base: {stance_base}\n"
        f"mode: {mode or '-'}\n"
        f"detector: {hit.detector}\n"
        f"matched: {matched}\n"
        f"{rules}"
        f"{samples}"
        f"[/TOPIC_LOCK]"
    )

    hobby = hobby_module_inject(cid, hit)
    if hobby:
        return (lock + "\n\n" + hobby).strip()
    return lock.strip()


def topic_critical_addon(
    character: str,
    hit: TopicHit,
    mode: str = "",
    group_id: str = "",
    source_text: str = "",
) -> str:
    mode = (mode or "").strip()
    if mode == "direct" and hit.category_id == "peer_bond":
        return (
            "[P0: TOPIC LOCK]\n"
            "id: peer_bond_suppressed\n"
            "ACTION: no_RP_scene_for_group_prompt\n"
            "FORBID: answer_as_skit|meet_cute_play|question_crowd\n"
            "HOBBY peer_bond: NOT_LOADED\n"
            "[/P0]"
        )
    return ""
