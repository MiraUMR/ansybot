"""hobbies.yaml 读写：锁、校验、注释保留、字段转换。"""
from __future__ import annotations

import hashlib
import re
import secrets
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from filelock import FileLock
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .schemas import (
    BUILTIN_REPLY_STYLES,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ReplyStyleCreate,
    ReplyStyleOut,
    label_to_priority,
    normalize_reply_stance,
    priority_to_label,
)

PERSONA_ROOT = Path("data/persona")
ALLOWED = ("anon", "soyo")
IDLE_ID = "idle_ambient"
BUILTIN_STANCE_BASE = frozenset(BUILTIN_REPLY_STYLES.keys())

_yaml = YAML(typ="rt")
_yaml.preserve_quotes = True
_yaml.default_flow_style = False
_yaml.allow_unicode = True
_yaml.width = 4096

_cache_lock = threading.RLock()
_doc_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


class YamlStoreError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


def hobbies_path(persona: str) -> Path:
    return PERSONA_ROOT / persona / "hobbies.yaml"


def reply_styles_path(persona: str) -> Path:
    return PERSONA_ROOT / persona / "reply_styles.yaml"


def lock_path(persona: str) -> Path:
    path = hobbies_path(persona)
    return path.with_suffix(path.suffix + ".lock")


def reply_styles_lock_path(persona: str) -> Path:
    path = reply_styles_path(persona)
    return path.with_suffix(path.suffix + ".lock")


def assert_persona(persona: str) -> str:
    cid = (persona or "").strip()
    if cid not in ALLOWED:
        raise YamlStoreError(f"非法 persona: {persona!r}，仅允许 anon|soyo", 400)
    return cid


def _word_token(raw: Any) -> str:
    if isinstance(raw, dict):
        key = str(raw.get("key") or "").strip()
        value = str(raw.get("value") or raw.get("text") or "").strip()
        if key and value:
            return f"{key}={value}"
        return value or key
    return str(raw or "").strip()


def flatten_words(items: Any) -> List[str]:
    out: List[str] = []
    if not isinstance(items, list):
        return out
    for x in items:
        w = _word_token(x)
        if w and w not in out:
            out.append(w)
    return out


def split_trigger_words(words: List[str]) -> Tuple[List[str], List[str]]:
    keywords: List[str] = []
    aliases: List[str] = []
    for raw in words or []:
        w = str(raw or "").strip()
        if not w:
            continue
        if len(w) <= 2 or re.fullmatch(r"[A-Za-z]+", w):
            if w not in aliases:
                aliases.append(w)
        else:
            if w not in keywords:
                keywords.append(w)
    return keywords, aliases


def make_category_id(display_name: str) -> str:
    name = (display_name or "").strip()
    base = ""
    try:
        from pypinyin import lazy_pinyin  # type: ignore

        base = "_".join(lazy_pinyin(name)).lower()
    except Exception:
        base = re.sub(r"[^a-zA-Z0-9]+", "_", name).lower().strip("_")
        if not base or not re.search(r"[a-z]", base):
            digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
            base = f"cat_{digest}"
    base = re.sub(r"[^a-z0-9_]+", "_", base).strip("_") or "category"
    return f"{base}_{secrets.token_hex(2)}"


def category_to_api(cat: Dict[str, Any]) -> CategoryOut:
    keywords = flatten_words(cat.get("keywords"))
    aliases = flatten_words(cat.get("aliases"))
    trigger = list(keywords)
    for a in aliases:
        if a not in trigger:
            trigger.append(a)
    return CategoryOut(
        id=str(cat.get("id") or ""),
        display_name=str(cat.get("display_name") or cat.get("id") or ""),
        priority=priority_to_label(cat.get("priority")),
        trigger_words=trigger,
        reply_stance=str(cat.get("reply_stance") or "soft"),
        mode_hints=[str(x) for x in (cat.get("mode_hints") or []) if str(x).strip()],
        sample_lines=[str(x) for x in (cat.get("sample_lines") or []) if str(x).strip()],
        forbid_pivot=bool(cat.get("forbid_pivot")),
    )


def _empty_doc() -> Dict[str, Any]:
    return {
        "detector": {
            "mode": "hybrid",
            "embed_model": "text-embedding-v3",
            "embed_threshold": 0.45,
            "keyword_min_score": 8,
        },
        "categories": [],
    }


