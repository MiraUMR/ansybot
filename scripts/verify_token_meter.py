"""校验 token 拆分日志：按模块命名，而不是只记一个数字。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import types
from importlib.util import module_from_spec, spec_from_file_location

pkg = types.ModuleType("group_world_state")
pkg.__path__ = [str(ROOT / "plugins" / "group_world_state")]
sys.modules["group_world_state"] = pkg
spec = spec_from_file_location(
    "group_world_state.token_meter",
    ROOT / "plugins" / "group_world_state" / "token_meter.py",
)
token_meter = module_from_spec(spec)
sys.modules["group_world_state.token_meter"] = token_meter
spec.loader.exec_module(token_meter)

estimate_tokens = token_meter.estimate_tokens
format_api_usage = token_meter.format_api_usage
format_chat_token_report = token_meter.format_chat_token_report
format_consumed = token_meter.format_consumed
format_module_injection = token_meter.format_module_injection
format_static_modules = token_meter.format_static_modules
split_system_prompt = token_meter.split_system_prompt


def check(label: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {label}{(' :: ' + extra) if extra else ''}")
    if not cond:
        sys.exit(1)


sample = (
    "你就是长崎素世本人。\n"
    "# 不可推翻的强设定（最高优先级）\nbase body\n\n"
    "## 普通群聊（无标签 / 非@消息）\ncompanion body\n\n"
    "# 本群长期关系（仅本群有效）\nrelation body\n\n"
    "# 当下\n只根据眼前这段对话回复。\n\n"
    "# 当前信息\n现在时间：2026-09-04\n\n"
    "# 近期聊天（仅同伴）\n"
    "-- 对话记录开始 --\n"
    "爱音：今天练到九点\n"
    "-- 对话记录结束 --\n\n"
    "记住：`<break>` 只是发消息的分段标记。\n"
)

parts = split_system_prompt(sample)
names = [n for n, _ in parts]
check("拆出人设.base", "人设.base" in names)
check("拆出人设.companion.md", "人设.companion.md" in names)
check("拆出本群长期关系", "本群长期关系" in names)
check("拆出近期聊天.内容", "近期聊天.内容" in names)
check("拆出回复规则", "回复规则" in names)
check("消耗了句式", "人设.base 消耗了" in format_consumed("人设.base", 12) and "token" in format_consumed("人设.base", 12))
check("estimate 非零", estimate_tokens(sample) > 20)

class _U:
    prompt_tokens = 100
    completion_tokens = 20
    total_tokens = 120

api = format_api_usage(_U(), model="demo")
check("API 命名 prompt/completion", "prompt 消耗了 100 token" in api and "completion 消耗了 20 token" in api)

inj = format_module_injection("soyo", "peer", [("base", "aaa"), ("companion", "bbb")])
check("注入日志含角色与消耗了", "persona_layers soyo" in inj and "base 消耗了" in inj)

static = format_static_modules([("soyo:base", "hello 素世")])
check("预估日志不再 dump dict", "{" not in static and "消耗了" in static)

class _P:
    def __init__(self, role, text):
        self.role = role
        self.content = [type("T", (), {"text": text, "media_id": None})()]

report = format_chat_token_report(
    [_P("system", sample), _P("user", "小爱音今天练完了吗")],
    model="dashscope/qwen",
    mode="peer",
    resp=_U(),
)
check("chat 拆分含 character=soyo", "character=soyo" in report)
check("chat 拆分含本轮.user", "本轮.user 消耗了" in report)
check("chat 拆分含 API 行", "prompt 消耗了 100 token" in report)

chat_py = (ROOT / "patches/llm_chat.py").read_text(encoding="utf-8")
adapter = (ROOT / "patches/openai_adapter.py").read_text(encoding="utf-8")
init_py = (ROOT / "plugins/group_world_state/__init__.py").read_text(encoding="utf-8")
check("ChatCompletion 调用拆分日志", "format_chat_token_report" in chat_py)
check("adapter 记录 named usage", "prompt 消耗了" in adapter and "completion 消耗了" in adapter)
check("启动日志改用 format_static_modules", "format_static_modules" in init_py)

print("all checks passed")
