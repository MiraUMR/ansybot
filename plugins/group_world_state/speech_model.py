"""Bestdori 台词炼成的说话模式：语料池 + 节奏统计，给 voice_pack 用。"""
from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path("data/voice_patterns")
_CACHE: Dict[str, Dict[str, Any]] = {}

_HAN = re.compile(r"[\u4e00-\u9fff]")
_YOU = re.compile(r"你(?!们)")
# anon 开口：同伴一切中文/假名/罗马音变体都锁成 soyorin（爽世是 Bestdori-CN 对素世的译名变体）。
# soyo 开口：只锁同伴（裸爱音补成小爱音）；自己名字不动，含自称的句子在 distill 直接丢掉，
# 避免把“我叫爽世”洗成“我，请多指教”这种坏句子。
_NAME_FIX = {
    "anon": (
        (re.compile(r"小?爽世(?:同学|之助)?|素世"), "soyorin"),
        (re.compile(r"そよりん|ソヨリン|ソユリン|そよ"), "soyorin"),
        (re.compile(r"(?i)soyorin"), "soyorin"),
        (re.compile(r"(?i)\bsoyo\b"), "soyorin"),
    ),
    "soyo": (
        (re.compile(r"千早爱音|爱音酱"), "小爱音"),
        (re.compile(r"(?<!小)爱音"), "小爱音"),
        (re.compile(r"アノンちゃん|アノン"), "小爱音"),
        (re.compile(r"(?i)anon(?:\s*chan)?"), "小爱音"),
    ),
}
_SELF_NAME_RE = re.compile(r"爽世|素世|soyorin|soyo|そよ|ソヨ", re.IGNORECASE)


def _cid(character: str) -> str:
    c = (character or "").strip().lower()
    return c if c in ("anon", "soyo") else "soyo"


def pattern_path(character: str) -> Path:
    return ROOT / f"{_cid(character)}.yaml"


def load_pattern(character: str) -> Dict[str, Any]:
    cid = _cid(character)
    if cid in _CACHE:
        return _CACHE[cid]
    path = pattern_path(cid)
    if not path.exists():
        _CACHE[cid] = {}
        return _CACHE[cid]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    _CACHE[cid] = data
    return data


def reload_patterns() -> None:
    _CACHE.clear()


def lock_example(character: str, text: str) -> str:
    out = (text or "").strip()
    for pat, repl in _NAME_FIX.get(_cid(character), ()):
        out = pat.sub(repl, out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def peer_safe(text: str) -> bool:
    return not _YOU.search(text or "")


def pattern_voice_line(character: str) -> str:
    data = load_pattern(character)
    line = str(data.get("voice_line") or "").strip()
    return line


def pattern_pools(character: str) -> Dict[str, List[str]]:
    data = load_pattern(character)
    plain = [lock_example(character, x) for x in (data.get("plain") or []) if str(x).strip()]
    quirk = [lock_example(character, x) for x in (data.get("quirk") or []) if str(x).strip()]
    plain = [x for x in plain if x]
    quirk = [x for x in quirk if x]
    return {"plain": plain, "quirk": quirk}


def _score(line: str, needles: List[str]) -> int:
    if not line or not needles:
        return 0
    return sum(1 for n in needles if n and n in line)


def retrieve_examples(
    character: str,
    content: str,
    *,
    daily: bool,
    recent: Optional[List[str]] = None,
    count: int = 2,
) -> List[str]:
    """按当前这句话的字面重叠，从炼好的池子里抽节奏参考。"""
    pools = pattern_pools(character)
    if not pools["plain"] and not pools["quirk"]:
        return []
    prefer = pools["plain"] if daily else (pools["quirk"] + pools["plain"])
    prefer = [p for p in prefer if peer_safe(p)] or prefer
    banned = set(recent or [])
    fresh = [p for p in prefer if p not in banned] or prefer
    needles = [ch for ch in _HAN.findall(content or "") if ch not in "的了吗呢吧啊呀哦嗯"]
    needles = list(dict.fromkeys(needles))[:12]
    if needles:
        ranked = sorted(fresh, key=lambda s: (-_score(s, needles), len(s), s))
        # 重叠太弱时退回随机，避免每轮都抽到同一批字面命中。
        if _score(ranked[0], needles) <= 0:
            random.shuffle(fresh)
            ranked = fresh
    else:
        ranked = list(fresh)
        random.shuffle(ranked)
    out: List[str] = []
    for line in ranked:
        if line in out:
            continue
        out.append(line)
        if len(out) >= max(1, count):
            break
    return out
