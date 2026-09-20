from __future__ import annotations

import re
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from .characters import (
    aliases,
    character_by_qq,
    get_character,
    peer_config,
    peer_id_for,
    peer_qq,
)

CST = timezone(timedelta(hours=8))
_lock = threading.Lock()


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


class PeerChainStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, group_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(group_id))[:80]
        return self.root / f"{safe or 'unknown'}.yaml"

    def _read(self, group_id: str) -> Dict[str, Any]:
        path = self._path(group_id)
        if not path.exists():
            return {"group_id": str(group_id), "rounds": 0, "last_speaker": "", "updated_at": "", "cooldown_until": ""}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("group_id", str(group_id))
        data.setdefault("rounds", 0)
        data.setdefault("last_speaker", "")
        data.setdefault("updated_at", "")
        data.setdefault("cooldown_until", "")
        return data

    def _write(self, doc: Dict[str, Any]) -> None:
        path = self._path(str(doc.get("group_id") or "unknown"))
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        tmp.replace(path)

    def in_cooldown(self, group_id: str) -> bool:
        with _lock:
            doc = self._read(group_id)
            until = _parse(doc.get("cooldown_until") or "")
            return bool(until and until > _now())

    def last_speaker(self, group_id: str) -> str:
        with _lock:
            return str(self._read(group_id).get("last_speaker") or "")

    def companion_online(self, group_id: str, ttl_seconds: Optional[int] = None) -> bool:
        """白名单同伴最近是否还在互聊链里（心跳＝最后一次同伴对话时间）。"""
        ttl = int(
            ttl_seconds
            if ttl_seconds is not None
            else (peer_config().get("chain_ttl_seconds") or 600)
        )
        with _lock:
            updated = _parse(self._read(group_id).get("updated_at") or "")
        if not updated:
            return False
        return (_now() - updated).total_seconds() <= ttl

    def set_scene(self, group_id: str, scene: str, ttl_seconds: int = 180) -> None:
        with _lock:
            doc = self._read(group_id)
            doc["group_id"] = str(group_id)
            doc["scene"] = scene
            doc["scene_until"] = _iso(_now() + timedelta(seconds=ttl_seconds))
            self._write(doc)

    def get_scene(self, group_id: str) -> str:
        with _lock:
            doc = self._read(group_id)
            until = _parse(doc.get("scene_until") or "")
            if until and until > _now():
                return str(doc.get("scene") or "")
            return ""

    def should_continue(self, group_id: str, character_id: str) -> Tuple[bool, str]:
        """Return (allowed, reason_hint for prompt)."""
        cfg = peer_config()
        max_rounds = int(cfg.get("max_rounds") or 3)
        ttl = int(cfg.get("chain_ttl_seconds") or 600)
        with _lock:
            doc = self._read(group_id)
            until = _parse(doc.get("cooldown_until") or "")
            if until and until > _now():
                return False, "同伴互聊冷却中，本轮别主动找同伴开口，专注回眼前的人。"
            scene_until = _parse(doc.get("scene_until") or "")
            scene = str(doc.get("scene") or "")
            if scene_until and scene_until > _now() and scene == "anon_chasing_soyo":
                if character_id == "soyo":
                    return True, (
                        "小爱音在追你。你是跑开的那一方，接住她「别跑/等等我」。"
                        "不要去追她，不要说追到了，不要也好收束，不要拐到吃的/时间。"
                    )
                return True, (
                    "你在追 soyorin。对面就是她，「你」=她。"
                    "鞋带散了是你自己的。禁止说「你比soyorin跑得快」。"
                )
            updated = _parse(doc.get("updated_at") or "")
            rounds = int(doc.get("rounds") or 0)
            if updated and (_now() - updated).total_seconds() > ttl:
                doc["rounds"] = 0
                doc["last_speaker"] = ""
                rounds = 0
            if rounds >= max_rounds:
                return False, "同伴互聊已够，自然收束，别再抛新话题。"
            remain = max_rounds - rounds
            if remain <= 1:
                if character_id == "soyo":
                    return True, (
                        "这轮可以停，也可以轻轻拐一下再停。不要提问拉长。"
                        "停法随眼前的事走，换一种停，不要套同一句。"
                    )
                return True, (
                    "这轮可以停，也可以贴半句再停。不要追问成采访。"
                    "停法随眼前的事走，换一种停，不要套同一句。"
                )
            if character_id == "soyo":
                return True, (
                    "正在和同伴（小爱音）互聊：接住她刚说的，可以轻轻拐半句（吃的、时间、嫌一句）。"
                    "不要另开排期，也不要每轮都收口。"
                )
            return True, (
                "正在和同伴互聊：接住她刚说的，可以轻轻拐半句。不要采访追问，也不要每轮都收口。"
            )

    def record_reply(self, group_id: str, character_id: str) -> None:
        cfg = peer_config()
        max_rounds = int(cfg.get("max_rounds") or 3)
        cool = int(cfg.get("cooldown_seconds") or 180)
        with _lock:
            doc = self._read(group_id)
            last = doc.get("last_speaker") or ""
            rounds = int(doc.get("rounds") or 0)
            if last and last != character_id:
                rounds += 1
            elif not last:
                rounds = 1
            doc["rounds"] = rounds
            doc["last_speaker"] = character_id
            doc["updated_at"] = _iso(_now())
            if rounds >= max_rounds:
                doc["cooldown_until"] = _iso(_now() + timedelta(seconds=cool))
                doc["rounds"] = 0
                doc["last_speaker"] = ""
            self._write(doc)

    def seal_chain(self, group_id: str) -> None:
        """收束或触顶后立刻冷却，避免下一句又接上。"""
        cool = int(peer_config().get("cooldown_seconds") or 180)
        with _lock:
            doc = self._read(group_id)
            doc["group_id"] = str(group_id)
            doc["cooldown_until"] = _iso(_now() + timedelta(seconds=cool))
            doc["rounds"] = 0
            doc["last_speaker"] = ""
            doc["updated_at"] = _iso(_now())
            doc["scene"] = ""
            doc["scene_until"] = ""
            self._write(doc)


