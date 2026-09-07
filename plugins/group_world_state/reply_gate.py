"""同群/同会话聊天串行，避免套餐卡住时并发导致串回复。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import DefaultDict, Dict, Optional, Tuple

from kirara_ai.logger import get_logger

logger = get_logger("ChatReplyGate")

# key -> generation（每次新消息 +1）
_generation: Dict[str, int] = {}
_locks: DefaultDict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_meta_lock = asyncio.Lock()


def scope_key(im_name: str, group_id: Optional[str], user_id: Optional[str]) -> str:
    im = (im_name or "unknown").strip() or "unknown"
    if group_id:
        return f"{im}:g:{group_id}"
    return f"{im}:u:{user_id or 'unknown'}"


async def begin(key: str) -> int:
    """登记一条待处理聊天，返回本票 generation。"""
    async with _meta_lock:
        gen = _generation.get(key, 0) + 1
        _generation[key] = gen
        return gen


def current(key: str) -> int:
    return _generation.get(key, 0)


async def run_exclusive(key: str, gen: int, coro):
    """
    同一 scope 串行执行。
    若排队期间又来了更新的消息（generation 已前进），跳过本票，避免旧回复插队。
    """
    lock = _locks[key]
    async with lock:
        cur = current(key)
        if cur != gen:
            logger.info(f"skip stale reply scope={key} gen={gen} current={cur}")
            return None
        return await coro