def _load_raw(persona: str) -> Dict[str, Any]:
    path = hobbies_path(persona)
    if not path.is_file():
        return _empty_doc()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = _yaml.load(f)
    except YAMLError as exc:
        raise YamlStoreError(f"YAML 语法错误: {exc}", 422) from exc
    except OSError as exc:
        raise YamlStoreError(f"读取失败: {exc}", 500) from exc
    if data is None:
        return _empty_doc()
    if not isinstance(data, dict):
        raise YamlStoreError("hobbies.yaml 根节点必须是 mapping", 422)
    if "detector" not in data or data["detector"] is None:
        data["detector"] = {}
    if "categories" not in data or data["categories"] is None:
        data["categories"] = []
    if not isinstance(data["categories"], list):
        raise YamlStoreError("categories 必须是列表", 422)
    return data


def _mtime(persona: str) -> float:
    path = hobbies_path(persona)
    try:
        return path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        return 0.0


def load_doc(persona: str, *, force: bool = False) -> Dict[str, Any]:
    cid = assert_persona(persona)
    mtime = _mtime(cid)
    with _cache_lock:
        cached = _doc_cache.get(cid)
        if not force and cached and cached[0] == mtime:
            return deepcopy(cached[1])
    data = _load_raw(cid)
    with _cache_lock:
        _doc_cache[cid] = (mtime, deepcopy(data))
    return deepcopy(data)


def invalidate(persona: Optional[str] = None) -> None:
    with _cache_lock:
        if persona:
            _doc_cache.pop(assert_persona(persona), None)
        else:
            _doc_cache.clear()
    try:
        from kirara_ai.plugins.group_world_state.topic_classify import invalidate_taxonomy

        invalidate_taxonomy(persona)
    except Exception:
        try:
            from group_world_state.topic_classify import invalidate_taxonomy  # type: ignore

            invalidate_taxonomy(persona)
        except Exception:
            pass


def _validate_roundtrip(text: str) -> None:
    try:
        parsed = _yaml.load(text)
    except YAMLError as exc:
        raise YamlStoreError(f"YAML 写入后语法校验失败: {exc}", 422) from exc
    if not isinstance(parsed, dict):
        raise YamlStoreError("YAML 写入后根节点无效", 422)
    if "categories" in parsed and parsed["categories"] is not None:
        if not isinstance(parsed["categories"], list):
            raise YamlStoreError("YAML 写入后 categories 无效", 422)


