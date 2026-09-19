"""引导式故事模式：按群持久化的多 Bot 状态机。"""
from __future__ import annotations

import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from .characters import aliases, character_by_qq, get_character, load_characters
from .store import WorldStateStore, now_iso, scope_id

CST = timezone(timedelta(hours=8))
TRIGGERS_PATH = Path("data/persona/story_triggers.yaml")
_ID_ALIAS = {
    "aono": "anon",
    "anon": "anon",
    "anonrin": "anon",
    "soyo": "soyo",
    "soyorin": "soyo",
}

_lock = threading.RLock()
_trigger_cache: Optional[Dict[str, Any]] = None


def canonical_bot_id(raw: str) -> str:
    key = (raw or "").strip().lower()
    return _ID_ALIAS.get(key, key)


def _known_ids() -> List[str]:
    chars = load_characters().get("characters") or {}
    return [cid for cid in ("soyo", "anon") if cid in chars] or [
        c for c in chars.keys() if c != "host"
    ]


def load_story_triggers() -> Dict[str, Any]:
    global _trigger_cache
    if _trigger_cache is not None:
        return _trigger_cache
    data: Dict[str, Any] = {}
    if TRIGGERS_PATH.is_file():
        try:
            data = yaml.safe_load(TRIGGERS_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    cfg = dict(data.get("story_triggers") or data or {})
    cfg.setdefault(
        "start_keywords",
        ["开始故事", "故事开始", "进入故事"],
    )
    cfg.setdefault(
        "start_scenes",
        ["逛庙会", "去逛庙会", "夏日祭典", "夏日祭", "一起去看live", "去看live", "看live"],
    )
    cfg.setdefault("end_tokens", ["end", "结束", "stop"])
    cfg.setdefault("start_patterns", [])
    cfg.setdefault("end_commands", [])
    cfg.setdefault("guide_prefix", "@{bot_name}")
    _trigger_cache = cfg
    return cfg


def _mention_aliases(cid: str) -> List[str]:
    extra = {
        "anon": ["小爱音", "aono", "Aono"],
        "soyo": [],
    }
    names = list(aliases(cid)) + extra.get(cid, []) + [cid]
    display = str(get_character(cid).get("display") or "")
    if display:
        names.append(display)
    return [n for n in names if n]


def _alias_catalog() -> List[str]:
    names: List[str] = []
    for cid in _known_ids():
        names.extend(_mention_aliases(cid))
    names.sort(key=len, reverse=True)
    seen = set()
    out = []
    for n in names:
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def strip_bot_mentions(content: str) -> str:
    text = content or ""
    text = re.sub(r"\[CQ:at,[^\]]+\]", " ", text)
    names = _alias_catalog()
    if names:
        pat = "|".join(re.escape(n) for n in names)
        text = re.sub(rf"[@＠]\s*(?:{pat})", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def mentioned_ids_in_text(content: str) -> List[str]:
    """按出现顺序提取 @别名 点到的角色。"""
    text = content or ""
    found: List[str] = []
    seen = set()
    spans: List[tuple] = []
    for cid in _known_ids():
        for alias in _mention_aliases(cid):
            if not alias:
                continue
            for match in re.finditer(
                rf"[@＠]\s*{re.escape(alias)}", text, flags=re.IGNORECASE
            ):
                spans.append((match.start(), match.end(), cid))
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    occupied: List[tuple] = []
    for start, end, cid in spans:
        if any(start < oend and end > ostart for ostart, oend in occupied):
            continue
        occupied.append((start, end))
        if cid not in seen:
            seen.add(cid)
            found.append(cid)
    return found


def extract_at_qqs(user_msg: Any, content: str = "") -> List[str]:
    try:
        from .mentions import at_target_qqs

        if user_msg is not None:
            targets, _ = at_target_qqs(user_msg)
            if targets:
                return list(targets)
    except Exception:
        pass
    qqs: List[str] = []
    text = content or (getattr(user_msg, "content", None) or "")
    for match in re.finditer(r"\[CQ:at,[^\]]*qq=(\d+)[^\]]*\]", str(text), flags=re.IGNORECASE):
        qqs.append(match.group(1))
    raw = getattr(user_msg, "raw_message", None) if user_msg is not None else None
    segs: Any = []
    if isinstance(raw, dict):
        segs = raw.get("message") or raw.get("message_chain") or []
    elif raw is not None:
        segs = getattr(raw, "message", None) or []
    if isinstance(segs, list):
        for seg in segs:
            if isinstance(seg, dict) and str(seg.get("type") or "") in ("at", "mention"):
                data = seg.get("data") or {}
                qq = str(data.get("qq") or data.get("user_id") or "").strip()
                if qq and qq != "all":
                    qqs.append(qq)
            else:
                typ = str(getattr(seg, "type", "") or "")
                if typ in ("at", "mention"):
                    data = getattr(seg, "data", None) or {}
                    if isinstance(data, dict):
                        qq = str(data.get("qq") or data.get("user_id") or "").strip()
                    else:
                        qq = str(getattr(seg, "qq", "") or getattr(seg, "user_id", "") or "").strip()
                    if qq and qq != "all":
                        qqs.append(qq)
    for el in getattr(user_msg, "message_elements", None) or []:
        # OneBot 适配器把 @ 转成 AtElement(user_id=QQ)
        uid = str(getattr(el, "user_id", "") or "").strip()
        if uid and uid != "all":
            qqs.append(uid)
        target = getattr(el, "target", None)
        if target is None:
            continue
        qq = str(getattr(target, "user_id", "") or getattr(target, "id", "") or "").strip()
        if qq and qq != "all" and qq != "bot":
            qqs.append(qq)
    return qqs


def extract_participating_bots(
    content: str, user_msg: Any = None, extra_ids: Optional[Sequence[str]] = None
) -> List[str]:
    found: List[str] = []
    seen = set()

    def add(cid: Optional[str]) -> None:
        cid = canonical_bot_id(cid or "")
        if cid in _known_ids() and cid not in seen:
            seen.add(cid)
            found.append(cid)

    for qq in extract_at_qqs(user_msg, content):
        add(character_by_qq(qq))
    for cid in mentioned_ids_in_text(content):
        add(cid)
    for cid in extra_ids or []:
        add(cid)
    return found


def remaining_guide_text(content: str) -> str:
    return strip_bot_mentions(content)


def is_story_end_command(content: str) -> bool:
    rest = remaining_guide_text(content).strip().strip("。.!！?？~～")
    if not rest:
        return False
    tokens = [str(t).strip().lower() for t in (load_story_triggers().get("end_tokens") or [])]
    return rest.lower() in tokens


def is_story_start_command(content: str, mentioned_bots: Sequence[str]) -> bool:
    if not mentioned_bots:
        return False
    rest = remaining_guide_text(content)
    if not rest:
        return False
    cfg = load_story_triggers()
    needles = list(cfg.get("start_keywords") or []) + list(cfg.get("start_scenes") or [])
    return any(n and n in rest for n in needles)


def extract_story_prompt(content: str) -> str:
    rest = remaining_guide_text(content)
    cfg = load_story_triggers()
    for kw in cfg.get("start_keywords") or []:
        rest = rest.replace(str(kw), " ")
    rest = re.sub(r"\s+", " ", rest).strip()
    return rest or remaining_guide_text(content) or "一段尚未命名的故事"


def resolve_story_speaker(
    session: "StorySession", mentioned_bots: Sequence[str]
) -> Optional[str]:
    participating = list(session.participating_bots or [])
    for cid in mentioned_bots:
        cid = canonical_bot_id(cid)
        if cid in participating:
            return cid
    if session.current_speaker and session.current_speaker in participating:
        return session.current_speaker
    return participating[0] if participating else None


def other_bots_label(character: str, participating: Sequence[str]) -> str:
    others = [b for b in participating if b != character]
    if not others:
        return "（仅你一人）"
    names = []
    for cid in others:
        if character == "soyo" and cid == "anon":
            names.append("小爱音")
        elif character == "anon" and cid == "soyo":
            names.append("soyorin")
        else:
            names.append(str(get_character(cid).get("display") or cid))
    return "、".join(names)


def display_of(character: str) -> str:
    if character == "soyo":
        return "长崎素世"
    if character == "anon":
        return "千早爱音"
    return str(get_character(character).get("display") or character)


@dataclass
class StorySession:
    initiator_qq: str
    group_id: str
    story_prompt: str
    participating_bots: List[str]
    turn_count: int = 0
    memory_points: List[str] = field(default_factory=list)
    active: bool = True
    current_speaker: Optional[str] = None

    @property
    def initiator(self) -> tuple:
        return (self.initiator_qq, self.group_id)

    def to_doc(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_doc(cls, doc: Dict[str, Any]) -> "StorySession":
        bots = [canonical_bot_id(b) for b in (doc.get("participating_bots") or [])]
        bots = [b for b in bots if b]
        return cls(
            initiator_qq=str(doc.get("initiator_qq") or ""),
            group_id=str(doc.get("group_id") or ""),
            story_prompt=str(doc.get("story_prompt") or ""),
            participating_bots=bots,
            turn_count=int(doc.get("turn_count") or 0),
            memory_points=[str(x).strip() for x in (doc.get("memory_points") or []) if str(x).strip()],
            active=bool(doc.get("active", True)),
            current_speaker=(str(doc.get("current_speaker") or "").strip() or None),
        )


@dataclass
class StoryRoute:
    action: str  # none | discard | start | turn | end
    speaker: Optional[str] = None
    session: Optional[StorySession] = None
    guide_text: str = ""
    persist: bool = False
    finalize: bool = False


def route_story(
    *,
    character: str,
    sender_qq: str,
    group_id: str,
    content: str,
    mentioned_bots: Sequence[str],
    session: Optional[StorySession],
    sender_is_participating_bot: bool = False,
) -> StoryRoute:
    character = canonical_bot_id(character)
    sender_qq = str(sender_qq or "").strip()
    mentioned = [canonical_bot_id(b) for b in mentioned_bots if canonical_bot_id(b)]
    guide = remaining_guide_text(content)

    if is_story_end_command(content):
        if session and session.active and sender_qq == session.initiator_qq:
            speaker = resolve_story_speaker(session, mentioned) or (
                character if character in session.participating_bots else None
            )
            if speaker != character:
                return StoryRoute(action="discard", speaker=speaker, session=session)
            return StoryRoute(
                action="end",
                speaker=character,
                session=session,
                guide_text=guide,
                persist=True,
                finalize=True,
            )
        if session and session.active:
            return StoryRoute(action="discard", session=session)
        return StoryRoute(action="none")

    if session and session.active:
        if sender_is_participating_bot:
            return StoryRoute(action="discard", session=session)
        if sender_qq != session.initiator_qq:
            return StoryRoute(action="discard", session=session)
        if not mentioned:
            return StoryRoute(action="discard", session=session)
        speaker = resolve_story_speaker(session, mentioned)
        if speaker != character:
            return StoryRoute(action="discard", speaker=speaker, session=session)
        return StoryRoute(
            action="turn",
            speaker=character,
            session=session,
            guide_text=guide,
            persist=True,
        )

    if is_story_start_command(content, mentioned):
        bots = list(mentioned)
        if not bots:
            return StoryRoute(action="none")
        new_session = StorySession(
            initiator_qq=sender_qq,
            group_id=str(group_id or ""),
            story_prompt=extract_story_prompt(content),
            participating_bots=bots,
            current_speaker=bots[0],
            active=True,
        )
        speaker = bots[0]
        if character not in bots:
            return StoryRoute(action="discard", speaker=speaker, session=new_session, persist=True)
        if character != speaker:
            return StoryRoute(action="discard", speaker=speaker, session=new_session, persist=True)
        return StoryRoute(
            action="start",
            speaker=character,
            session=new_session,
            guide_text=guide,
            persist=True,
        )

    return StoryRoute(action="none")


def merge_memory_points(points: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in points:
        text = re.sub(r"\s+", " ", (raw or "").strip())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def story_fact_key(session: StorySession, when: Optional[datetime] = None) -> str:
    stamp = (when or datetime.now(CST)).strftime("%Y%m%d%H%M")
    bots = "_".join(sorted(canonical_bot_id(b) for b in session.participating_bots))
    key = f"story_{stamp}_{bots}"
    return key[:40]


def finalize_story(
    session: StorySession,
    world_store: WorldStateStore,
    group_name: str = "",
) -> str:
    points = merge_memory_points(session.memory_points)
    summary = "；".join(points) if points else "故事已结束（无额外记忆点）。"
    key = story_fact_key(session)
    gid = session.group_id
    for bot in session.participating_bots:
        scope = scope_id(bot, gid, None)
        try:
            world_store.set_fact(
                scope,
                key,
                summary,
                source="story",
                group_name=group_name or None,
            )
        except Exception:
            # 键名碰撞时退回短键
            fallback = f"story_{key[-20:]}"[:40]
            world_store.set_fact(
                scope,
                fallback,
                summary,
                source="story",
                group_name=group_name or None,
            )
    session.active = False
    return summary


class StorySessionStore:
    """文件：data/world_state/_story/{group_id}.yaml"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, group_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(group_id))[:80]
        return self.root / f"{safe or 'unknown'}.yaml"

    def get(self, group_id: str) -> Optional[StorySession]:
        with _lock:
            path = self._path(group_id)
            if not path.exists():
                return None
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                return None
            if not data or not data.get("active"):
                return None
            session = StorySession.from_doc(data)
            session.group_id = str(group_id)
            return session

    def save(self, session: StorySession) -> None:
        with _lock:
            path = self._path(session.group_id)
            tmp = path.with_suffix(".yaml.tmp")
            doc = session.to_doc()
            doc["updated_at"] = now_iso()
            tmp.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
            tmp.replace(path)

    def clear(self, group_id: str) -> None:
        with _lock:
            path = self._path(group_id)
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass

    def append_memory(self, group_id: str, speaker: str, points: Sequence[str]) -> None:
        session = self.get(group_id)
        if not session or not session.active:
            return
        merged = list(session.memory_points)
        for p in merge_memory_points(points):
            if p not in merged:
                merged.append(p)
        session.memory_points = merged
        session.turn_count = int(session.turn_count or 0) + 1
        session.current_speaker = speaker
        self.save(session)
