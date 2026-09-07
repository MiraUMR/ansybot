import sys
sys.path.insert(0, "/usr/local/lib/python3.11/site-packages/kirara_ai/plugins")
from group_world_state.blocks import _build_external_trigger_prompt
from group_world_state.style_guard import critical_block_for, find_soyo_violations, find_anon_violations

ps = _build_external_trigger_prompt("soyo", "甲", "群", "不是小爱音的生日吗")
pa = _build_external_trigger_prompt("anon", "甲", "群", "不是小爱音的生日吗")
cs = critical_block_for("soyo")
ca = critical_block_for("anon")
print("SOYO_ADDON", "特别注意（素世版）" in ps)
print("ANON_ADDON", "特别注意（爱音版）" in pa)
print("SOYO_NO_ANON_ADDON", "特别注意（爱音版）" not in ps)
print("ANON_NO_SOYO_ADDON", "特别注意（素世版）" not in pa)
print("NO_NARRATIVE_TITLE", "NARRATIVE INTERNALIZATION" not in cs and "NARRATIVE INTERNALIZATION" not in ca)
print("WECHAT_VOICE", "发微信" in cs and "发微信" in ca)
print("NO_ACTION_FIRST", "必须先有内敛" not in cs)
print("NO_FORCE_HOOK", "必须携带互动钩子" not in ca)
print("PROMPT_VOICE_TAIL", "禁止秘书腔" in ps)
print("SOYO_FACT_HIT", find_soyo_violations("不是，9月8号。", trigger_mode=True))
print("ANON_FACT_HIT", find_anon_violations("对呀！就是9月8号哦！", trigger_mode=True))
print("SOYO_OK", find_soyo_violations("……还没到呢。九月八号。", trigger_mode=True))
print("SHORT_FACT_OK", find_soyo_violations("五个。不多不少。", trigger_mode=True))
print("Q_NO_MARK", find_soyo_violations("她会不会在意。", trigger_mode=True))
print("DUI_BA", find_anon_violations("大吉岭对吧。", trigger_mode=True))
print("FAQ_HIT", find_soyo_violations("会看的", trigger_mode=True, user_text="会不会在意爱音发了什么"))
print("NE_OK", find_soyo_violations("……还没到呢。九月八号。", trigger_mode=True))
print("SECRETARY_HIT", find_anon_violations(
    "soyorin，大吉岭的事我记下了。别再看手机了，现在出门还赶得上。上次你挑茶叶的样子我还记得，这次我帮你筛好，你负责点头就行。"
))
print("SECRETARY_OK", find_anon_violations("soyorin！大吉岭对吧，走啊现在！"))
from group_world_state.blocks import _env_voice_tail
from group_world_state.peer import alias_hit, looks_addressed_to_self

print("ADDRESSED_YES", looks_addressed_to_self("素世，帮我看看", "soyo"))
print("MENTION_ONLY", looks_addressed_to_self("素世今天没来练琴", "soyo"))
print("CANON_NOT_ANON", alias_hit("canon 这首好听", "anon"))
print("ENV_HIT", find_soyo_violations("你说的这家店我知道", env_mode=True))
print("ENV_OK", find_soyo_violations("……水开了。", env_mode=True))

# --- @ 只认 QQ ---
from kirara_ai.im.message import IMMessage
from kirara_ai.im.sender import ChatSender

from group_world_state.mentions import (
    addressed_to_self,
    is_reply_to_bot as _is_reply_to_bot,
    mentioned_bot as _mentioned_bot,
    mentioned_others as _mentioned_others,
)

SELF = "2246246527"  # soyo
OTHER = "1000100010"
_sender = ChatSender.from_group_chat(user_id="10001", group_id="g1", display_name="甲")


def _msg(segs, elements=None):
    return IMMessage(
        sender=_sender,
        message_elements=elements or [],
        raw_message={"self_id": SELF, "message": segs},
    )


at_bot = _msg([{"type": "at", "data": {"qq": SELF, "is_bot": True}}])
at_other = _msg([{"type": "at", "data": {"qq": OTHER}}])
at_all = _msg([{"type": "at", "data": {"qq": "all"}}])
reply_other = _msg(
    [{"type": "reply", "data": {"id": "1"}}, {"type": "at", "data": {"qq": OTHER}}]
)
reply_plain = _msg([{"type": "reply", "data": {"id": "1"}}])
reply_bot_qq = _msg([{"type": "reply", "data": {"id": "1", "qq": SELF}}])

print("AT_BOT", _mentioned_bot(at_bot, "soyo"), _mentioned_others(at_bot, "soyo"))
print("AT_OTHER", _mentioned_bot(at_other, "soyo"), _mentioned_others(at_other, "soyo"))
print("AT_ALL", _mentioned_bot(at_all, "soyo"), _mentioned_others(at_all, "soyo"))
print("REPLY_OTHER", _is_reply_to_bot(reply_other, "soyo"))
print("REPLY_PLAIN", _is_reply_to_bot(reply_plain, "soyo"))
print("REPLY_BOT_QQ", _is_reply_to_bot(reply_bot_qq, "soyo"))

cq_other = IMMessage(
    sender=_sender,
    message_elements=[],
    raw_message={"self_id": SELF, "raw_message": f"[CQ:at,qq={OTHER}] 今晚吃什么"},
)
print("CQ_AT_OTHER", _mentioned_bot(cq_other, "soyo"), _mentioned_others(cq_other, "soyo"))
print("ADDRESSED_OTHER", addressed_to_self(at_other, "soyo"))
print("ADDRESSED_BOT", addressed_to_self(at_bot, "soyo"))
print("ADDRESSED_REPLY_PLAIN", addressed_to_self(reply_plain, "soyo"))
from group_world_state.narration import wrap_template
print("WRAP_YOU", wrap_template("@张三 你看这个"))
print("WRAP_OK", wrap_template("外面下雨了"))

print("---ENV TAIL---")
print(_env_voice_tail("soyo"))
print("---SOYO CRITICAL---")
print(cs)