def save_doc(persona: str, doc: Dict[str, Any]) -> None:
    cid = assert_persona(persona)
    path = hobbies_path(cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.read_bytes() if path.is_file() else None
    lock = FileLock(str(lock_path(cid)), timeout=10)
    try:
        with lock:
            from io import StringIO

            buf = StringIO()
            _yaml.dump(doc, buf)
            text = buf.getvalue()
            _validate_roundtrip(text)
            tmp = path.with_suffix(".yaml.tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
    except YamlStoreError:
        if backup is not None:
            path.write_bytes(backup)
        elif path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
        raise
    except Exception as exc:
        if backup is not None:
            path.write_bytes(backup)
        raise YamlStoreError(f"写入失败: {exc}", 500) from exc
    invalidate(cid)


def list_categories(persona: str) -> List[CategoryOut]:
    doc = load_doc(persona)
    return [category_to_api(c) for c in (doc.get("categories") or []) if isinstance(c, dict)]


def get_category(persona: str, category_id: str) -> Dict[str, Any]:
    doc = load_doc(persona)
    for cat in doc.get("categories") or []:
        if isinstance(cat, dict) and str(cat.get("id")) == category_id:
            return cat
    raise YamlStoreError(f"分类不存在: {category_id}", 404)


def create_category(persona: str, body: CategoryCreate) -> CategoryOut:
    cid = assert_persona(persona)
    doc = load_doc(cid, force=True)
    cats = list(doc.get("categories") or [])
    new_id = make_category_id(body.display_name)
    existing = {str(c.get("id")) for c in cats if isinstance(c, dict)}
    while new_id in existing:
        new_id = make_category_id(body.display_name)
    try:
        priority = label_to_priority(body.priority)
    except ValueError as exc:
        raise YamlStoreError(str(exc), 400) from exc
    keywords, aliases = split_trigger_words(body.trigger_words)
    row = {
        "id": new_id,
        "display_name": body.display_name,
        "priority": priority,
        "keywords": keywords,
        "aliases": aliases,
        "reply_stance": body.reply_stance,
        "mode_hints": list(body.mode_hints or []),
        "sample_lines": list(body.sample_lines or []),
        "forbid_pivot": bool(body.forbid_pivot),
    }
    cats.append(row)
    doc["categories"] = cats
    if "detector" not in doc or not doc["detector"]:
        doc["detector"] = _empty_doc()["detector"]
    save_doc(cid, doc)
    return category_to_api(row)


def update_category(persona: str, category_id: str, body: CategoryUpdate) -> CategoryOut:
    cid = assert_persona(persona)
    doc = load_doc(cid, force=True)
    cats = list(doc.get("categories") or [])
    idx = next(
        (i for i, c in enumerate(cats) if isinstance(c, dict) and str(c.get("id")) == category_id),
        -1,
    )
    if idx < 0:
        raise YamlStoreError(f"分类不存在: {category_id}", 404)
    cat = dict(cats[idx])
    data = body.model_dump(exclude_unset=True)
    if category_id == IDLE_ID:
        if "reply_stance" in data and data["reply_stance"] != cat.get("reply_stance"):
            raise YamlStoreError("idle_ambient 的 reply_stance 禁止修改", 409)
        if "id" in data:
            raise YamlStoreError("idle_ambient 的 id 禁止修改", 409)
    if "display_name" in data and data["display_name"] is not None:
        name = str(data["display_name"]).strip()
        if not name:
            raise YamlStoreError("display_name 不能为空", 400)
        cat["display_name"] = name
    if "priority" in data and data["priority"] is not None:
        try:
            cat["priority"] = label_to_priority(data["priority"])
        except ValueError as exc:
            raise YamlStoreError(str(exc), 400) from exc
    if "trigger_words" in data and data["trigger_words"] is not None:
        keywords, aliases = split_trigger_words(list(data["trigger_words"] or []))
        cat["keywords"] = keywords
        cat["aliases"] = aliases
    if "reply_stance" in data and data["reply_stance"] is not None:
        cat["reply_stance"] = data["reply_stance"]
    if "mode_hints" in data and data["mode_hints"] is not None:
        cat["mode_hints"] = list(data["mode_hints"] or [])
    if "sample_lines" in data and data["sample_lines"] is not None:
        cat["sample_lines"] = list(data["sample_lines"] or [])
    if "forbid_pivot" in data and data["forbid_pivot"] is not None:
        cat["forbid_pivot"] = bool(data["forbid_pivot"])
    cats[idx] = cat
    doc["categories"] = cats
    save_doc(cid, doc)
    return category_to_api(cat)


def delete_category(persona: str, category_id: str) -> None:
    cid = assert_persona(persona)
    if category_id == IDLE_ID:
        raise YamlStoreError("idle_ambient 禁止删除", 409)
    doc = load_doc(cid, force=True)
    cats = list(doc.get("categories") or [])
    idx = next(
        (i for i, c in enumerate(cats) if isinstance(c, dict) and str(c.get("id")) == category_id),
        -1,
    )
    if idx < 0:
        raise YamlStoreError(f"分类不存在: {category_id}", 404)
    if len(cats) - 1 < 1:
        raise YamlStoreError("删除后分类数不能小于 1", 400)
    cats.pop(idx)
    doc["categories"] = cats
    save_doc(cid, doc)


def get_detector_config(persona: str) -> Dict[str, Any]:
    doc = load_doc(persona)
    det = dict(doc.get("detector") or {})
    threshold = float(det.get("embed_threshold") if det.get("embed_threshold") is not None else 0.45)
    sensitivity = int(round(max(0.0, min(1.0, threshold)) * 100))
    return {
        "sensitivity": sensitivity,
        "embed_model": str(det.get("embed_model") or "text-embedding-v3"),
        "mode": str(det.get("mode") or "hybrid"),
    }


def update_detector_config(persona: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    cid = assert_persona(persona)
    doc = load_doc(cid, force=True)
    det = dict(doc.get("detector") or {})
    if "sensitivity" in patch and patch["sensitivity"] is not None:
        s = int(patch["sensitivity"])
        if s < 0 or s > 100:
            raise YamlStoreError("sensitivity 需在 0–100", 400)
        det["embed_threshold"] = round(s / 100.0, 4)
    if "embed_model" in patch and patch["embed_model"]:
        det["embed_model"] = str(patch["embed_model"]).strip()
    if "mode" in patch and patch["mode"]:
        mode = str(patch["mode"]).strip().lower()
        if mode not in ("hybrid", "keyword", "embed"):
            raise YamlStoreError("mode 仅允许 hybrid|keyword|embed", 400)
        det["mode"] = mode
    doc["detector"] = det
    save_doc(cid, doc)
    return get_detector_config(cid)


def export_yaml_bytes(persona: str) -> bytes:
    cid = assert_persona(persona)
    path = hobbies_path(cid)
    if not path.is_file():
        from io import StringIO

        buf = StringIO()
        _yaml.dump(_empty_doc(), buf)
        return buf.getvalue().encode("utf-8")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise YamlStoreError(f"导出失败: {exc}", 500) from exc


def _load_custom_reply_styles(persona: str) -> List[Dict[str, str]]:
    path = reply_styles_path(persona)
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = _yaml.load(f)
    except (YAMLError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("styles")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            sid = normalize_reply_stance(row.get("id"))
        except ValueError:
            continue
        if sid in BUILTIN_STANCE_BASE or sid in seen:
            continue
        label = str(row.get("label") or sid).strip() or sid
        base = str(row.get("base") or "soft").strip().lower()
        if base not in BUILTIN_STANCE_BASE:
            base = "soft"
        seen.add(sid)
        out.append({"id": sid, "label": label, "base": base})
    return out


def _save_custom_reply_styles(persona: str, styles: List[Dict[str, str]]) -> None:
    cid = assert_persona(persona)
    path = reply_styles_path(cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"styles": styles}
    lock = FileLock(str(reply_styles_lock_path(cid)), timeout=10)
    with lock:
        from io import StringIO

        buf = StringIO()
        _yaml.dump(doc, buf)
        text = buf.getvalue()
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)


def list_reply_styles(persona: str) -> List[ReplyStyleOut]:
    cid = assert_persona(persona)
    out: List[ReplyStyleOut] = [
        ReplyStyleOut(id=sid, label=label, builtin=True, base=sid)
        for sid, label in BUILTIN_REPLY_STYLES.items()
    ]
    for row in _load_custom_reply_styles(cid):
        out.append(
            ReplyStyleOut(
                id=row["id"],
                label=row["label"],
                builtin=False,
                base=row.get("base") or "soft",
            )
        )
    return out


def resolve_reply_stance_base(persona: str, stance: Any) -> str:
    """自定义风格映射到内置行为轨；未知 id 按 soft。"""
    try:
        sid = normalize_reply_stance(stance, default="soft")
    except ValueError:
        return "soft"
    if sid in BUILTIN_STANCE_BASE:
        return sid
    for row in _load_custom_reply_styles(persona):
        if row["id"] == sid:
            base = row.get("base") or "soft"
            return base if base in BUILTIN_STANCE_BASE else "soft"
    return "soft"


def create_reply_style(persona: str, body: ReplyStyleCreate) -> ReplyStyleOut:
    cid = assert_persona(persona)
    sid = body.id
    if sid in BUILTIN_STANCE_BASE:
        raise YamlStoreError(f"不能覆盖内置风格: {sid}", 409)
    customs = _load_custom_reply_styles(cid)
    if any(r["id"] == sid for r in customs):
        raise YamlStoreError(f"风格已存在: {sid}", 409)
    customs.append({"id": sid, "label": body.label, "base": body.base})
    _save_custom_reply_styles(cid, customs)
    return ReplyStyleOut(id=sid, label=body.label, builtin=False, base=body.base)


def delete_reply_style(persona: str, style_id: str) -> None:
    cid = assert_persona(persona)
    try:
        sid = normalize_reply_stance(style_id)
    except ValueError as exc:
        raise YamlStoreError(str(exc), 400) from exc
    if sid in BUILTIN_STANCE_BASE:
        raise YamlStoreError("内置风格不可删除", 409)
    customs = _load_custom_reply_styles(cid)
    nxt = [r for r in customs if r["id"] != sid]
    if len(nxt) == len(customs):
        raise YamlStoreError(f"风格不存在: {sid}", 404)
    # 仍被分类引用时禁止删
    for cat in list_categories(cid):
        if cat.reply_stance == sid:
            raise YamlStoreError(
                f"风格 {sid} 仍被场景「{cat.display_name}」使用，请先改场景再删",
                409,
            )
    _save_custom_reply_styles(cid, nxt)
