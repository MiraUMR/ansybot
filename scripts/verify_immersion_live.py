#!/usr/bin/env python3
"""Verify immersion config + modules are live inside the container."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, "/usr/local/lib/python3.11/site-packages")

ok = True

def check( Cond, msg):
    global ok
    mark = "OK" if Cond else "FAIL"
    if not Cond:
        ok = False
    print(f"[{mark}] {msg}")

# 1) config
from kirara_ai.plugins.group_world_state.characters import (
    immersion_config,
    bot_qq_whitelist,
    is_registered_bot_qq,
)
imm = immersion_config()
check(imm.get("enabled") is True or imm.get("enabled") == True, f"immersion.enabled={imm.get('enabled')}")
check(int(imm.get("short_text_max_len") or 0) == 4, f"short_text_max_len={imm.get('short_text_max_len')}")
check(int(imm.get("scene_buffer_max") or 0) == 5, f"scene_buffer_max={imm.get('scene_buffer_max')}")
check(int(imm.get("narration_llm_min_len") or 0) == 12, f"narration_llm_min_len={imm.get('narration_llm_min_len')}")
check(int(imm.get("env_reply_chance") or 0) == 100, f"env_reply_chance={imm.get('env_reply_chance')}")
wl = bot_qq_whitelist()
check(wl == {"3845655536", "2246246527"} or wl >= {"3845655536", "2246246527"}, f"whitelist={sorted(wl)}")
check(is_registered_bot_qq("3845655536") and not is_registered_bot_qq("123"), "is_registered_bot_qq")

# 2) narration classify
from kirara_ai.plugins.group_world_state.narration import classify_human_utterance, wrap_template
check(classify_human_utterance("😀") == "discard", "emoji -> discard")
check(classify_human_utterance("今天天气不错") == "template", "short stmt -> template")
check(classify_human_utterance("你今天晚上到底打算吃什么啊感觉好纠结") == "llm", "long -> llm")
check(wrap_template("hi").startswith("[环境描写]"), "template wrap")

# 3) DialogueContext outputs exist
from kirara_ai.plugins.group_world_state.blocks import (
    DialogueContext,
    QuerySceneContext,
    AppendSceneContext,
    GatedChatMemoryStore,
    FilterFallbackMemory,
)
for cls, keys in [
    (DialogueContext, {"message_mode", "user_prompt_text", "skip_chat_memory", "narration"}),
    (QuerySceneContext, {"text"}),
    (GatedChatMemoryStore, set()),
    (FilterFallbackMemory, {"user_msg", "skip_chat_memory"}),
]:
    outs = set(getattr(cls, "outputs", {}) or {})
    miss = keys - outs
    check(not miss, f"{cls.__name__} outputs ok (missing={miss or 'none'})")

# 4) persona files on disk (mounted)
for char in ("anon", "soyo"):
    p = Path(f"/app/data/persona/{char}/04_runtime.txt")
    text = p.read_text(encoding="utf-8") if p.is_file() else ""
    check("{current_scene}" in text, f"{char}/04_runtime has {{current_scene}}")
    check("场景叙述理解" in text, f"{char}/04_runtime has 场景叙述规则")

# 5) characters.yaml immersion section
cy = Path("/app/data/characters.yaml").read_text(encoding="utf-8")
check("immersion:" in cy and "env_reply_chance" in cy, "characters.yaml has immersion block")

# 6) workflows contain gated blocks
for wf in ("anon.yaml", "soyo.yaml"):
    y = Path(f"/app/data/workflows/chat/{wf}").read_text(encoding="utf-8")
    check("world_state:gated_memory" in y, f"{wf} gated_memory")
    check("world_state:query_scene" in y, f"{wf} query_scene")
    check("world_state:append_scene" in y, f"{wf} append_scene")
    check("user_prompt_text" in y, f"{wf} user_prompt_text wire")
    check("{current_scene}" in y or "current_scene" in y, f"{wf} current_scene")

for wf in ("memory_store_anon.yaml", "memory_store_soyo.yaml"):
    y = Path(f"/app/data/workflows/chat/{wf}").read_text(encoding="utf-8")
    check("world_state:filter_fallback_memory" in y, f"{wf} filter_fallback")

# 7) patch: ChatMessageConstructor accepts user_prompt_text
from kirara_ai.workflow.implementations.blocks.llm import chat as chat_mod
src = inspect.getsource(chat_mod)
check("user_prompt_text" in src or "user_prompt_override" in src, "llm_chat patch has user_prompt override")
check("current_scene" in src or "user_prompt_text" in src, "llm_chat patch scene/prompt hooks")

print("OVERALL", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