_WRAP_RE = re.compile(
    r"(那先这样|先这样吧|先这样|回头再说|晚点再说|我去练|先走了|不说了|"
    r"就这样吧|就这样|你自己看着办|自己看着办|先别到处说|"
    r"下次再说|先到这|先到这儿|"
    r"那我等你|我等你哦|不聊了|先去忙|我去忙|先忙|"
    r"回头聊|先去练一下)"
)
_WRAP_SHORT = {
    "不聊了", "先这样", "就这样", "先走了", "我去忙",
}
_CONTINUE_RE = re.compile(r"[？?]|要不要|去哪|怎么了|为什么|是不是|好不好")


def looks_like_wrap_up(text: str) -> bool:
    """对方已经把话收住，本轮不宜再接。"""
    t = (text or "").strip()
    if not t:
        return True
    if _CONTINUE_RE.search(t):
        return False
    compact = re.sub(r"[\s。.!！~～、，,]+", "", t)
    if not compact:
        return True
    if compact in _WRAP_SHORT:
        return True
    if _WRAP_RE.search(t):
        return True
    if len(compact) <= 18 and re.search(r"(知道了|行吧|好吧)", compact):
        return True
    return False


def peer_should_discard(*, allowed: bool, wrap_up: bool, at_self: bool) -> bool:
    """文字点名/引用回复不能续摊；只有真正的 @ 才能打断收束或轮次上限。"""
    if at_self:
        return False
    return wrap_up or (not allowed)


_SCENE_HINT = re.compile(
    r"(走在|路上|突然|撞见|遇见|看见|看到|发现|偷偷|正在|路过|场面|场景|设定为)"
)

_ASCII_ALIAS = re.compile(r"^[A-Za-z0-9_]+$")
# 「你/在吗/帮我」这类才算真的在跟角色说话，只是提到名字不算。
_ADDRESS_HINT = re.compile(r"(你|您|在吗|在不在|来一下|帮我|教我|求你|怎么看|觉得呢)")
# 爱音常用 soyorin——／小爱音～ 这种拖长，必须算当面叫人。
_NAME_SEP = "，,、：:！!？?…~～—–―－ー- \t　"


def alias_hit(text: str, alias: str) -> bool:
    """英文别名要词边界，避免 canon / anonymous 这类误判成点名。"""
    a = (alias or "").strip()
    if not a:
        return False
    if _ASCII_ALIAS.match(a):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(a)}(?![A-Za-z0-9])"
        return re.search(pattern, text or "", re.IGNORECASE) is not None
    return a in (text or "")


_VOCATIVE_SEP = "，,、：:！!？?…~～—–―－ー-"


