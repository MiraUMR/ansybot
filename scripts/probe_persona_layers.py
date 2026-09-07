"""容器内实测：PersonaLayers 在四种条件下拼出的模块组合。"""
import sys
from types import SimpleNamespace

sys.path.insert(0, "/usr/local/lib/python3.11/site-packages/kirara_ai/plugins")

from group_world_state.blocks import PersonaLayers, load_persona_module

block = PersonaLayers(character="soyo")
sender = SimpleNamespace(group_id="123456", raw_metadata={"im_name": "qq_soyo"}, user_id="9527")

SCENE = "<current_scene>\n有人在群里说今天很热\n</current_scene>"
CASES = [
    ("普通群聊 (env)", "env", ""),
    ("普通群聊 (空场景占位)", "env", "（暂无额外环境音。）"),
    ("@触发 (direct)", "direct", ""),
    ("Bot互聊 (peer)", "peer", ""),
    ("含场景 (env+scene)", "env", SCENE),
    ("@触发+场景，场景模块应被互斥", "direct", SCENE),
]

marks = {
    "base": "你就是长崎素世本人",
    "trigger": "[SYSTEM: EXTERNAL_TRIGGER] 标签触发",
    "companion": "## 与小爱音互聊",
    "scene": "# 场景记忆读取规则",
}

for label, mode, scene in CASES:
    text = block.execute(chat_sender=sender, message_mode=mode, current_scene=scene)["text"]
    hit = "+".join(k for k, v in marks.items() if v in text)
    print(f"{label:22s} mode={mode:7s} scene={'yes' if scene and '暂无' not in scene else 'no ':3s} -> {hit:30s} {len(text)} chars")

print()
print("base 缓存命中:", load_persona_module("soyo", "base") is load_persona_module("soyo", "base"))
print("anon 无模块时降级为空:", repr(load_persona_module("anon", "base")))
