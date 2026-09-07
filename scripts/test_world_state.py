#!/usr/bin/env python3
"""Parser/store tests that do not need Kirara running."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins"))

from group_world_state.extractor import (
    filter_ops,
    is_regression,
    parse_extract_json,
    should_extract,
)
from group_world_state.parser import StateOp, extract_command, strip_state
from group_world_state.store import WorldStateStore


class ParserTest(unittest.TestCase):
    def test_strip_and_set(self):
        raw = "好啊那就这样。<break>笨蛋。\n<<STATE\nSET relationship 已经告白并交往\n>>"
        cleaned, ops = strip_state(raw)
        self.assertNotIn("<<STATE", cleaned)
        self.assertIn("笨蛋", cleaned)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].op, "set")
        self.assertEqual(ops[0].key, "relationship")
        self.assertIn("告白", ops[0].text)

    def test_no_marker(self):
        cleaned, ops = strip_state("普通回复")
        self.assertEqual(cleaned, "普通回复")
        self.assertEqual(ops, [])

    def test_del(self):
        _, ops = strip_state("<<STATE\nDEL nickname\n>>")
        self.assertEqual(ops[0].op, "del")
        self.assertEqual(ops[0].key, "nickname")

    def test_command(self):
        self.assertEqual(extract_command("/长期记忆")[0], "show")
        verb, args = extract_command("/长期记忆 设定 relationship 已经告白")
        self.assertEqual(verb, "set")
        self.assertEqual(args, ["relationship", "已经告白"])
        self.assertEqual(extract_command("随便聊聊"), None)


class StoreTest(unittest.TestCase):
    def test_group_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorldStateStore(Path(tmp))
            store.set_fact("1035893116", "relationship", "已经告白", source="command")
            store.set_fact("1071033510", "relationship", "还在暗恋", source="command")
            a = store.render("1035893116")
            b = store.render("1071033510")
            self.assertIn("已经告白", a)
            self.assertIn("还在暗恋", b)
            self.assertNotIn("已经告白", b)


class ExtractorTest(unittest.TestCase):
    def test_parse_updates(self):
        ops = parse_extract_json(
            '```json\n{"updates":[{"op":"set","key":"relationship","text":"已经告白并交往"}]}\n```'
        )
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].key, "relationship")
        self.assertIn("交往", ops[0].text)

    def test_empty_updates(self):
        self.assertEqual(parse_extract_json('{"updates":[]}'), [])
        self.assertEqual(parse_extract_json("NONE"), [])

    def test_should_extract(self):
        self.assertTrue(should_extract("她接受告白了", "", always=False))
        self.assertFalse(should_extract("吃了吗", "", always=False))
        self.assertFalse(should_extract("/长期记忆", "已经告白", always=True))
        self.assertTrue(should_extract("今天天气真不错啊", "嗯那就这样吧我先回去了", always=True))

    def test_filter_forbidden_and_regression(self):
        current = "【本群已经发生、必须当作既定事实】\n- relationship: 已经向长崎素世告白并被接受，目前在交往"
        ops = filter_ops(
            [
                StateOp("set", "relationship", "爱音是直男"),
                StateOp("set", "relationship", "尚未告白，仍是别扭暗恋"),
                StateOp("set", "relationship", "已经向长崎素世告白并被接受，目前在交往"),
                StateOp("set", "plot", "今晚要去Live"),
            ],
            current,
        )
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].key, "plot")
        self.assertTrue(is_regression("relationship", "还在暗恋", current))


if __name__ == "__main__":
    unittest.main()