def looks_vocative_to(text: str, character_id: str) -> bool:
    """名字后跟称呼停顿才算叫她。只是提到「小爱音又发了…」不算当面说话。"""
    raw = (text or "").strip()
    if not raw:
        return False
    names = sorted(
        (a for a in aliases(character_id) if a),
        key=len,
        reverse=True,
    )
    hit = next((a for a in names if alias_hit(raw, a)), "")
    if not hit:
        return False
    flags = re.IGNORECASE if _ASCII_ALIAS.match(hit) else 0
    if re.search(rf"{re.escape(hit)}\s*[{re.escape(_VOCATIVE_SEP)}]", raw, flags):
        return True
    if re.search(rf"{re.escape(hit)}\s*(你|出来|在吗|看一下|帮我)", raw, flags):
        return True
    return bool(re.search(rf"{re.escape(hit)}\s*[?？]\s*$", raw, flags))


def looks_addressed_to_self(text: str, character_id: str) -> bool:
    """区分「在跟你说话」和「只是提到你」。后者按环境音处理，保住代入感。"""
    raw = (text or "").strip()
    if not raw:
        return False
    names = sorted(
        (a for a in aliases(character_id) if a),
        key=len,
        reverse=True,
    )
    hit = next((a for a in names if alias_hit(raw, a)), "")
    if not hit:
        return False
    if _ADDRESS_HINT.search(raw):
        return True
    # 句首或句中：名字后跟停顿才算叫人。「小爱音，出来吧」算叫；「小爱音今天没来」不算。
    flags = re.IGNORECASE if _ASCII_ALIAS.match(hit) else 0
    if re.search(rf"{re.escape(hit)}\s*[{re.escape(_NAME_SEP)}]", raw, flags):
        return True
    return bool(re.search(rf"{re.escape(hit)}\s*[?？]\s*$", raw, flags))


def looks_like_narrated_scene(text: str, character_id: str) -> bool:
    """第三人称场面（「撞见某某正在…」），不是在点名你回答。"""
    raw = text or ""
    if re.search(r"[@＠]", raw):
        return False
    self_names = [a for a in aliases(character_id) if a and len(a) >= 2]
    if not any(a in raw for a in self_names):
        return False
    if not _SCENE_HINT.search(raw):
        return False
    peer_cid = peer_id_for(character_id)
    peer_names = [a for a in aliases(peer_cid) if a and len(a) >= 2] if peer_cid else []
    peer_hit = any(a in raw for a in peer_names)
    # 两个角色都出现，或自己名字 + 场面动词：当场面，不当 @
    return bool(peer_hit or len(re.sub(r"\s+", "", raw)) >= 16)


def analyze_dialogue_target(
    character_id: str,
    sender_qq: str,
    content: str,
    mentioned_self: bool = False,
    is_reply_to_self: bool = False,
) -> Dict[str, Any]:
    """按发送者账号分流（只在代码里做）：只有配置的同伴才是 peer。

    提示词只给「同伴 / 眼前的人」，不写入任何账号。不认昵称 / 显示名 / 名片。
    """
    from .characters import classify_sender_qq, is_peer_qq, is_registered_bot_qq, peer_address

    peer_cid = peer_id_for(character_id)
    peer = get_character(peer_cid) if peer_cid else {}
    text = content or ""
    sender_qq = str(sender_qq or "").strip()
    kind = classify_sender_qq(character_id, sender_qq)
    is_peer = kind == "peer" or is_peer_qq(character_id, sender_qq)
    is_bot = is_registered_bot_qq(sender_qq)

    self_aliases = aliases(character_id)
    named_self = any(alias_hit(text, a) for a in self_aliases)
    if named_self and looks_like_narrated_scene(text, character_id):
        named_self = False

    call = (peer_address(character_id).get("call") or "").strip()
    peer_label = str(peer.get("display") or peer_cid or "同伴")
    if is_peer:
        target = f"同伴（当面称{call or peer_label}）"
        force = mentioned_self or is_reply_to_self or named_self
        return {
            "dialogue_target": target,
            "is_peer": True,
            "is_bot": True,
            "sender_kind": "peer",
            "sender_qq": sender_qq,
            "should_reply_peer": force,
            "named_self": named_self,
            "force_peer": force,
            "extract_priority": "peer",
        }

    # 非同伴：即使是登记 Bot / 同名昵称，也当眼前的人
    if mentioned_self or is_reply_to_self or named_self:
        return {
            "dialogue_target": "眼前的人，正在对你说话",
            "is_peer": False,
            "is_bot": is_bot,
            "sender_kind": "member",
            "sender_qq": sender_qq,
            "should_reply_peer": False,
            "named_self": True,
            "force_peer": False,
            "extract_priority": "normal",
        }

    return {
        "dialogue_target": "眼前的人",
        "is_peer": False,
        "is_bot": is_bot,
        "sender_kind": "member",
        "sender_qq": sender_qq,
        "should_reply_peer": False,
        "named_self": False,
        "force_peer": False,
        "extract_priority": "normal",
    }
