"""Story Mode V1.5 host manager: session CRUD, LLM turn, finalize."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from kirara_ai.im.manager import IMManager
from kirara_ai.im.message import IMMessage, TextMessage
from kirara_ai.im.sender import ChatSender, ChatType
from kirara_ai.ioc.container import DependencyContainer
from kirara_ai.llm.format.message import LLMChatMessage, LLMChatTextContent
from kirara_ai.llm.format.request import LLMChatRequest
from kirara_ai.llm.llm_manager import LLMManager
from kirara_ai.llm.llm_registry import LLMAbility
from kirara_ai.logger import get_logger

from . import story_db
from .parser import strip_memory_points
from .prompt_assembler import build_story_prompt
from .store import WorldStateStore, scope_id
from .story import load_story_triggers

logger = get_logger("StoryHost")
CST = timezone(timedelta(hours=8))
SETTINGS_PATH = Path("data/persona/story_settings.yaml")
HOST_IM = "qq_official_bot"

_settings_cache: Optional[Dict[str, Any]] = None


def load_story_settings() -> Dict[str, Any]:
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache
    data: Dict[str, Any] = {}
    if SETTINGS_PATH.is_file():
        try:
            data = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    data.setdefault("max_turns", 7)
    data.setdefault("public_base_url", "https://ansy.love/qqbot/backend-api")
    data.setdefault("public_api_prefix", "/qqbot/backend-api/api/story")
    data.setdefault("llm_model", "")
    data.setdefault(
        "fantasy_keywords",
        ["异世界", "奇幻", "做梦", "梦境", "fantasy", "冒险世界", "魔法", "穿越"],
    )
    data.setdefault("templates", {})
    _settings_cache = data
    return data


def public_api_prefix() -> str:
    return str(load_story_settings().get("public_api_prefix") or "/qqbot/backend-api/api/story").rstrip("/")


def hmac_secret() -> str:
    return (os.environ.get("STORY_HMAC_SECRET") or "dev-story-hmac-change-me").strip()


def sign_token(session_id: str, initiator_qq: str, group_id: str) -> str:
    payload = f"{session_id}:{initiator_qq}:{group_id}".encode("utf-8")
    return hmac.new(hmac_secret().encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_token(session_id: str, initiator_qq: str, group_id: str, token: str) -> bool:
    if not token:
        return False
    expected = sign_token(session_id, initiator_qq, group_id)
    return hmac.compare_digest(expected, str(token).strip())


def detect_scene_type(text: str) -> str:
    raw = text or ""
    keywords = list(load_story_settings().get("fantasy_keywords") or [])
    try:
        triggers = load_story_triggers()
        keywords.extend(triggers.get("fantasy_keywords") or [])
    except Exception:
        pass
    seen = set()
    for kw in keywords:
        k = str(kw or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        if k in raw:
            return "fantasy"
    return "daily"


def _now_iso() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _parse_json(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _tpl(key: str, **kwargs: Any) -> str:
    templates = load_story_settings().get("templates") or {}
    fmt = templates.get(key) or ""
    try:
        return str(fmt).format(**kwargs)
    except Exception:
        return str(fmt)


class StoryHostManager:
    def __init__(self, container: Optional[DependencyContainer] = None):
        self.container = container
        story_db.connect()

    def has_active_for_group(self, group_id: str) -> bool:
        row = story_db.fetchone(
            "SELECT session_id FROM story_sessions WHERE group_id=? AND status='ACTIVE' LIMIT 1",
            (str(group_id),),
        )
        return bool(row)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        row = story_db.fetchone(
            "SELECT * FROM story_sessions WHERE session_id=?",
            (session_id,),
        )
        if not row:
            return None
        row["participants"] = _parse_json(row.get("participants"), [])
        row["history_log"] = _parse_json(row.get("history_log"), [])
        row["recipient_meta"] = _parse_json(row.get("recipient_meta"), {})
        return row

    def get_active_by_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        row = story_db.fetchone(
            "SELECT session_id FROM story_sessions WHERE group_id=? AND status='ACTIVE' "
            "ORDER BY created_at DESC LIMIT 1",
            (str(group_id),),
        )
        if not row:
            return None
        return self.get_session(str(row["session_id"]))

    def create_session(
        self,
        group_id: str,
        initiator_qq: str,
        scene_desc: str,
        participants: Optional[List[str]] = None,
        recipient_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # one active session per group
        existing = self.get_active_by_group(group_id)
        if existing:
            self.finalize(str(existing["session_id"]), quiet=True)

        settings = load_story_settings()
        sid = str(uuid.uuid4())
        bots = participants or ["soyo", "anon"]
        scene_type = detect_scene_type(scene_desc)
        max_turns = int(settings.get("max_turns") or 7)
        story_db.execute(
            """
            INSERT INTO story_sessions (
                session_id, group_id, initiator_qq, status, scene_type, scene_desc,
                participants, turn_count, max_turns, history_log, recipient_meta,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'ACTIVE', ?, ?, ?, 0, ?, '[]', ?, ?, ?)
            """,
            (
                sid,
                str(group_id),
                str(initiator_qq),
                scene_type,
                (scene_desc or "").strip() or "日常场景",
                json.dumps(bots, ensure_ascii=False),
                max_turns,
                json.dumps(recipient_meta or {}, ensure_ascii=False),
                _now_iso(),
                _now_iso(),
            ),
        )
        session = self.get_session(sid)
        assert session is not None
        return session

    def form_url(self, session: Dict[str, Any]) -> str:
        settings = load_story_settings()
        base = str(settings.get("public_base_url") or "").rstrip("/")
        sid = session["session_id"]
        uid = session["initiator_qq"]
        gid = session["group_id"]
        token = sign_token(sid, uid, gid)
        return f"{base}/api/story/form?sid={sid}&uid={uid}&token={token}"

    def open_message(self, session: Dict[str, Any]) -> str:
        bots = "、".join(session.get("participants") or [])
        return _tpl(
            "open",
            scene_type=session.get("scene_type") or "daily",
            bots=bots or "soyo/anon",
            url=self.form_url(session),
        )

    def help_message(self) -> str:
        return _tpl("help") or "主持人：开始故事 / 结束"

    def _last_response(self, session: Dict[str, Any]) -> str:
        history = session.get("history_log") or []
        if not history:
            return ""
        last = history[-1] if isinstance(history[-1], dict) else {}
        return str(last.get("response") or "")

    def _call_llm(self, prompt: str) -> str:
        if self.container is None:
            raise RuntimeError("container required for LLM")
        manager: LLMManager = self.container.resolve(LLMManager)
        settings = load_story_settings()
        model_id = str(settings.get("llm_model") or "").strip()
        if not model_id:
            model_id = manager.get_llm_id_by_ability(LLMAbility.TextChat) or ""
        if not model_id:
            raise RuntimeError("no LLM model available")
        llm = manager.get_llm(model_id)
        if not llm:
            raise RuntimeError(f"LLM {model_id} not found")
        req = LLMChatRequest(
            messages=[
                LLMChatMessage(
                    role="system",
                    content=[LLMChatTextContent(text="You are a roleplay actor. Follow instructions.")],
                ),
                LLMChatMessage(
                    role="user",
                    content=[LLMChatTextContent(text=prompt)],
                ),
            ],
            model=model_id,
        )
        resp = llm.chat(req)
        chunks: List[str] = []
        if resp and resp.message:
            for part in resp.message.content or []:
                if isinstance(part, LLMChatTextContent) and part.text:
                    chunks.append(part.text)
        return "\n".join(chunks).strip()

    def process_turn(
        self,
        session_id: str,
        target_bot: str,
        action_prompt: str,
        send_to_group: bool = True,
    ) -> Dict[str, Any]:
        session = self.get_session(session_id)
        if not session or session.get("status") != "ACTIVE":
            raise ValueError("session not active")
        bot = (target_bot or "").strip().lower()
        if bot not in ("soyo", "anon"):
            raise ValueError("target_bot must be soyo or anon")
        participants = session.get("participants") or []
        if participants and bot not in participants:
            raise ValueError(f"{bot} not in participants")

        turn = int(session.get("turn_count") or 0) + 1
        max_turns = int(session.get("max_turns") or 7)
        prompt = build_story_prompt(
            bot,
            {
                "scene_desc": session.get("scene_desc") or "",
                "last_response": self._last_response(session),
            },
            action_prompt,
        )
        raw = self._call_llm(prompt)
        clean, memories = strip_memory_points(raw)
        if not clean:
            clean = raw.strip() or "……"

        history = list(session.get("history_log") or [])
        history.append(
            {
                "turn": turn,
                "bot": bot,
                "prompt": action_prompt,
                "response": clean,
                "memory": memories,
            }
        )
        story_db.execute(
            """
            UPDATE story_sessions
            SET turn_count=?, history_log=?, updated_at=?
            WHERE session_id=?
            """,
            (turn, json.dumps(history, ensure_ascii=False), _now_iso(), session_id),
        )
        session = self.get_session(session_id) or session
        narration = _tpl(
            "narration",
            n=turn,
            max=max_turns,
            scene=(session.get("scene_desc") or "")[:40],
        )
        display = {"soyo": "素世", "anon": "爱音"}.get(bot, bot)
        body = f"{narration}\n【{display}】\n{clean}"
        if turn >= max_turns:
            body += "\n\n" + _tpl("max_turns_hint", max=max_turns)
        else:
            body += "\n\n" + _tpl("turn_hint", n=turn, max=max_turns)

        if send_to_group:
            self.send_group_text(session, body)
        return {"session": session, "text": body, "memories": memories, "turn": turn}

    def finalize(self, session_id: str, quiet: bool = False) -> str:
        session = self.get_session(session_id)
        if not session:
            return ""
        history = session.get("history_log") or []
        points: List[str] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            for m in item.get("memory") or []:
                text = str(m or "").strip()
                if text and text not in points:
                    points.append(text)

        scene_type = (session.get("scene_type") or "daily").strip().lower()
        is_fantasy = scene_type == "fantasy"
        summary = "；".join(points) if points else "故事已结束（无额外记忆点）。"
        if is_fantasy:
            summary = f"[dream] {summary}"

        if self.container is not None:
            try:
                world: WorldStateStore = self.container.resolve(WorldStateStore)
            except Exception:
                world = WorldStateStore(Path("data/world_state"))
            stamp = datetime.now(CST).strftime("%Y%m%d%H%M")
            bots = "_".join(sorted(str(b) for b in (session.get("participants") or [])))
            if is_fantasy:
                key = f"dream_story_{stamp}_{bots}"[:40]
                source = "story_dream"
            else:
                key = f"story_{stamp}_{bots}"[:40]
                source = "story"
            gid = str(session.get("group_id") or "")
            for bot in session.get("participants") or []:
                scope = scope_id(str(bot), gid, None)
                try:
                    world.set_fact(scope, key, summary, source=source)
                except Exception as exc:
                    logger.warning(f"finalize set_fact failed bot={bot}: {exc}")
                    try:
                        fallback = ("dream_" if is_fantasy else "story_") + stamp[-8:]
                        world.set_fact(scope, fallback[:40], summary, source=source)
                    except Exception:
                        pass

        story_db.execute(
            "UPDATE story_sessions SET status='COMPLETED', updated_at=? WHERE session_id=?",
            (_now_iso(), session_id),
        )
        msg = _tpl("end") or "✅ 故事已完结。"
        if not quiet and session.get("status") == "ACTIVE":
            self.send_group_text(session, msg + (f"\n记忆摘要：{summary}" if points else ""))
        return summary

    def send_group_text(self, session: Dict[str, Any], text: str) -> None:
        if self.container is None or not text:
            return
        meta = session.get("recipient_meta") or {}
        gid = str(session.get("group_id") or meta.get("group_id") or "")
        if not gid:
            logger.warning("send_group_text: missing group_id")
            return
        target = ChatSender.from_group_chat(
            user_id=str(meta.get("user_id") or session.get("initiator_qq") or "0"),
            group_id=gid,
            display_name=str(meta.get("display_name") or "群成员"),
            metadata={"im_name": HOST_IM},
        )
        msg = IMMessage(
            sender=ChatSender.get_bot_sender(),
            message_elements=[TextMessage(text)],
        )
        try:
            im_manager: IMManager = self.container.resolve(IMManager)
            adapter = im_manager.get_adapter(HOST_IM)
            loop: asyncio.AbstractEventLoop = self.container.resolve(asyncio.AbstractEventLoop)
            loop.create_task(adapter.send_message(msg, target))
        except Exception as exc:
            logger.warning(f"host send failed: {exc}")


def strip_host_command(content: str) -> str:
    """Remove @mentions CQ codes and leading @names."""
    import re

    text = content or ""
    text = re.sub(r"\[CQ:at,[^\]]+\]", " ", text)
    text = re.sub(r"@\S+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_host_start(content: str) -> bool:
    triggers = load_story_triggers()
    text = strip_host_command(content)
    for kw in triggers.get("start_keywords") or []:
        if kw and kw in text:
            return True
    for scene in triggers.get("start_scenes") or []:
        if scene and scene in text:
            return True
    return False


def is_host_end(content: str) -> bool:
    triggers = load_story_triggers()
    text = strip_host_command(content)
    text = text.strip("。.!！?？~～… \t")
    tokens = [str(t).lower() for t in (triggers.get("end_tokens") or ["end", "结束", "stop"])]
    return text.lower() in tokens
