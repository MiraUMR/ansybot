"""儿童模式：指定 QQ 按分钟间隔才读取并回复（含 @）。配置热加载。"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

CST = timezone(timedelta(hours=8))
CONFIG_PATH = Path("data/children_mode.yaml")
STATE_PATH = Path("data/world_state/_children_mode_state.yaml")

_lock = threading.RLock()
_config_mtime: float = -1.0
_config_cache: Dict[str, Any] = {}
_state_cache: Optional[Dict[str, Any]] = None


def _now() -> datetime:
    return datetime.now(CST)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _parse(iso: str) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _default_config() -> Dict[str, Any]:
    return {
        "enabled": True,
        "default_interval_minutes": 30,
        "users": [],
    }


def _normalize_qq(raw: Any) -> str:
    text = str(raw or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _load_config_unlocked() -> Dict[str, Any]:
    global _config_mtime, _config_cache
    try:
        mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.is_file() else -1.0
    except OSError:
        mtime = -1.0
    if mtime == _config_mtime and _config_cache:
        return _config_cache
    data = _default_config()
    if CONFIG_PATH.is_file():
        try:
            loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception:
            pass
    users: List[Dict[str, Any]] = []
    seen: set[str] = set()
    raw_users = data.get("users") or []
    if isinstance(raw_users, dict):
        raw_users = [
            {"qq": k, "interval_minutes": v} for k, v in raw_users.items()
        ]
    for item in raw_users:
        if isinstance(item, (str, int)):
            qq = _normalize_qq(item)
            minutes = int(data.get("default_interval_minutes") or 30)
        elif isinstance(item, dict):
            qq = _normalize_qq(item.get("qq") or item.get("id") or "")
            minutes = int(item.get("interval_minutes") or data.get("default_interval_minutes") or 30)
        else:
            continue
        if not qq or not qq.isdigit() or qq in seen:
            continue
        if minutes < 1:
            minutes = 1
        seen.add(qq)
        users.append({"qq": qq, "interval_minutes": minutes})
    data["enabled"] = bool(data.get("enabled", True))
    data["default_interval_minutes"] = int(data.get("default_interval_minutes") or 30) or 30
    data["users"] = users
    _config_cache = data
    _config_mtime = mtime
    return data


def load_config() -> Dict[str, Any]:
    with _lock:
        return dict(_load_config_unlocked())


def save_config(data: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "enabled": bool(data.get("enabled", True)),
        "default_interval_minutes": int(data.get("default_interval_minutes") or 30) or 30,
        "users": [],
    }
    seen: set[str] = set()
    for item in data.get("users") or []:
        if isinstance(item, dict):
            qq = _normalize_qq(item.get("qq"))
            minutes = int(item.get("interval_minutes") or payload["default_interval_minutes"])
        else:
            qq = _normalize_qq(item)
            minutes = payload["default_interval_minutes"]
        if not qq or not qq.isdigit() or qq in seen:
            continue
        if minutes < 1:
            minutes = 1
        seen.add(qq)
        payload["users"].append({"qq": qq, "interval_minutes": minutes})
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "# 儿童模式：名单内 QQ 必须间隔指定分钟才读取并回复（含 @）\n"
        "# 改完约几秒内生效，无需重启。\n\n"
        + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    )
    with _lock:
        CONFIG_PATH.write_text(text, encoding="utf-8")
        global _config_mtime, _config_cache
        _config_cache = payload
        try:
            _config_mtime = CONFIG_PATH.stat().st_mtime
        except OSError:
            _config_mtime = -1.0
    return payload


def _user_map(cfg: Dict[str, Any]) -> Dict[str, int]:
    return {
        str(u["qq"]): int(u["interval_minutes"])
        for u in (cfg.get("users") or [])
        if u.get("qq")
    }


def _load_state_unlocked() -> Dict[str, Any]:
    global _state_cache
    if _state_cache is not None:
        return _state_cache
    data: Dict[str, Any] = {"last": {}}
    if STATE_PATH.is_file():
        try:
            loaded = yaml.safe_load(STATE_PATH.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                data["last"] = dict(loaded.get("last") or {})
        except Exception:
            pass
    _state_cache = data
    return data


def _save_state_unlocked(data: Dict[str, Any]) -> None:
    global _state_cache
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _state_cache = data


def listed_interval(qq: str) -> Optional[int]:
    qq = _normalize_qq(qq)
    if not qq:
        return None
    with _lock:
        cfg = _load_config_unlocked()
        if not cfg.get("enabled"):
            return None
        return _user_map(cfg).get(qq)


def allowed(qq: str) -> bool:
    qq = _normalize_qq(qq)
    minutes = listed_interval(qq)
    if minutes is None:
        return True
    with _lock:
        last = _parse((_load_state_unlocked().get("last") or {}).get(qq) or "")
    if last is None:
        return True
    return _now() >= last + timedelta(minutes=minutes)


def remaining_seconds(qq: str) -> int:
    qq = _normalize_qq(qq)
    minutes = listed_interval(qq)
    if minutes is None:
        return 0
    with _lock:
        last = _parse((_load_state_unlocked().get("last") or {}).get(qq) or "")
    if last is None:
        return 0
    left = (last + timedelta(minutes=minutes)) - _now()
    return max(0, int(left.total_seconds()))


def record(qq: str) -> None:
    qq = _normalize_qq(qq)
    if listed_interval(qq) is None:
        return
    with _lock:
        data = _load_state_unlocked()
        last = dict(data.get("last") or {})
        last[qq] = _iso(_now())
        data = {"last": last}
        _save_state_unlocked(data)


def status_rows() -> List[Dict[str, Any]]:
    cfg = load_config()
    rows = []
    with _lock:
        last_map = dict((_load_state_unlocked().get("last") or {}))
    for user in cfg.get("users") or []:
        qq = str(user.get("qq") or "")
        minutes = int(user.get("interval_minutes") or cfg["default_interval_minutes"])
        last = last_map.get(qq) or ""
        left = remaining_seconds(qq) if cfg.get("enabled") else 0
        rows.append(
            {
                "qq": qq,
                "interval_minutes": minutes,
                "last_read": last,
                "remaining_seconds": left,
                "blocked": bool(cfg.get("enabled") and left > 0),
            }
        )
    return rows
