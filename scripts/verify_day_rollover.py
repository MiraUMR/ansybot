#!/usr/bin/env python3
"""自然日翻篇：昨天的约定/做过的事不再当今天的话题。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = spec_from_file_location(
    "day_rollover", ROOT / "plugins" / "group_world_state" / "day_rollover.py"
)
mod = module_from_spec(spec)
spec.loader.exec_module(mod)
classify_fact = mod.classify_fact
is_same_civil_day = mod.is_same_civil_day
keep_today_memory = mod.keep_today_memory
render_fact_sections = mod.render_fact_sections

CST = timezone(timedelta(hours=8))
failed = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global failed
    print(f"[{'OK ' if cond else 'FAIL'}] {label}{(' :: ' + extra) if extra else ''}")
    if not cond:
        failed += 1


now = datetime(2026, 9, 19, 23, 0, tzinfo=CST)
yesterday = "2026-09-18T21:10:00+08:00"
today = "2026-09-19T11:00:00+08:00"

rel = {"key": "relationship", "text": "双方互相喜欢，尚未正式告白", "updated_at": yesterday}
crepe = {
    "key": "plot",
    "text": "群里在聊新开的可丽饼店，看起来超好吃",
    "updated_at": yesterday,
}
done = {
    "key": "promise",
    "text": "已经去过那家可丽饼店了",
    "updated_at": today,
}
open_p = {
    "key": "promise",
    "text": "今晚去喝一杯",
    "updated_at": today,
}
confess = {
    "key": "plot",
    "text": "爱音已向素世告白，素世害羞但已接受",
    "updated_at": yesterday,
}

check("昨天可丽饼话题 closed", classify_fact(crepe, now) == "closed")
check("关系事实 sticky", classify_fact(rel, now) == "sticky")
check("告白剧情 sticky", classify_fact(confess, now) == "sticky")
check("做过的事 closed", classify_fact(done, now) == "closed")
check("今天未做完的约定 open", classify_fact(open_p, now) == "open")

text = render_fact_sections([rel, crepe, done, open_p, confess], "（空）", now)
check("关系仍是既定事实", "必须当作既定事实" in text and "双方互相喜欢" in text)
check("告白不因隔日翻掉", "爱音已向素世告白" in text)
check("可丽饼进翻篇栏", "已翻篇的近事" in text and "可丽饼店" in text)
check("做过的事进翻篇栏", "已经去过那家可丽饼店了" in text)
check("今天约定仍进行中", "今天还在进行的约定" in text and "今晚去喝一杯" in text)
check("翻篇栏禁止续摊", "不要当还没做完" in text)

check("昨天时间戳不是今天", not is_same_civil_day(datetime(2026, 9, 18, 23, 50), now))
check("今天时间戳是今天", is_same_civil_day(datetime(2026, 9, 19, 0, 10), now))
check("丢掉 N天前 字符串", keep_today_memory(["1天前，聊可丽饼", "刚刚，嗯"], now) == ["刚刚，嗯"])

anon = (ROOT / "data/workflows/chat/anon.yaml").read_text(encoding="utf-8")
soyo = (ROOT / "data/workflows/chat/soyo.yaml").read_text(encoding="utf-8")
check("anon 工作流写了自然日翻篇", "跨过自然日的闲聊" in anon)
check("soyo 工作流写了自然日翻篇", "跨过自然日的闲聊" in soyo)

compose = (ROOT / "patches/builtin_composes.py").read_text(encoding="utf-8")
check("记忆分解只留当天", "_today_memory_entries" in compose)

if failed:
    raise SystemExit(f"{failed} checks failed")
print("all passed")
