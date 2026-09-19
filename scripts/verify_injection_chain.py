#!/usr/bin/env python3
"""Check injection chain: duplicates, dead dumps, vision caption, token size."""
from __future__ import annotations

import re
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
failed = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global failed
    print(f"[{'OK ' if cond else 'FAIL'}] {label}{(' :: ' + extra) if extra else ''}")
    if not cond:
        failed += 1


def load_pkg_mod(mod_name: str, rel: str):
    spec = spec_from_file_location(mod_name, ROOT / rel)
    mod = module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


pkg = types.ModuleType("kirara_ai")
pkg_plugins = types.ModuleType("kirara_ai.plugins")
pkg_gws = types.ModuleType("kirara_ai.plugins.group_world_state")
pkg_gws.__path__ = [str(ROOT / "plugins" / "group_world_state")]
sys.modules["kirara_ai"] = pkg
sys.modules["kirara_ai.plugins"] = pkg_plugins
sys.modules["kirara_ai.plugins.group_world_state"] = pkg_gws

blocks = (ROOT / "plugins/group_world_state/blocks.py").read_text(encoding="utf-8")
chat_py = (ROOT / "patches/llm_chat.py").read_text(encoding="utf-8")
compose_py = (ROOT / "patches/builtin_composes.py").read_text(encoding="utf-8")
guard = (ROOT / "plugins/group_world_state/style_guard.py").read_text(encoding="utf-8")
meter_py = (ROOT / "plugins/group_world_state/token_meter.py").read_text(encoding="utf-8")

check("direct 对话对象不再塞情境框架", "情境自适应：按问题本身选择" not in blocks)
check("direct 对话对象用眼前的人", 'display or "眼前的人"' in blocks)
check("轻提不再两截转进", "再用半句随口带到" not in blocks)
check("轻提改为同一句带过", "可以在同一句里偶尔带过" in blocks)
check("Trigger 禁止两截转进", "禁止两截转进" in blocks)
check("识图提示禁止套上一轮", "不要把上一轮看图的句子" in chat_py)
check("识图描述走短物象", "_vision_caption_from_reply" in chat_py)
check("记忆图片过滤角色回复", "_VOICE_CAPTION_RE" in compose_py)
check("素世拦截公式转进", "公式转进" in guard)
check("token 拆分认 XML", "<at_mode>" in meter_py and "<companion_mode" in meter_py)

compiler = load_pkg_mod(
    "kirara_ai.plugins.group_world_state.compiler",
    "plugins/group_world_state/compiler.py",
)
for cid in ("soyo", "anon"):
    text = compiler.compile_persona(
        cid,
        mode="chat",
        peer_online=True,
        context_text="@角色 这是什么",
        at_mode=True,
        sender_qq="747905287",
    )
    n = compiler._estimate(text)
    check(f"{cid} @编译不含群聊", "群聊" not in text, f"tokens≈{n}")
    check(f"{cid} @编译低于预算", n <= compiler._TOKEN_BUDGET["chat"], f"{n}")
    check(f"{cid} @不含重复 peer 块", "<peer " not in text and "<peer>" not in text)
    check(f"{cid} @含 at_mode", "<at_mode>" in text)
    check(f"{cid} 框架禁止两截转进", "禁止两截转进" in text)
    check(f"{cid} 无旧 markdown 触发表", "## 被@时的响应范式" not in text)
    check(f"{cid} 闲聊不灌口味锚点", "蔬菜通心粉汤" not in text and "水果三明治" not in text)
    check(f"{cid} 闲聊不强制点菜", "本轮自己定" not in text)

leak = re.compile(r"发给|截图|soyorin|小爱音|走不动|某人|拉她|给她看", re.I)


def vision_caption(reply: str) -> str:
    text = re.sub(r"\s+", " ", (reply or "").strip())
    if not text:
        return "已看过图"
    head = re.split(r"[。？?\n]", text, maxsplit=1)[0].strip("，,。！!?—-… ")
    if len(head) < 8:
        bits = [p.strip() for p in re.split(r"[。！？!?\n]", text) if p.strip()]
        head = "。".join(bits[:2]).strip("，,。！!?—-… ")
    if not head or leak.search(head) or len(head) >= 40:
        cleaned = leak.sub(" ", head or text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip("，,。！!?—-… ")
        if 4 <= len(cleaned) <= 24:
            return cleaned
        return "已看过图"
    return head[:36]


sample = (
    "哇——！这什么，小香猪吗！！粉粉嫩嫩的也太犯规了吧。"
    "刚刷到这种萌物根本走不动道啊……不行我得截图发给soyorin看看。"
)
out = vision_caption(sample)
check("识图说明不含发给soyorin", "发给" not in out and "soyorin" not in out.lower(), out)
check("识图说明很短", len(out) <= 36, out)

xml_sys = (
    "<role id=\"soyo\" name=\"长崎素世\">\n<lock>\n- 软慢\n</lock>\n"
    "<at_mode>\n- 禁止两截转进\n</at_mode>\n"
    "# 当下\n只根据眼前这段对话回复。\n"
)
meter = load_pkg_mod(
    "kirara_ai.plugins.group_world_state.token_meter",
    "plugins/group_world_state/token_meter.py",
)
xml_names = [n for n, _ in meter.split_system_prompt(xml_sys)]
check("XML 拆出人设.at_mode", "人设.at_mode" in xml_names, str(xml_names))
check("XML 拆出当下", "当下" in xml_names, str(xml_names))

if failed:
    sys.exit(1)
print("all checks passed")
