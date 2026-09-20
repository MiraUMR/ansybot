#!/usr/bin/env python3
"""近期聊天注入：去重、截短、丢掉空回声。"""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = spec_from_file_location(
    "memory_inject", ROOT / "plugins" / "group_world_state" / "memory_inject.py"
)
mod = module_from_spec(spec)
spec.loader.exec_module(mod)

failed = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global failed
    print(f"[{'OK ' if cond else 'FAIL'}] {label}{(' :: ' + extra) if extra else ''}")
    if not cond:
        failed += 1


def entry(content: str, ts: int = 0) -> SimpleNamespace:
    return SimpleNamespace(content=content, timestamp=ts)


reply = (
    "Mira 说: @千早爱音 你回答\n"
    "你回答: 嗯今天没安排出门啦，窝在房间里刷刷谱面就好。"
)
echo = "千早爱音 说: 嗯今天没安排出门啦，窝在房间里刷刷谱面就好。"
inbound = "Mira 说: @千早爱音 你回答"
empty = "长崎素世 说:"
peer = "长崎素世 说: 那明天呢"
blank_reply = "刚刚，千早爱音 说: \n你回答: "

picked = mod.compact_memory_entries(
    [entry(inbound), entry(reply), entry(echo), entry(empty), entry(peer), entry(blank_reply)]
)
texts = [e.content for e in picked]
check("丢掉空你回答", blank_reply not in texts and not any("你回答:" in t and not mod.memory_payload(t) for t in texts))
check("丢掉空「说:」", empty not in texts)
check("丢掉自己回声", echo not in texts)
check("丢掉与你回答重复的入站", inbound not in texts)
check("留下完整一轮", reply in texts)
check("留下同伴新句", peer in texts)

long_ans = "啊。" + ("可以啊可以啊，" * 40) + "那就这样。"
clipped = mod.clip_memory_entry_text(f"刚刚，Mira 说: 约吗\n你回答: {long_ans}")
check("长回复被截短", 40 < len(clipped) < len(long_ans) + 20, clipped)
check("截短仍带时间前缀", clipped.startswith("刚刚，"))
check("截短仍带你回答", "你回答:" in clipped)
check("截短不只留一句啊", "可以啊" in clipped)

many = [entry(f"Mira 说: n{i}\n你回答: r{i}") for i in range(12)]
capped = mod.compact_memory_entries(many)
check("最多保留6轮", len(capped) == 6, str(len(capped)))
check("保留最新", capped[-1].content.endswith("r11") and "n11" in capped[-1].content)

gated = mod.compact_memory_content(
    [
        "刚刚，" + inbound,
        "刚刚，" + reply,
        "刚刚，" + echo,
        "刚刚，" + peer,
    ]
)
check("字符串门控去重", len(gated) == 2, str(gated))
check("门控截短后仍是字符串", all(isinstance(x, str) for x in gated))

blocks = (ROOT / "plugins/group_world_state/blocks.py").read_text(encoding="utf-8")
compose = (ROOT / "patches/builtin_composes.py").read_text(encoding="utf-8")
check("fallback 跳过 self 回声", 'kind == "self"' in blocks and "classify_sender_qq" in blocks)
check("记忆门控走 compact", "compact_memory_content" in blocks)
check("分解器走 compact", "_compact_today_entries" in compose and "clip_memory_entry_text" in compose)

if failed:
    raise SystemExit(f"{failed} checks failed")
print("all passed")
