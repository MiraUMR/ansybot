"""按东八区自然日翻篇：昨天的闲聊/约定/做过的事不再当今天的话题。"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, List, Optional, Sequence, Tuple

CST = timezone(timedelta(hours=8))

STICKY_KEYS = {"relationship"}
STICKY_PREFIXES = ("nickname_",)
REL_PLOT_RE = re.compile(r"(告白|表白|交往|分手|复合|恋人|女朋友|在一起|求婚|结婚)")
DONE_RE = re.compile(
    r"(已经(去|吃|做|到|回|结束|完成)|去过了?|吃过了?|做过了?|"
    r"回来了|到家了|结束了|吃完|玩完|看完|做过)"
)
CROSS_DAY_PREFIX_RE = re.compile(r"^\s*\d+\s*天前")


def now_cst(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(CST)
    if now.tzinfo is None:
        return now.replace(tzinfo=CST)
    return now.astimezone(CST)


def civil_date(ts: Any = None, now: Optional[datetime] = None) -> date:
    if ts is None:
        return now_cst(now).date()
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.date()
        return ts.astimezone(CST).date()
    if isinstance(ts, date) and not isinstance(ts, datetime):
        return ts
    return parse_iso_date(str(ts)) or now_cst(now).date()


def parse_iso_date(raw: str) -> Optional[date]:
    s = (raw or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
        except ValueError:
            return None
    return None


def is_same_civil_day(ts: Any, now: Optional[datetime] = None) -> bool:
    if ts is None:
        return True
    return civil_date(ts, now) == now_cst(now).date()


def is_sticky_fact(key: str, text: str = "") -> bool:
    k = (key or "").strip().lower()
    if k in STICKY_KEYS or any(k.startswith(p) for p in STICKY_PREFIXES):
        return True
    if k == "plot" and REL_PLOT_RE.search(text or ""):
        return True
    return False


def looks_done(text: str) -> bool:
    return bool(DONE_RE.search(text or ""))


def classify_fact(
    fact: dict,
    now: Optional[datetime] = None,
) -> str:
    """sticky | open | closed"""
    key = str(fact.get("key") or "note")
    text = str(fact.get("text") or "")
    if is_sticky_fact(key, text):
        return "sticky"
    day = parse_iso_date(str(fact.get("updated_at") or ""))
    today = now_cst(now).date()
    if day is not None and day < today:
        return "closed"
    if looks_done(text):
        return "closed"
    return "open"


def split_facts(
    facts: Sequence[dict],
    now: Optional[datetime] = None,
) -> Tuple[List[dict], List[dict], List[dict]]:
    sticky: List[dict] = []
    open_now: List[dict] = []
    closed: List[dict] = []
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        if not str(fact.get("text") or "").strip():
            continue
        bucket = classify_fact(fact, now)
        if bucket == "sticky":
            sticky.append(fact)
        elif bucket == "open":
            open_now.append(fact)
        else:
            closed.append(fact)
    closed.sort(key=lambda f: str(f.get("updated_at") or ""), reverse=True)
    return sticky, open_now, closed[:4]


def render_fact_sections(
    facts: Sequence[dict],
    empty_fallback: str,
    now: Optional[datetime] = None,
) -> str:
    sticky, open_now, closed = split_facts(facts, now)
    parts: List[str] = []
    if sticky:
        parts.append(
            "【本群已经发生、必须当作既定事实】\n"
            + "\n".join(f"- {f.get('key')}: {(f.get('text') or '').strip()}" for f in sticky)
        )
    if open_now:
        parts.append(
            "【今天还在进行的约定】\n"
            + "\n".join(f"- {f.get('key')}: {(f.get('text') or '').strip()}" for f in open_now)
        )
    if closed:
        parts.append(
            "【已翻篇的近事（除非对方这句明确提起，否则不要续、不要约、不要当还没做完）】\n"
            + "\n".join(f"- {f.get('key')}: {(f.get('text') or '').strip()}" for f in closed)
        )
    if not parts:
        return empty_fallback
    if not sticky:
        parts.insert(0, empty_fallback)
    return "\n\n".join(parts)


def keep_today_entries(entries: Iterable[Any], now: Optional[datetime] = None) -> List[Any]:
    kept: List[Any] = []
    for entry in entries or []:
        ts = getattr(entry, "timestamp", None)
        if ts is None and isinstance(entry, dict):
            ts = entry.get("timestamp") or entry.get("ts")
        if is_same_civil_day(ts, now):
            kept.append(entry)
    return kept


def keep_today_memory(memory_content: Any, now: Optional[datetime] = None) -> Any:
    """工作流里已经分解成字符串时，丢掉「N天前」的跨日记录。"""
    if not isinstance(memory_content, list):
        return memory_content
    kept = []
    for item in memory_content:
        if isinstance(item, str) and CROSS_DAY_PREFIX_RE.match(item):
            continue
        kept.append(item)
    return kept
