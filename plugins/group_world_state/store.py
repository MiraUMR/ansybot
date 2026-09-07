from __future__ import annotations

import re
import threading
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

CST = timezone(timedelta(hours=8))
KEY_RE = re.compile(r"^[a-zA-Z0-9_\u4e00-\u9fff]{1,40}$")
SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")

DEFAULT_EMPTY = {
    "anon": "（尚无额外长期设定。按默认人设相处：喜欢素世，彼此在意，尚未正式说破；告白与交往均可自然发生。）",
    "soyo": "（尚无额外长期设定。按默认人设相处：喜欢爱音，彼此在意，尚未正式说破；被告白时可以接受，不必永远推开。）",
}


def now_iso() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def normalize_key(key: str) -> str:
    key = (key or "").strip().replace(" ", "_").replace("-", "_")
    return key.lower()


def scope_id(
    character: Optional[str],
    group_id: Optional[str],
    user_id: Optional[str] = None,
) -> str:
    char = (character or "anon").strip() or "anon"
    if group_id:
        return f"{char}/{group_id}"
    if user_id:
        return f"{char}/c2c_{user_id}"
    return f"{char}/unknown"


def empty_text_for(scope: str) -> str:
    char = (scope or "").split("/", 1)[0] or "anon"
    return DEFAULT_EMPTY.get(char) or DEFAULT_EMPTY["anon"]


class WorldStateStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        defaults = {
            "admin_ids": [],
            "max_facts_per_group": 40,
            "max_text_length": 300,
        }
        path = self.root / "_config.yaml"
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            defaults.update({k: v for k, v in data.items() if v is not None})
        return defaults

    @property
    def admin_ids(self) -> List[str]:
        return [str(x) for x in (self._config.get("admin_ids") or [])]

    @property
    def max_facts(self) -> int:
        return int(self._config.get("max_facts_per_group") or 40)

    @property
    def max_text_length(self) -> int:
        return int(self._config.get("max_text_length") or 300)

    def can_edit(self, user_id: Optional[str]) -> bool:
        admins = self.admin_ids
        if not admins:
            return True
        return str(user_id or "") in admins

    def _path_for(self, scope: str) -> Path:
        raw = (scope or "unknown").replace("\\", "/")
        if "/" in raw:
            char, gid = raw.split("/", 1)
        else:
            # legacy flat file: treat as anon/<gid>
            char, gid = "anon", raw
        char_safe = SAFE_ID_RE.sub("_", char)[:40] or "anon"
        gid_safe = SAFE_ID_RE.sub("_", gid)[:80] or "unknown"
        if gid_safe.startswith("_"):
            gid_safe = "g" + gid_safe
        folder = self.root / char_safe
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{gid_safe}.yaml"

    def _read(self, scope: str) -> Dict[str, Any]:
        path = self._path_for(scope)
        group_key = scope.split("/", 1)[-1] if "/" in scope else scope
        if not path.exists():
            # migrate legacy flat yaml once
            legacy = self.root / f"{SAFE_ID_RE.sub('_', group_key)[:80]}.yaml"
            if legacy.exists() and not str(legacy.name).startswith("_"):
                try:
                    data = yaml.safe_load(legacy.read_text(encoding="utf-8")) or {}
                    data.setdefault("group_id", group_key)
                    data.setdefault("character", scope.split("/", 1)[0] if "/" in scope else "anon")
                    self._write({**data, "group_id": group_key})
                    return self._read(scope)
                except Exception:
                    pass
            return {
                "group_id": group_key,
                "group_name": "",
                "updated_at": "",
                "facts": [],
                "character": scope.split("/", 1)[0] if "/" in scope else "anon",
            }
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("group_id", group_key)
        data.setdefault("group_name", "")
        data.setdefault("updated_at", "")
        data.setdefault("facts", [])
        data.setdefault("character", scope.split("/", 1)[0] if "/" in scope else "anon")
        if not isinstance(data["facts"], list):
            data["facts"] = []
        return data

    def _write(self, doc: Dict[str, Any]) -> None:
        character = str(doc.get("character") or "anon")
        group_id = str(doc.get("group_id") or "unknown")
        path = self._path_for(f"{character}/{group_id}")
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        tmp.replace(path)

    def ensure_group(self, scope: str, group_name: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            doc = self._read(scope)
            changed = False
            if group_name and doc.get("group_name") != group_name:
                doc["group_name"] = group_name
                changed = True
            path = self._path_for(scope)
            if not path.exists():
                doc["updated_at"] = now_iso()
                changed = True
            if changed:
                self._write(doc)
            return deepcopy(doc)

    def get(self, scope: str) -> Dict[str, Any]:
        with self._lock:
            return deepcopy(self._read(scope))

    def list_groups(self) -> List[Dict[str, Any]]:
        items = []
        with self._lock:
            for path in sorted(self.root.glob("*/*.yaml")):
                if path.name.startswith("_"):
                    continue
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                facts = data.get("facts") or []
                items.append(
                    {
                        "group_id": data.get("group_id") or path.stem,
                        "group_name": data.get("group_name") or "",
                        "character": data.get("character") or path.parent.name,
                        "updated_at": data.get("updated_at") or "",
                        "fact_count": len(facts) if isinstance(facts, list) else 0,
                    }
                )
            # legacy flat files
            for path in sorted(self.root.glob("*.yaml")):
                if path.name.startswith("_"):
                    continue
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                facts = data.get("facts") or []
                items.append(
                    {
                        "group_id": data.get("group_id") or path.stem,
                        "group_name": data.get("group_name") or "",
                        "character": data.get("character") or "anon",
                        "updated_at": data.get("updated_at") or "",
                        "fact_count": len(facts) if isinstance(facts, list) else 0,
                    }
                )
        return items

    def render(self, scope: str) -> str:
        doc = self.get(scope)
        facts = doc.get("facts") or []
        if not facts:
            return empty_text_for(scope)
        lines = []
        for fact in facts:
            key = fact.get("key") or "note"
            text = (fact.get("text") or "").strip()
            if text:
                lines.append(f"- {key}: {text}")
        return "【本群已经发生、必须当作既定事实】\n" + "\n".join(lines)

    def set_fact(
        self,
        scope: str,
        key: str,
        text: str,
        source: str = "manual",
        group_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        key = normalize_key(key)
        if not KEY_RE.match(key):
            raise ValueError("键名只能用字母、数字、下划线或中文，最长 40 字")
        text = (text or "").strip()
        if not text:
            raise ValueError("内容不能为空")
        if len(text) > self.max_text_length:
            text = text[: self.max_text_length]
        with self._lock:
            doc = self._read(scope)
            if group_name:
                doc["group_name"] = group_name
            facts: List[Dict[str, Any]] = list(doc.get("facts") or [])
            found = False
            stamp = now_iso()
            for fact in facts:
                if fact.get("key") == key:
                    fact["text"] = text
                    fact["updated_at"] = stamp
                    fact["source"] = source
                    found = True
                    break
            if not found:
                facts.append(
                    {
                        "key": key,
                        "text": text,
                        "updated_at": stamp,
                        "source": source,
                    }
                )
            if len(facts) > self.max_facts:
                keep = [f for f in facts if f.get("key") == "relationship"]
                rest = [f for f in facts if f.get("key") != "relationship"]
                rest.sort(key=lambda f: f.get("updated_at") or "")
                overflow = len(keep) + len(rest) - self.max_facts
                if overflow > 0:
                    rest = rest[overflow:]
                facts = keep + rest
            doc["facts"] = facts
            doc["updated_at"] = stamp
            self._write(doc)
            return deepcopy(doc)

    def delete_fact(self, scope: str, key: str) -> Dict[str, Any]:
        key = normalize_key(key)
        with self._lock:
            doc = self._read(scope)
            before = len(doc.get("facts") or [])
            doc["facts"] = [f for f in (doc.get("facts") or []) if f.get("key") != key]
            if len(doc["facts"]) == before:
                raise KeyError(key)
            doc["updated_at"] = now_iso()
            self._write(doc)
            return deepcopy(doc)

    def replace_all(
        self,
        scope: str,
        facts: List[Dict[str, Any]],
        group_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        cleaned = []
        stamp = now_iso()
        for item in facts or []:
            key = normalize_key(str(item.get("key") or ""))
            text = str(item.get("text") or "").strip()
            if not KEY_RE.match(key) or not text:
                continue
            cleaned.append(
                {
                    "key": key,
                    "text": text[: self.max_text_length],
                    "updated_at": item.get("updated_at") or stamp,
                    "source": item.get("source") or "api",
                }
            )
        with self._lock:
            doc = self._read(scope)
            if group_name is not None:
                doc["group_name"] = group_name
            doc["facts"] = cleaned[: self.max_facts]
            doc["updated_at"] = stamp
            self._write(doc)
            return deepcopy(doc)

    def clear(self, scope: str) -> Dict[str, Any]:
        return self.replace_all(scope, [], group_name=None)
