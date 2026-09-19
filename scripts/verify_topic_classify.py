"""验收：hybrid 话题分类 + 爱好模块按命中注入（不依赖 kirara_ai）。"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "group_world_state"
os.chdir(ROOT)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


for pkg in (
    "kirara_ai",
    "kirara_ai.llm",
    "kirara_ai.llm.format",
    "kirara_ai.llm.format.message",
    "kirara_ai.llm.format.request",
    "kirara_ai.llm.format.response",
    "kirara_ai.llm.llm_manager",
):
    if pkg not in sys.modules:
        sys.modules[pkg] = types.ModuleType(pkg)
sys.modules["kirara_ai.llm.format.message"].LLMChatMessage = object
sys.modules["kirara_ai.llm.format.message"].LLMChatTextContent = object
sys.modules["kirara_ai.llm.format.request"].LLMChatRequest = object
sys.modules["kirara_ai.llm.format.response"].LLMChatResponse = object
sys.modules["kirara_ai.llm.llm_manager"].LLMManager = object

topic = load("topic_classify_v2", PLUGIN / "topic_classify.py")
guard = load("style_guard_v2", PLUGIN / "style_guard.py")


def check(label: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {label}{(' :: ' + extra) if extra else ''}")
    if not cond:
        sys.exit(1)


# force keyword-only for offline deterministic tests
for char in ("anon", "soyo"):
    doc = topic.load_hobbies_doc(char)
    det = dict(doc.get("detector") or {})
    det["mode"] = "keyword"
    topic.save_hobbies_doc(char, {"detector": det, "categories": doc["categories"]})

h1 = topic.classify_text("anon", "新闻三要素要成真一个了吗")
check("用例1 idle", h1.category_id == "idle_ambient", f"got={h1.category_id}")

lock = topic.topic_lock_text("anon", h1, mode="env")
check("idle 结构化锁", "[TOPIC_LOCK]" in lock and "ACTION: deflect" in lock)
check("idle 不注入爱好包", "[HOBBY_CONTEXT]" not in lock and "[HOBBY_PACK]" not in lock)
check("idle 不注入吉他事实", "ESP_ULTRATONE" not in lock)
lock_d = topic.topic_lock_text("anon", h1, mode="direct", source_text="哈哈")
check("idle @接眼前这句", "ACTION: reply_this_line" in lock_d and "answer_now_doing" not in lock_d)
lock_q = topic.topic_lock_text("anon", h1, mode="direct", source_text="你在干嘛")
check("idle 被问才报正在做", "ACTION: answer_now_doing" in lock_q)

h2 = topic.classify_text("anon", "今晚吉他排练别迟到")
check("用例2 band", h2.category_id == "band_practice", f"got={h2.category_id}")
lock2 = topic.topic_lock_text("anon", h2, mode="direct")
check("band 注入乐队模块", "ESP_ULTRATONE" in lock2 or "MyGO_rhythm_guitarist" in lock2)
check("band 不注入红茶模块", "darjeeling" not in lock2 and "veggie_macaroni" not in lock2)

h3 = topic.classify_text("anon", "原神抽卡了吗")
check("用例3 ignore", h3.category_id == "game_blocked", f"got={h3.category_id}")

h4 = topic.classify_text("soyo", "要不要喝杯红茶")
check("用例4 food", h4.category_id == "food", f"got={h4.category_id}")
lock4 = topic.topic_lock_text("soyo", h4, mode="peer")
check("food 注入红茶模块", "红茶" in lock4)

# restore hybrid mode
for char in ("anon", "soyo"):
    doc = topic.load_hobbies_doc(char)
    det = dict(doc.get("detector") or {})
    det["mode"] = "hybrid"
    det.setdefault("embed_model", "text-embedding-v3")
    det.setdefault("embed_threshold", 0.45)
    det.setdefault("keyword_min_score", 8)
    topic.save_hobbies_doc(char, {"detector": det, "categories": doc["categories"]})

anon_base_path = ROOT / "data/persona/anon/modules/anon_base.md"
if anon_base_path.is_file():
    anon_base = anon_base_path.read_text(encoding="utf-8")
    check("base 已去掉爱好分层长文", "【高共鸣话题】" not in anon_base)
    check("base 指向爱好设定", "爱好设定" in anon_base)

routes = (PLUGIN / "persona_routes.py").read_text(encoding="utf-8")
ui = (PLUGIN / "persona_ui.html").read_text(encoding="utf-8")
check("API hobbies", "/hobbies/" in routes and "save_hobby_module" in routes)
check("API pack codec", "parse_hobby_pack" in routes and "format_hobby_pack" in routes)
check("UI 爱好栏", "爱好设定" in ui and "hobbyPanel" in ui)
check("UI 条目编辑", all(x in ui for x in ("hFacts", "hAllow", "hForbidPolicy", "hBehaviors", "hExOk", "hExBad", "data-add", "实际意思")))
check("UI 爱好隐藏大文本", 'editor.classList.add("hidden")' in ui)

raw = topic.load_hobby_module("anon", "band_practice")
parsed = topic.parse_hobby_pack(raw)
allow_vals = topic.item_values(parsed.get("allow"))
ex_ok_vals = topic.item_values(parsed.get("ex_ok"))
check("parse allow", "rehearsal" in allow_vals, f"allow={parsed.get('allow')}")
check("parse ex_ok", any("再来一遍" in x for x in ex_ok_vals), f"ex_ok={parsed.get('ex_ok')}")
roundtrip = topic.parse_hobby_pack(topic.format_hobby_pack(parsed))
check(
    "format roundtrip allow",
    set(topic.item_values(parsed.get("allow"))) == set(topic.item_values(roundtrip.get("allow"))),
    f"{parsed.get('allow')} vs {roundtrip.get('allow')}",
)
check(
    "format roundtrip ex_ok",
    topic.item_values(parsed.get("ex_ok")) == topic.item_values(roundtrip.get("ex_ok")),
    f"{parsed.get('ex_ok')} vs {roundtrip.get('ex_ok')}",
)

noted = topic.format_hobby_pack({
    "id": "t",
    "stance": "soft",
    "facts": [{"key": "role", "value": "bassist", "note": "乐队贝斯"}],
    "allow": [{"value": "rehearsal", "note": "可以聊排练"}],
    "forbid": [],
    "tone": [],
    "behaviors": [{"value": "IF hit THEN short", "note": "命中短回"}],
    "ex_ok": [{"value": "今天练到九点。", "note": "干脆"}],
    "ex_bad": [],
})
noted_p = topic.parse_hobby_pack(noted)
check("note in pack text", " :: 可以聊排练" in noted)
check(
    "note roundtrip",
    (noted_p.get("allow") or [{}])[0].get("note") == "可以聊排练"
    and (noted_p.get("facts") or [{}])[0].get("key") == "role",
    f"{noted_p}",
)

bad = "反正我眼里现在只有这把吉他的音准"
hits = guard.find_character_violations("anon", bad, env_mode=True, topic_idle=True)
check("idle 硬切仍拦截", any("idle硬切" in x for x in hits), f"hits={hits}")

check("detector hybrid 已写回", topic.load_hobbies_doc("anon")["detector"].get("mode") == "hybrid")
print("ALL PASS")
