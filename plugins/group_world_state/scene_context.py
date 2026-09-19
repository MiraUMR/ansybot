"""按角色+群隔离的临时场景缓冲（不进入对话记忆）。"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

import yaml

from .day_rollover import is_same_civil_day

CST = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


@dataclass
class SceneEntry:
    ts: str
    raw: str
    narration: str
    source: str  # template | llm


class SceneContextStore:
    """文件：data/world_state/_scene/{character}/{group_id}.yaml"""

    def __init__(self, root: Path, maxlen: int = 5):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.maxlen = max(1, int(maxlen or 5))
        self._lock = threading.RLock()
        self._cache: Dict[str, Deque[SceneEntry]] = {}

    def _path(self, character: str, group_id: str) -> Path:
        char = (character or "anon").strip() or "anon"
        gid = str(group_id or "unknown").strip() or "unknown"
        d = self.root / char
        d.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in gid)
        return d / f"{safe}.yaml"

    def _scope_key(self, character: str, group_id: str) -> str:
        return f"{(character or 'anon').strip()}/{(group_id or '').strip()}"

    def _load(self, character: str, group_id: str) -> Deque[SceneEntry]:
        key = self._scope_key(character, group_id)
        if key in self._cache:
            return self._cache[key]
        path = self._path(character, group_id)
        items: Deque[SceneEntry] = deque(maxlen=self.maxlen)
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                for raw in data.get("entries") or []:
                    if not isinstance(raw, dict):
                        continue
                    narr = str(raw.get("narration") or "").strip()
                    if not narr:
                        continue
                    items.append(
                        SceneEntry(
                            ts=str(raw.get("ts") or ""),
                            raw=str(raw.get("raw") or ""),
                            narration=narr,
                            source=str(raw.get("source") or "template"),
                        )
                    )
            except Exception:
                pass
        self._cache[key] = items
        return items

    def _save(self, character: str, group_id: str, items: Deque[SceneEntry]) -> None:
        path = self._path(character, group_id)
        payload = {
            "character": character,
            "group_id": str(group_id),
            "entries": [asdict(e) for e in list(items)],
        }
        path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def append(
        self,
        character: str,
        group_id: str,
        *,
        raw: str,
        narration: str,
        source: str = "template",
    ) -> None:
        narr = (narration or "").strip()
        if not narr or not group_id:
            return
        with self._lock:
            items = self._load(character, group_id)
            # maxlen deque: append drops left automatically if we recreate with maxlen
            if items.maxlen != self.maxlen:
                items = deque(items, maxlen=self.maxlen)
                self._cache[self._scope_key(character, group_id)] = items
            items.append(
                SceneEntry(
                    ts=_now_iso(),
                    raw=(raw or "").strip(),
                    narration=narr,
                    source=(source or "template").strip() or "template",
                )
            )
            items = self._today_only(items)
            self._cache[self._scope_key(character, group_id)] = items
            self._save(character, group_id, items)

    def _today_only(self, items: Deque[SceneEntry]) -> Deque[SceneEntry]:
        kept = [e for e in items if is_same_civil_day(e.ts)]
        out: Deque[SceneEntry] = deque(kept, maxlen=self.maxlen)
        return out

    def entries(self, character: str, group_id: str) -> List[SceneEntry]:
        with self._lock:
            items = self._load(character, group_id)
            pruned = self._today_only(items)
            key = self._scope_key(character, group_id)
            if len(pruned) != len(items):
                self._cache[key] = pruned
                self._save(character, group_id, pruned)
            else:
                self._cache[key] = pruned
            return list(pruned)

    def render_xml(self, character: str, group_id: str) -> str:
        rows = self.entries(character, group_id)
        if not rows:
            return ""
        lines = ["<current_scene>"]
        for e in rows:
            lines.append(f"- {e.narration}")
        lines.append("</current_scene>")
        return "\n".join(lines)

    def set_maxlen(self, maxlen: int) -> None:
        with self._lock:
            self.maxlen = max(1, int(maxlen or 5))
