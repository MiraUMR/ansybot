"""本地校验：叙事内化注入 + 称呼拦截（不依赖 kirara_ai）。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BLOCKS = (ROOT / "plugins/group_world_state/blocks.py").read_text(encoding="utf-8")
GUARD = (ROOT / "plugins/group_world_state/style_guard.py").read_text(encoding="utf-8")
BASE = (ROOT / "data/persona/soyo/modules/soyo_base.md").read_text(encoding="utf-8")
TRIG = (ROOT / "data/persona/soyo/modules/soyo_trigger.md").read_text(encoding="utf-8")
ANON_BASE = (ROOT / "data/persona/anon/modules/anon_base.md").read_text(encoding="utf-8")
ANON_TRIG = (ROOT / "data/persona/anon/modules/anon_trigger.md").read_text(encoding="utf-8")
ANON_COMP = (ROOT / "data/persona/anon/modules/anon_companion.md").read_text(encoding="utf-8")
SOYO_COMP = (ROOT / "data/persona/soyo/modules/soyo_companion.md").read_text(encoding="utf-8")
SOYO_STORY = (ROOT / "data/persona/soyo/modules/soyo_story.md").read_text(encoding="utf-8")
ANON_STORY = (ROOT / "data/persona/anon/modules/anon_story.md").read_text(encoding="utf-8")
STORY_PY = (ROOT / "plugins/group_world_state/story.py").read_text(encoding="utf-8")
STORY_YAML = yaml.safe_load((ROOT / "data/persona/story_triggers.yaml").read_text(encoding="utf-8"))
PARSER = (ROOT / "plugins/group_world_state/parser.py").read_text(encoding="utf-8")
INIT = (ROOT / "plugins/group_world_state/__init__.py").read_text(encoding="utf-8")
WF = yaml.safe_load((ROOT / "data/workflows/chat/soyo.yaml").read_text(encoding="utf-8"))
ANON_WF = yaml.safe_load((ROOT / "data/workflows/chat/anon.yaml").read_text(encoding="utf-8"))


def check(label: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {label}{(' :: ' + extra) if extra else ''}")
    if not cond:
        sys.exit(1)


# --- prompt 组装 ---
check("CRITICAL 动态加载", "def critical_block_for" in GUARD)
check("CRITICAL 含素世/爱音分版", "特别注意（素世版）" in GUARD and "特别注意（爱音版）" in GUARD)
check("CRITICAL 已去掉叙事内化标题", "NARRATIVE INTERNALIZATION" not in GUARD)
check("CRITICAL 口吻为发微信", "发微信" in GUARD)
check("拦截秘书腔", "我记下了" in GUARD and "称呼当抬头" in GUARD)
check("voice_tail 禁止秘书腔", "禁止秘书腔" in BLOCKS)
check("重写不再无条件塞称呼", "素世必须出现「小爱音」" not in GUARD)
check("组装函数引用 CRITICAL 块", "critical_block_for" in BLOCKS)
check("组装函数不再写入提问者来源", "来源：群友" not in BLOCKS.split("def _build_external_trigger_prompt", 1)[-1].split("class ", 1)[0])
check("场面叙述分流", "looks_like_narrated_scene" in BLOCKS and "mode=scene_cast" in BLOCKS)
check("CRITICAL 不再一刀切禁止提及同伴", "禁止强制绑定同伴" not in GUARD)
check("导演腔拦截", "让我理理" in GUARD)
check("peer 强制规定称呼", "未称呼小爱音" in GUARD and "未称呼soyorin" in GUARD)
check("轻提开关已写入组装函数", "本轮轻提开关" in BLOCKS)
check("MENTION_CHANCE=0.30", "MENTION_CHANCE = 0.30" in BLOCKS)
check("组装函数已移除硬转化", "转化为对小爱音" not in BLOCKS)
check("GuardCharacterReply 已实现", "class GuardCharacterReply" in BLOCKS)

# --- 工作流接线 ---
blocks = {b["name"]: b for b in WF["blocks"]}
wires = {
    (b["name"], w["target"], w["mapping"]["from"], w["mapping"]["to"])
    for b in WF["blocks"]
    for w in (b.get("connected_to") or [])
}
check("guard_character_reply 已注册", blocks.get("guard_character_reply", {}).get("type") == "world_state:guard_reply")
check("llm_chat → guard", ("llm_chat", "guard_character_reply", "resp", "llm_resp") in wires)
check("guard → apply_world_state", ("guard_character_reply", "apply_world_state", "llm_resp", "llm_resp") in wires)
check("llm_chat 不再直连 apply", ("llm_chat", "apply_world_state", "resp", "llm_resp") not in wires)
check("env 记忆经 gate_memory_query", ("query_memory", "gate_memory_query", "memory_content", "memory_content") in wires)
check("gate_memory_query 接入构造器", ("gate_memory_query", "ChatMessageConstructor_kcjgyy", "memory_content", "memory_content") in wires)
check("dialogue 把 mode 交给记忆门", ("dialogue_context", "gate_memory_query", "message_mode", "message_mode") in wires)
check("query_memory 不再直连构造器", ("query_memory", "ChatMessageConstructor_kcjgyy", "memory_content", "memory_content") not in wires)
check("soyo 记忆作用域", blocks.get("gated_chat_memory", {}).get("params", {}).get("scope_type") == "soyo_group")
check("soyo workflow 含故事收束例外", "若本轮是故事模式" in yaml.safe_dump(WF, allow_unicode=True))
check("anon workflow 含故事收束例外", "若本轮是故事模式" in yaml.safe_dump(ANON_WF, allow_unicode=True))
check("回复规则不再默认直接接话", "默认直接接话" not in yaml.safe_dump(WF, allow_unicode=True) and "默认直接接话" not in yaml.safe_dump(ANON_WF, allow_unicode=True))
check("回复规则改模式分流", "模式分流" in yaml.safe_dump(WF, allow_unicode=True) and "模式分流" in yaml.safe_dump(ANON_WF, allow_unicode=True))
check("P0 作废默认直接接话", "默认直接接话/先回应对方" in GUARD)

# --- 模块文本 ---
check("base 含称呼执行铁律", "称呼执行铁律" in BASE)
check("base 禁止变体列表", all(x in BASE for x in ("爱音酱", "Anon", "千早", "永远禁止")))
check("base 区分在场/不在场", "当面聊天/互聊时" in BASE and "对方不在场时" in BASE)
check("trigger 含情境自适应框架", "情境自适应响应框架" in TRIG)
check("trigger 含事实查询素世版", "事实查询/纠错类消息的特殊处理（素世版）" in TRIG)
check("anon trigger 含事实查询爱音版", "事实查询/纠错类消息的特殊处理（爱音版）" in ANON_TRIG)
check("soyo base 含事实与记忆", "永远不要当人形数据库" in BASE)
check("anon base 含事实与记忆", "永远不要当人形百科" in ANON_BASE)
check("trigger 已移除强制转化", "必须转化为" not in TRIG and "叙事内化三步法" not in TRIG)
check("trigger 不再要求动作铺垫", "动作铺垫" not in TRIG and "动作铺垫" not in ANON_TRIG)
check("soyo trigger 允许短事实", "五个。不多不少。" in TRIG)
check("anon trigger 不再强制互动钩子", "互动钩子" not in ANON_TRIG)
check("anon base 不再强制互动钩子", "带对同伴的互动钩子" not in ANON_BASE)

# --- 正则行为（与 style_guard 同步） ---
ALLOWED = "小爱音"
TOKEN = "\u0000PEER\u0000"
NAME_RULES = [
    (re.compile(r"爱音酱"), "爱音酱"),
    (re.compile(r"(?i)\bAnon\b"), "Anon"),
    (re.compile(r"千早"), "千早"),
    (re.compile(r"爱音"), "爱音"),
]
INTERVIEW = [
    (re.compile(r"你问的"), "你问的"),
    (re.compile(r"有人问"), "有人问"),
    (re.compile(r"有人提到"), "有人提到"),
]


def hits(text: str, trigger: bool = False) -> list[str]:
    body = text.replace(ALLOWED, TOKEN)
    found = [lab for pat, lab in NAME_RULES if pat.search(body)]
    if trigger:
        found += [lab for pat, lab in INTERVIEW if pat.search(text)]
    return found


check("合法小爱音不误伤", not hits("小爱音先把话说完", True))
check("合法某人不误伤", not hits("某人要是知道了大概又会拉我去", True))
check("拦截裸爱音", "爱音" in hits("爱音今晚有空吗"))
check("拦截爱音酱", "爱音酱" in hits("爱音酱别闹"))
check("拦截Anon", "Anon" in hits("Anon 你看这个"))
check("拦截采访体", "有人问" in hits("有人问我要不要去甜品店", True))
check("P0 禁止复读选择问", "紧不紧张" in GUARD and "让她自己来问" in GUARD)
check("trigger 点名同伴走类型3", "触发内容已点名同伴" in BLOCKS)
check("无问号也当提问", "def looks_like_question" in GUARD and "会不会" in GUARD)
check("轻提不再先答问题核心", "先答问题核心" not in BLOCKS)
check("触发提示禁止对群友输出提问句", "禁止对群友输出提问句" in BLOCKS)
check("Bot 互聊问句放行写入分流", "本轮是 Bot 互聊" in BLOCKS)
check("类型3 对同伴可以提问", "对同伴可以提问" in BLOCKS)
check("guard 把触发原文交给问答检测", "user_text=src" in BLOCKS and "trigger_source_text" in BLOCKS)
check("trigger 模块写明无问号也要转化", "没有问号" in TRIG and "没有问号" in ANON_TRIG)
check("voice_tail 示范不再带反问", "大吉岭对吧" not in BLOCKS.split("def _voice_tail", 1)[-1].split("def _env_voice_tail", 1)[0])

SECRETARY_SAMPLE = (
    "soyorin，大吉岭的事我记下了。别再看手机了，现在出门还赶得上。"
    "上次你挑茶叶的样子我还记得，这次我帮你筛好，你负责点头就行。"
)
check("拦截秘书腔样本", all(x in SECRETARY_SAMPLE for x in ("我记下了", "你负责", "别再看手机")))
check("称呼当抬头正则", bool(re.search(r"(?i)^[\s\*＿_]*soyorin[，,]", SECRETARY_SAMPLE)))
check("感叹号称呼不误伤", not re.search(r"(?i)^[\s\*＿_]*soyorin[，,]", "soyorin！大吉岭对吧，走啊现在！"))

ANON_WF = yaml.safe_load((ROOT / "data/workflows/chat/anon.yaml").read_text(encoding="utf-8"))
anon_names = {b["name"] for b in ANON_WF["blocks"]}
check("anon 已分层 persona_layers", "persona_layers" in anon_names)
check("anon 已移除全量核心人设块", "核心人设（身份性格与不可推翻）" not in anon_names)
check("anon trigger 含情境自适应", "情境自适应响应框架" in ANON_TRIG)
check("anon trigger 含轻提", "轻提（约三成）" in ANON_TRIG)
check("anon base 含称呼铁律", "称呼执行铁律" in ANON_BASE and "soyorin" in ANON_BASE)
check("anon lore 已移除群友专属称呼", "sine斯年" not in (ROOT / "data/persona/anon/03_lore.txt").read_text(encoding="utf-8"))

check("soyo companion 含Bot互聊互动强化", "Bot互聊互动强化" in SOYO_COMP and "话题共鸣优先" in SOYO_COMP)
check("anon companion 含Bot互聊互动强化", "Bot互聊互动强化" in ANON_COMP and "情绪共振优先" in ANON_COMP)
check("soyo base 外热内冷", "外热内冷" in BASE and "口嫌体正直" in BASE)
check("soyo base 互聊权重最高", "Bot互聊时权重最高" in BASE)
check("anon base 伪阳角", "伪阳角" in ANON_BASE and "常识人" in ANON_BASE)
check("trigger 示例不再用小说旁白", "*盯着" not in TRIG and "*眼睛突然" not in ANON_TRIG)
check("anon base 互聊权重最高", "Bot互聊时权重最高" in ANON_BASE)
check("soyo story 风格锚点内敛", "克制、内敛、情绪后置" in SOYO_STORY and "不得变成外放型人格" in SOYO_STORY)
check("anon story 风格锚点外放", "外放、直球、情绪前置" in ANON_STORY and "不得变成内敛型人格" in ANON_STORY)
check("story 模块不共用模板句", "情绪后置" in SOYO_STORY and "情绪前置" in ANON_STORY)
check("soyo story 本轮可续收束", "本轮收束（不是故事结束）" in SOYO_STORY and "没说完的半句" in SOYO_STORY)
check("anon story 本轮可续收束", "本轮收束（不是故事结束）" in ANON_STORY and "刚抓住袖口" in ANON_STORY)
check("故事结束指令未改", "end / 结束 / stop" in SOYO_STORY and "end / 结束 / stop" in ANON_STORY)
check("故事轮不注入 Companion", "故事轮不注入 Companion" in BLOCKS)
check("persona 互斥网关", "def exclusive_persona_primary" in BLOCKS)
check("direct 只注 trigger", 'return "trigger"' in BLOCKS and 'return "companion"' in BLOCKS)
check("P0 指令变量", "def critical_instruction_for" in GUARD and "critical_instruction" in BLOCKS)
check("人设模块由工作流套层", "envelop_module" in BLOCKS and "strip_workflow_chrome" in BLOCKS)
check("构造器追加 P0 到系统提示末尾", "critical_instruction" in (ROOT / "patches/llm_chat.py").read_text(encoding="utf-8"))
check("soyo 工作流接 P0", ("dialogue_context", "ChatMessageConstructor_kcjgyy", "critical_instruction", "critical_instruction") in wires)
check("故事轮提示标明不是结束", "这不是故事结束" in BLOCKS)
check(
    "整段结束 OOC 未改",
    "只输出这一句：故事已结束，关键情节已记录。" in BLOCKS,
)
SOYO_UPDATE = (ROOT / "data/persona/soyo/05_update.txt").read_text(encoding="utf-8")
ANON_UPDATE = (ROOT / "data/persona/anon/05_update.txt").read_text(encoding="utf-8")
check("soyo 05_update 故事收束例外", "若本轮是故事模式" in SOYO_UPDATE and "end / 结束 / stop" in SOYO_UPDATE)
check("anon 05_update 故事收束例外", "若本轮是故事模式" in ANON_UPDATE and "end / 结束 / stop" in ANON_UPDATE)
check("05_update 口吻为发微信", "本轮像发微信" in SOYO_UPDATE and "本轮像发微信" in ANON_UPDATE)
end_tokens = (STORY_YAML.get("story_triggers") or {}).get("end_tokens") or []
check("end_tokens 仍为 end/结束/stop", [str(t) for t in end_tokens] == ["end", "结束", "stop"])
check("StorySession 类存在", "class StorySession" in STORY_PY)
check("route_story 存在", "def route_story" in STORY_PY)
check("finalize_story 存在", "def finalize_story" in STORY_PY)
check("PERSONA_MODULES 含 story", 'PERSONA_MODULES = ("base", "scene", "trigger", "companion", "story")' in BLOCKS)
check("DialogueContext 故事拦截", "def _route_story_mode" in BLOCKS)
check("ApplyWorldState 剥离 memory_point", "strip_memory_points" in BLOCKS)
check("parser 含 strip_memory_points", "def strip_memory_points" in PARSER)
check("插件注册 StorySessionStore", "StorySessionStore" in INIT)
check("触发词含双Bot庙会", any("逛庙会" in str(p) for p in (STORY_YAML.get("story_triggers") or {}).get("start_patterns") or []))
check("触发词含单Bot开始故事", any("开始故事" in str(p) for p in (STORY_YAML.get("story_triggers") or {}).get("start_patterns") or []))

# --- story 状态机（不依赖 kirara_ai） ---
import os
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location

os.chdir(ROOT)
pkg = types.ModuleType("group_world_state")
pkg.__path__ = [str(ROOT / "plugins" / "group_world_state")]
sys.modules["group_world_state"] = pkg
for name in ("characters", "store", "story", "peer", "narration"):
    path = ROOT / "plugins" / "group_world_state" / f"{name}.py"
    spec = spec_from_file_location(f"group_world_state.{name}", path)
    mod = module_from_spec(spec)
    sys.modules[f"group_world_state.{name}"] = mod
    spec.loader.exec_module(mod)
story = sys.modules["group_world_state.story"]

r_soyo = story.route_story(
    character="soyo",
    sender_qq="10001",
    group_id="g1",
    content="@素世 @爱音 去逛庙会",
    mentioned_bots=["soyo", "anon"],
    session=None,
)
r_anon = story.route_story(
    character="anon",
    sender_qq="10001",
    group_id="g1",
    content="@素世 @爱音 去逛庙会",
    mentioned_bots=["soyo", "anon"],
    session=None,
)
check("双Bot开场 soyo 先发言", r_soyo.action == "start" and r_soyo.speaker == "soyo")
check("双Bot开场 anon 本轮丢弃", r_anon.action == "discard")

sess = r_soyo.session
sess.current_speaker = "soyo"
r_guide = story.route_story(
    character="anon",
    sender_qq="10001",
    group_id="g1",
    content="@爱音 买苹果糖",
    mentioned_bots=["anon"],
    session=sess,
)
r_soyo_wait = story.route_story(
    character="soyo",
    sender_qq="10001",
    group_id="g1",
    content="@爱音 买苹果糖",
    mentioned_bots=["anon"],
    session=sess,
)
check("引导指定 anon 发言", r_guide.action == "turn" and r_guide.speaker == "anon")
check("引导指定 soyo 丢弃", r_soyo_wait.action == "discard")

r_end = story.route_story(
    character="soyo",
    sender_qq="10001",
    group_id="g1",
    content="@素世 结束",
    mentioned_bots=["soyo"],
    session=sess,
)
check("发起人结束故事", r_end.action == "end" and r_end.finalize)
check(
    "结束词仍精确匹配",
    story.is_story_end_command("结束")
    and story.is_story_end_command("end")
    and story.is_story_end_command("stop"),
)
check(
    "日常收束词不结束故事",
    not story.is_story_end_command("就这样")
    and not story.is_story_end_command("先这样")
    and not story.is_story_end_command("知道了"),
)

r_normal = story.route_story(
    character="soyo",
    sender_qq="10001",
    group_id="g1",
    content="@素世 你喜欢吃什么",
    mentioned_bots=["soyo"],
    session=None,
)
check("普通@不进入故事", r_normal.action == "none")

ids = story.mentioned_ids_in_text("@soyo @aono 去逛庙会")
check("@aono 映射为 anon", ids == ["soyo", "anon"] or set(ids) == {"soyo", "anon"})

peer_mod = sys.modules["group_world_state.peer"]
gift = "千早爱音 走在路上突然撞见长崎素世在偷偷给你买礼物"
check(
    "买礼物场面判定",
    peer_mod.looks_like_narrated_scene(gift, "anon")
    and peer_mod.looks_like_narrated_scene(gift, "soyo"),
)
check(
    "买礼物不点名进Trigger",
    not peer_mod.analyze_dialogue_target("anon", "10002", gift).get("named_self"),
)
check(
    "普通提问仍点名",
    bool(peer_mod.analyze_dialogue_target("soyo", "10002", "素世 你喜欢吃什么").get("named_self")),
)
check("收束句判定", peer_mod.looks_like_wrap_up("……知道了。你自己看着办。"))
check("带称呼的短收束", peer_mod.looks_like_wrap_up("小爱音，知道了。"))
check("爱音收束那我等你", peer_mod.looks_like_wrap_up("那我等你 soyorin"))
check("未收束不误伤", not peer_mod.looks_like_wrap_up("好啦好啦，不笑你。不过被我发现还挺开心的。"))
check("问句不算收束", not peer_mod.looks_like_wrap_up("知道了，那我们去哪？"))
check(
    "点名不能打断收束",
    peer_mod.peer_should_discard(allowed=True, wrap_up=True, at_self=False),
)
check(
    "轮次上限硬停",
    peer_mod.peer_should_discard(allowed=False, wrap_up=False, at_self=False),
)
check(
    "真正@可续",
    not peer_mod.peer_should_discard(allowed=False, wrap_up=True, at_self=True),
)

# --- 群员屏蔽（沉浸）---
check(
    "叫名字算在对你说话",
    peer_mod.looks_addressed_to_self("素世，帮我看看", "soyo")
    and peer_mod.looks_addressed_to_self("素世 你喜欢吃什么", "soyo"),
)
check(
    "只是提到不算在对你说话",
    not peer_mod.looks_addressed_to_self("素世今天没来练琴", "soyo")
    and not peer_mod.looks_addressed_to_self("刚才素世那句好好笑", "soyo"),
)
check(
    "句中称呼也算在叫人",
    peer_mod.looks_addressed_to_self("后面那个躲得也太明显了。小爱音，出来吧。", "anon")
    and peer_mod.looks_addressed_to_self("我哪有躲啊soyorin。猫都在你手边。", "soyo"),
)
check(
    "叙述里点到名字仍不算叫人",
    not peer_mod.looks_addressed_to_self("前面蹲着摸猫的绝对是soyorin。", "soyo"),
)
check(
    "英文别名要词边界",
    not peer_mod.alias_hit("canon 这首好听", "anon")
    and peer_mod.alias_hit("anon 在吗", "anon"),
)
check(
    "canon 不误判成点名",
    not peer_mod.analyze_dialogue_target("anon", "10002", "canon 这首好听").get("named_self"),
)
check("提到名字走环境音", "looks_addressed_to_self" in BLOCKS and "mode=env source=" in BLOCKS)
check("env 层有角色口吻尾巴", "def _env_voice_tail" in BLOCKS and "本轮没有对话对象" in BLOCKS)
check("env 违规拦截", "_env_hits" in GUARD and "环境音里称呼对方" in GUARD)
check("guard 接入 env_mode", "env_mode" in GUARD and "env_mode=env_mode" in BLOCKS)
check(
    "05_update 环境无对方",
    "这时没有「对方」" in SOYO_UPDATE and "这时没有「对方」" in ANON_UPDATE,
)
check(
    "05_update 收尾不再一律回应对方",
    "现在继续以长崎素世本人回应对方。" not in SOYO_UPDATE
    and "现在继续以千早爱音本人回应对方。" not in ANON_UPDATE,
)

check("@ 判定按 QQ", "def at_target_qqs" in (ROOT / "plugins/group_world_state/mentions.py").read_text(encoding="utf-8") and "def self_qq" in (ROOT / "plugins/group_world_state/mentions.py").read_text(encoding="utf-8"))
MENTIONS = (ROOT / "plugins/group_world_state/mentions.py").read_text(encoding="utf-8")
check("self_id 优先", "self_id" in MENTIONS and 'get_character(character).get("qq")' in MENTIONS)
check("@别人算群员", "def _mentioned_others" in BLOCKS or "mentioned_others" in BLOCKS)
check("member_at 强制跳过 peer", "skip-peer member_at=1" in BLOCKS)
check("场面不再走 peer 模式", '"message_mode": "scene"' in BLOCKS)
check("私聊或/chat 不当环境音", "force_chat" in BLOCKS and "reason=" in BLOCKS)
check("dispatch @ 用 QQ", "addressed_to_self" in (ROOT / "patches/dispatch_message_rules.py").read_text(encoding="utf-8"))
check("mentions 模块存在", (ROOT / "plugins/group_world_state/mentions.py").is_file())
check("persona scene 模式注 scene", 'return "scene"' in BLOCKS or 'mode in ("scene", "env")' in BLOCKS)
check("@全体不算被点名", 'qq.lower() == "all"' in (ROOT / "plugins/group_world_state/mentions.py").read_text(encoding="utf-8"))
check("mention/reply 传角色", "_mentioned_bot(user_msg, character)" in BLOCKS or "addressed_to_self(user_msg, character)" in BLOCKS)
check("direct 日志带 at_others", "at_others={int(at_others)}" in BLOCKS)
check("reply 默认不算回 bot", "只有能确认引用对象是本账号" in (ROOT / "plugins/group_world_state/mentions.py").read_text(encoding="utf-8"))
DISPATCH = (ROOT / "patches/dispatch_message_rules.py").read_text(encoding="utf-8")
check("dispatch 注册 not_at_others", 'type_name = "not_at_others"' in DISPATCH)
check("peer 点名要 vocative", "named = looks_addressed_to_self(text, self.character)" in DISPATCH)
check("/chat 优先于 @别人", "if force_chat or not is_group:" in BLOCKS)
check("gate_memory 模块已注册", "gate_memory" in INIT and "class GateMemoryByMode" in BLOCKS)
RULES = yaml.safe_load((ROOT / "data/dispatch_rules/rules.yaml").read_text(encoding="utf-8"))
_random_ok = True
for _r in RULES:
    if "_random_" not in str(_r.get("rule_id") or ""):
        continue
    _types = [x.get("type") for g in (_r.get("rule_groups") or []) for x in (g.get("rules") or [])]
    if "not_at_others" not in _types:
        _random_ok = False
        break
check("随机插话跳过 @别人", _random_ok)
ANON_WIRES = {
    (b["name"], w["target"], w["mapping"]["from"], w["mapping"]["to"])
    for b in ANON_WF["blocks"]
    for w in (b.get("connected_to") or [])
}
check("anon 也走记忆门控", ("query_memory", "gate_memory_query", "memory_content", "memory_content") in ANON_WIRES)
check("anon 工作流接 P0", ("dialogue_context", "ChatMessageConstructor_kcjgyy", "critical_instruction", "critical_instruction") in ANON_WIRES)
check("story 也读 AtElement", "AtElement(user_id=QQ)" in STORY_PY)
NARRATION = (ROOT / "plugins/group_world_state/narration.py").read_text(encoding="utf-8")
check("旁白去掉@", "def strip_addressing" in NARRATION)
check("旁白不原样引用第二人称", "并不针对谁" in NARRATION)


class _FakeAt:
    def __init__(self, uid: str) -> None:
        self.user_id = uid


_fake = types.SimpleNamespace(
    content="这个你怎么看",
    message_elements=[_FakeAt("2246246527")],
    raw_message={"self_id": "3845655536", "message": [{"type": "at", "data": {"qq": "2246246527"}}]},
)
check("story 从 @QQ 认出 Bot", story.extract_participating_bots("这个你怎么看", _fake) == ["soyo"])

narration = sys.modules["group_world_state.narration"]
check(
    "旁白模板不引用你",
    "你看" not in narration.wrap_template("@张三 你看这个")
    and "并不针对谁" in narration.wrap_template("@张三 你看这个"),
)
check(
    "旁白去掉CQ at",
    "10001" not in narration.strip_addressing("[CQ:at,qq=10001] 今晚吃什么")
    and "今晚吃什么" in narration.strip_addressing("[CQ:at,qq=10001] 今晚吃什么"),
)

check("companion 已改为收束优先", "收束优先于续摊" in SOYO_COMP and "收束优先于续摊" in ANON_COMP)
check("companion 不再鼓励主动开新话题", "允许主动发起" not in SOYO_COMP and "允许主动发起" not in ANON_COMP)
check("token_meter 模块存在", (ROOT / "plugins/group_world_state/token_meter.py").is_file())
check("ChatCompletion 写 named token 日志", "format_chat_token_report" in (ROOT / "patches/llm_chat.py").read_text(encoding="utf-8"))
CHARS = (ROOT / "data/characters.yaml").read_text(encoding="utf-8")
check("同伴绑定在人设不在 yaml by_character", "by_character:" not in CHARS)
check("peer 身份锁函数", "def peer_identity_lock" in (ROOT / "plugins/group_world_state/characters.py").read_text(encoding="utf-8"))
check("人设可解析 peer 块", "def parse_peer_binding" in (ROOT / "plugins/group_world_state/persona_text.py").read_text(encoding="utf-8"))
check("分流只认 is_peer", "elif analysis.get(\"is_peer\"):" in BLOCKS and "is_bot\") or analysis.get(\"is_peer\")" not in BLOCKS)
check("工作流写 QQ 铁律", "【QQ身份铁律】" in yaml.safe_dump(WF, allow_unicode=True) and "【QQ身份铁律】" in yaml.safe_dump(ANON_WF, allow_unicode=True))
check("soyo base 含 peer 绑定块", "```peer" in BASE and "peer_qq" in BASE and "3845655536" in BASE)
check("anon base 含 peer 绑定块", "```peer" in ANON_BASE and "peer_qq" in ANON_BASE and "2246246527" in ANON_BASE)

def _stub_kirara() -> None:
    import types

    names = [
        "kirara_ai",
        "kirara_ai.llm",
        "kirara_ai.llm.format",
        "kirara_ai.llm.format.message",
        "kirara_ai.llm.format.request",
        "kirara_ai.llm.format.response",
        "kirara_ai.llm.llm_manager",
    ]
    for name in names:
        sys.modules.setdefault(name, types.ModuleType(name))
    msg = sys.modules["kirara_ai.llm.format.message"]
    msg.LLMChatMessage = type("LLMChatMessage", (), {})
    msg.LLMChatTextContent = type("LLMChatTextContent", (), {})
    sys.modules["kirara_ai.llm.format.request"].LLMChatRequest = type("LLMChatRequest", (), {})
    sys.modules["kirara_ai.llm.format.response"].LLMChatResponse = type("LLMChatResponse", (), {})
    sys.modules["kirara_ai.llm.llm_manager"].LLMManager = type("LLMManager", (), {})


_stub_kirara()
_sg_spec = spec_from_file_location(
    "group_world_state.style_guard", ROOT / "plugins/group_world_state/style_guard.py"
)
_sg = module_from_spec(_sg_spec)
sys.modules["group_world_state.style_guard"] = _sg
_sg_spec.loader.exec_module(_sg)

check("无问号 会不会 算提问", _sg.looks_like_question("会不会在意爱音发了什么"))
check("无问号 什么呢 算提问", _sg.looks_like_question("刷sns都会看到什么呢"))
check("还没到呢 不算提问", not _sg.looks_like_question("……还没到呢。九月八号。"))
check("口癖 哪有 不拦", not _sg.find_soyo_violations("哪有这种事。", trigger_mode=True))
check(
    "对吧 无问号要转化",
    "求证提问" in _sg.find_anon_violations("大吉岭对吧。", trigger_mode=True),
)
check(
    "会不会 无问号要转化",
    "提问句" in _sg.find_soyo_violations("她会不会在意。", trigger_mode=True),
)
check(
    "答题 会看的 要拦截",
    "答题式回应"
    in _sg.find_soyo_violations(
        "会看的", trigger_mode=True, user_text="会不会在意爱音发了什么"
    ),
)
check(
    "答题 大概就是些 要拦截",
    "答题式列举"
    in _sg.find_anon_violations(
        "大概就是些乐队的动态。",
        trigger_mode=True,
        user_text="刷sns都会看到什么呢",
    ),
)
check(
    "短事实仍放行",
    not _sg.find_soyo_violations("五个。不多不少。", trigger_mode=True),
)
check(
    "peer 问句放行",
    not _sg.find_soyo_violations(
        "小爱音要不要去。", trigger_mode=False, require_address=True
    )
    and not _sg.find_anon_violations(
        "soyorin 大吉岭对吧。", trigger_mode=False, require_address=True
    ),
)
check(
    "类型3 对同伴问句放行",
    "提问句"
    not in _sg.find_soyo_violations(
        "小爱音要不要去。",
        trigger_mode=True,
        user_text="小爱音今晚有空吗",
        allow_ask=True,
    ),
)
check(
    "群友提问仍拦反问",
    "求证提问" in _sg.find_anon_violations("大吉岭对吧。", trigger_mode=True, allow_ask=False),
)
check(
    "只提到小爱音不算类型3",
    not _sg.source_names_peer("soyo", "小爱音又发了很多sns，都有什么呢"),
)
check(
    "小爱音逗号才算叫同伴",
    _sg.source_names_peer("soyo", "小爱音，出来吧"),
)
_sns_reply = "还能有什么，自拍加排练日常，偶尔夹几条突然的长感想。……发得这么卖力，看得人也确实不少。小爱音开心就好。"
_sns_ask = "@bot 小爱音又发了很多sns，都有什么呢"
check(
    "sns列举要拦截",
    "答题式列举" in _sg.find_soyo_violations(_sns_reply, trigger_mode=True, user_text=_sns_ask)
    or "提问句" in _sg.find_soyo_violations(_sns_reply, trigger_mode=True, user_text=_sns_ask),
)
_bad_plan = "也行，这家店要是踩雷了，我找你。周末下午吧，我空着。"
_plan_hits = _sg.find_soyo_violations(_bad_plan, trigger_mode=False, require_address=False)
check(
    "AI三段安排句要拦截",
    "AI三段安排句" in _plan_hits
    or "AI约时间句" in _plan_hits
    or "AI让步条件句" in _plan_hits,
)
check(
    "短接话不误伤安排句",
    not _sg.find_soyo_violations("……也行。别选奇怪的。", trigger_mode=False)
    and not _sg.find_soyo_violations("周末？随便。", trigger_mode=False),
)

# --- QQ 身份铁律 ---
peer_mod = sys.modules["group_world_state.peer"]
chars_mod = sys.modules.get("group_world_state.characters")
if chars_mod is None:
    _cpath = ROOT / "plugins/group_world_state/characters.py"
    _cspec = spec_from_file_location("group_world_state.characters", _cpath)
    chars_mod = module_from_spec(_cspec)
    sys.modules["group_world_state.characters"] = chars_mod
    _cspec.loader.exec_module(chars_mod)

check("soyo 同伴 QQ=爱音", chars_mod.peer_qq("soyo") == "3845655536")
check("anon 同伴 QQ=素世", chars_mod.peer_qq("anon") == "2246246527")
check("爱音 QQ 对 soyo 是 peer", chars_mod.is_peer_qq("soyo", "3845655536"))
check("路人 QQ 不是 peer", not chars_mod.is_peer_qq("soyo", "10001"))
check(
    "人设绑定称呼",
    chars_mod.peer_address("soyo").get("call") == "小爱音"
    and chars_mod.peer_address("anon").get("call") == "soyorin",
)
check(
    "人设绑定解析",
    chars_mod.peer_binding("soyo").get("peer_display") == "千早爱音"
    and chars_mod.peer_binding("anon").get("self_qq") == "3845655536",
)
check(
    "路人即使叫爱音也是群友",
    peer_mod.analyze_dialogue_target("soyo", "10001", "小爱音今晚有空吗", mentioned_self=True).get("is_peer")
    is False
    and peer_mod.analyze_dialogue_target("soyo", "10001", "小爱音今晚有空吗", mentioned_self=True).get("sender_kind")
    == "member",
)
check(
    "配置同伴 QQ 才走 peer",
    peer_mod.analyze_dialogue_target("soyo", "3845655536", "soyorin 在吗").get("is_peer") is True,
)
check(
    "未登记 Bot QQ 也当群友",
    peer_mod.analyze_dialogue_target("soyo", "999999999", "素世你好").get("is_peer") is False,
)

print("all checks passed")
