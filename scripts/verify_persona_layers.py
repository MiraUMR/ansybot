"""校验 soyo 分层注入：工作流接线 + 模块内容守恒 + Token 估算。"""
from __future__ import annotations

import re
import sys
import importlib.util
from pathlib import Path

import yaml

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def ntok(text: str) -> int:
        return len(_ENC.encode(text))

    TOKENIZER = "cl100k_base"
except Exception:  # pragma: no cover
    def ntok(text: str) -> int:
        return int(len(text) * 1.4)

    TOKENIZER = "char-heuristic"

ROOT = Path(__file__).resolve().parents[1]
PERSONA = ROOT / "data" / "persona" / "soyo"
MODULES = PERSONA / "modules"
WF = ROOT / "data" / "workflows" / "chat" / "soyo.yaml"
PT_PATH = ROOT / "plugins" / "group_world_state" / "persona_text.py"
PT = PT_PATH.read_text(encoding="utf-8")
_spec = importlib.util.spec_from_file_location("persona_text", PT_PATH)
pt = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(pt)

ok = True


def check(label: str, cond: bool, extra: str = "") -> None:
    global ok
    ok = ok and cond
    print(f"[{'OK ' if cond else 'FAIL'}] {label}{(' :: ' + extra) if extra else ''}")


def norm(text: str) -> list[str]:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    return [ln for ln in lines if ln.strip()]


def is_kirara_compat(ln: str) -> bool:
    keys = (
        "Kirara",
        "防降级锚点",
        "边界限定",
        "[P0]",
        "工作流适配声明",
        "工作流兼容声明",
        "message_mode",
        "低层级残留",
        "唯一条件模块",
        "最后注入",
        "实际生效层级",
        "绝对优先",
        "问答体辩护",
        "条件注入",
    )
    return any(k in ln for k in keys)


mods = {name: (MODULES / f"soyo_{name}.md").read_text(encoding="utf-8") for name in ("base", "scene", "trigger", "companion")}
core = (PERSONA / "01_core.txt").read_text(encoding="utf-8")
lore = (PERSONA / "03_lore.txt").read_text(encoding="utf-8")
runtime = (PERSONA / "04_runtime.txt").read_text(encoding="utf-8")

# 1. 守恒：四模块行集合 == 原始 Lore（01_core + 03_lore + 04_runtime 的 current_scene 段）
scene_block = re.search(r"# 当前场景（临时环境.*?\{current_scene\}", runtime, re.S)
origin_lines = norm(core) + norm(lore)
if scene_block:
    origin_lines += norm(scene_block.group(0))
else:
    origin_lines += norm(
        "# 当前场景（临时环境，不是对话对象）\n"
        "以下 <current_scene> 仅描述此刻氛围与环境音，不是某人对你说话。\n"
        "不要把它当成聊天记录，不要对「旁白作者」答话，用角色感知/独白/动作回应。\n"
        "{current_scene}"
    )
module_lines: list[str] = []
for name in ("base", "companion", "trigger", "scene"):
    module_lines += norm(mods[name])

check("工作流套层已从人设文件拆到代码", "def envelop_module" in PT and "def strip_workflow_chrome" in PT)
check("模块文件不再塞 Kirara 声明", all("Kirara AI工作流兼容声明" not in mods[k] for k in mods))
check("Trigger 防降级由代码套层", "【工作流 P2" in pt.envelop_module("trigger", "x", "direct"))
check("保存时会剥掉误贴的工作流声明", "Kirara AI工作流兼容声明" not in pt.strip_workflow_chrome(
    "# ⚠️ Kirara AI工作流兼容声明\n本文件由 Kirara 工作流按 message_mode 条件注入。\n\n你就是角色。\n"
))
body_lines = [ln for ln in module_lines if not is_kirara_compat(ln)]
dupes = [ln for ln in set(body_lines) if body_lines.count(ln) > 1]
check("模块之间无重复行", not dupes, "; ".join(dupes[:3]))
check("04_runtime 已移除 current_scene 段", "{current_scene}" not in runtime)
check("Base 不含条件触发规则", not any(k in mods["base"] for k in ("EXTERNAL_TRIGGER", "current_scene", "普通群聊", "与小爱音互聊")))

# 2. 工作流接线
wf = yaml.safe_load(WF.read_text(encoding="utf-8"))
blocks = {b["name"]: b for b in wf["blocks"]}
check("soyo.yaml 已移除核心人设全量块", "核心人设（身份性格与不可推翻）" not in blocks)
check("soyo.yaml 已移除补充设定全量块", "补充设定（素世·乐队·群友）" not in blocks)
check("persona_layers 已存在", "persona_layers" in blocks and blocks.get("persona_layers", {}).get("type") == "world_state:persona_layers")

wires = {(b["name"], w["target"], w["mapping"]["from"], w["mapping"]["to"]) for b in wf["blocks"] for w in (b.get("connected_to") or [])}
check("get_message.sender → persona_layers", ("get_message", "persona_layers", "sender", "chat_sender") in wires)
check("dialogue_context.message_mode → persona_layers", ("dialogue_context", "persona_layers", "message_mode", "message_mode") in wires)
check("query_scene_context.text → persona_layers", ("query_scene_context", "persona_layers", "text", "current_scene") in wires)
check("persona_layers → 拼接人设与本群关系", ("persona_layers", "拼接人设与本群关系", "text", "text1") in wires)
check("拼接人设与本群关系 → 拼接当场上下文", ("拼接人设与本群关系", "拼接当场上下文", "text", "text1") in wires)
check("群友别名已从配置清除", "sine" not in (ROOT / "data" / "characters.yaml").read_text(encoding="utf-8"))

# 3. Token 估算（system prompt 侧）
always = "".join(
    (PERSONA / f).read_text(encoding="utf-8") for f in ("02_world_intro.txt", "04_runtime.txt", "05_update.txt")
)
tok = {k: ntok(v) for k, v in mods.items()}
scaffold = ntok(always)
old_full = ntok(core + lore + always)
print(f"\ntokenizer = {TOKENIZER}")
for k in ("base", "scene", "trigger", "companion"):
    print(f"{k:10s} {tok[k]:5d} tokens ({len(mods[k])} chars)")
print(f"{'scaffold':10s} {scaffold:5d} tokens  (02_world_intro + 04_runtime + 05_update，每轮必注)")
print(f"{'old-full':10s} {old_full:5d} tokens  (分层前每轮全量)")
print(f"\n普通群聊轮次: {tok['base'] + scaffold}")
print(f"@触发轮次   : {tok['base'] + tok['trigger'] + scaffold}")
print(f"Bot互聊轮次 : {tok['base'] + tok['companion'] + scaffold}")
print(f"含场景轮次  : {tok['base'] + tok['scene'] + scaffold}")
print(f"最坏(场景+@，已互斥): {tok['base'] + tok['trigger'] + scaffold}  （direct 不再叠 scene 模块）")

sys.exit(0 if ok else 1)
