"""素世回复的轻量校验：违规称呼 / 采访体，命中则记录并触发一次重写。"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from kirara_ai.llm.format.message import LLMChatMessage, LLMChatTextContent
from kirara_ai.llm.format.request import LLMChatRequest
from kirara_ai.llm.format.response import LLMChatResponse
from kirara_ai.llm.llm_manager import LLMManager

CRITICAL_ADDONS = {
    "soyo": (
        "⚠️ 特别注意（素世版）：事实/日期/设定题用素世的口气直接说，"
        "禁止百科句，禁止先写动作说明书，禁止纠错腔。"
        "但口气可以随便，事实不行：不确定就淡淡认一句不知道（不清楚。/ 没记住。），"
        "禁止编造数字、日期、人名、地名、专有名词。"
        "禁止 markdown：不要代码围栏、不要 **加粗**、不要 # 标题。像本人发微信纯文本。"
    ),
    "anon": (
        "⚠️ 特别注意（爱音版）：事实题先有点情绪再带出信息，语气可以夸张。"
        "夸张只许用在语气上，不许用在事实上：不确定就直接说不知道"
        "（诶不知道欸。/ 这个我真不清楚。），禁止编造数字、日期、人名、地名、专有名词。"
        "不要平铺直叙。不要每条都拐去 soyorin；只有事实本身关于她时才点名。"
        "禁止 markdown：不要代码围栏、不要 **加粗**、不要 # 标题。像本人发微信纯文本。"
    ),
}


def critical_block_for(character: str) -> str:
    """声线交给 voice_pack；这里只放 CRITICAL 层独有的越权禁令。"""
    addon = CRITICAL_ADDONS.get(character) or CRITICAL_ADDONS["soyo"]
    call = "小爱音" if character != "anon" else "soyorin"
    if character == "anon":
        lock = (
            "身份锁：你碎快先热闹，同伴软慢后置。节奏、口味、口头习惯都不能和她对调。"
            "没问到吃的不要主动搬口味锚点。"
        )
    else:
        lock = (
            "身份锁：你软慢后置，同伴碎快先热闹。节奏、口味、口头习惯都不能和她对调。"
            "没问到吃的不要主动搬口味锚点。"
        )
    return (
        "[CRITICAL]\n"
        f"{lock}禁止问答体。禁止提及提问者（不要说有人问/你问的）。\n"
        "不要把无关问题都转化成找同伴；若本轮已经涉及同伴，必须用规定称呼"
        f"（{call}），这不是强制绑定。\n"
        "禁止两截转进：不要答完再拐去问同伴「你说，是不是」。\n"
        f"{addon}\n"
        "禁止导演复盘，禁止动作说明书和小说旁白。像本人发微信，不是客服。\n"
        "[/CRITICAL]"
    )


def critical_instruction_for(character: str, mode: str) -> str:
    """工作流 P0：仅 story / direct（Trigger）非空，挂在系统提示末尾覆盖低层规则。"""
    mode = (mode or "").strip()
    if mode == "story":
        return (
            "[P0: STORY MODE LOCK ACTIVE]\n"
            "⚠️ 故事模式最高优先级。由工作流 message_mode=story 注入，覆盖 Base/Companion/Trigger 常规规则。\n"
            "- Base「接话/有来有回」与 Companion「互动强化」：已降级\n"
            "- 唯一有效规则集：Story 模块 + 本指令\n"
            "- 对话对象是故事角色/环境，不是提问者\n"
            "- 每轮末尾输出 <memory_point> 标签\n"
            "[/P0]"
        )
    if mode != "direct":
        return ""
    # 语气/事实的口吻部分已在 CRITICAL_ADDONS 里说过，这里不重复，只补事实红线。
    return (
        "[P0: NARRATIVE LOCK ACTIVE]\n"
        "⚠️ direct/@ 最高优先级：Trigger + 本指令覆盖 Base「接话」惯性。\n"
        "- 事实红线：口气可以编，事实不能编。不确定就用角色口气认一句不知道，"
        "禁止杜撰数字/日期/人名/地名/专有名词，禁止把猜测说成肯定。\n"
        "- 前后不能自相矛盾：不要否认自己刚说过的话，不要凭空多出没提过的人和事；"
        "刚说出口的邀约或态度，下一句不要反着骂。\n"
        "- 身份锁：节奏口味不要和同伴对调。没问到吃的不要主动搬口味锚点。\n"
        "- 对眼前的人：禁问答体/复读选择问/给许可拒绝；无问号提问也改陈述。\n"
        "- 点名同伴：类型3，用规定称呼当面说；禁「她」向外转述。\n"
        "- 禁止在回复里写出任何账号、编号。\n"
        "- 若有 [ARBITRATION: peer_interaction] / TOPIC_LOCK peer_interaction："
        "忽略 deflect/idle，直接互动，禁止分析规则冲突。\n"
        "[INSTRUCTION: DO NOT ANALYZE RULE CONFLICTS. DIRECT ACTION ONLY.]\n"
        "[/P0]"
    )


CRITICAL_NARRATIVE_BLOCK = critical_block_for("soyo")

# 先抠掉合法称呼，再抓裸「爱音」等变体。
_ALLOWED_PEER = "小爱音"
_PEER_TOKEN = "\u0000PEER\u0000"

_NAME_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"爱音酱"), "爱音酱"),
    (re.compile(r"(?i)\bAnon\b"), "Anon"),
    (re.compile(r"千早"), "千早"),
    (re.compile(r"爱音"), "爱音"),
]

_SELF_SOYORIN = re.compile(
    r"(我(?:是|叫|就是)?\s*soyorin|soyorin(?:才不是|才没|才不))",
    re.IGNORECASE,
)

_SOYO_FACT_QA = [
    (re.compile(r"^(不是[，,。 ]|不对|其实|准确来说|错了)"), "纠错语气开头"),
]
_ANON_FACT_QA = [
    (re.compile(r"^(对呀|是的|没错|对哦|对啊)"), "平铺确认开头"),
]


def _lead_text(text: str) -> str:
    t = re.sub(r"^[\s\*＿_]+", "", text or "")
    t = re.sub(r"^\*[^*]*\*\s*", "", t)
    return t.strip()


_DIRECTOR_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"让我理理"), "让我理理"),
    (re.compile(r"这个状况"), "这个状况"),
    (re.compile(r"我是不是真的"), "我是不是真的"),
    (re.compile(r"这种时候我要是"), "这种时候我要是"),
    (re.compile(r"先假装没看到"), "先假装没看到"),
]

_SOYO_FIXED_VOICE = re.compile(
    r"[（(]就是不想让(?:某人|她)[^）)]{0,12}[）)]|"
    r"就是不想让(?:某人|她)知道我在意[。．]?|"
    r"红茶还有[。．]?|"
    r"看她的脸色[。．]?|"
    r"看脸色[。．]?|"
    r"周五可以吗[。．]?|"
    r"我哪天都行[。．]?|"
    r"哈啊\.{2,}|哈啊…+|"
    r"大吉岭|"
    r"这次就算了[。．]?|"
    r"你倒是把话说完[。．]?|"
    r"小爱音先坐下[。．]?|"
    r"(?:^|[\s。．])这样啊[。．，,]*|"
    r"(?:^|[\s。．])也好[。．]*|"
    r"小爱音[…。.\s]{0,8}你说[，,]?\s*是不是"
)


_SOYO_CATCHPHRASE = re.compile(
    r"[（(][^）)]{0,24}不想让某人知道我在意[^）)]{0,8}[）)]|"
    r"就是不想让某人知道我在意[。．]?"
)

_INNER_ASIDE_RE = re.compile(r"[（(]([^）)]{0,48})[）)]")
_INNER_HINT = re.compile(
    r"不想|在意|其实|心里|才不|才要|不能让|别让|不让|某人|偷偷|看出来|别把|还是别|心里话|腹诽|误会|顺手|识货|不理我"
)
# 串腔：爱音不该用素世淡藏；素世不该用爱音碎急嘴硬
_ANON_INNER_FORBIDDEN = re.compile(r"不想让某人|只是顺手|别让她误会|说了也没用|看她脸色")
_SOYO_INNER_FORBIDDEN = re.compile(r"才不想|偷偷关注|好久了|不理我怎么办|才不是特意|诶嘿|识货")
# 内心括号写成两段式剧情揭秘（其实...早就...这个不能让她知道），太像写小说，不像真人一拍反应。
_INNER_NOVEL_RE = re.compile(
    r"其实.{2,30}(已经|早就|一直).{0,30}(不能|别|不想|不敢)[^）)]{0,20}(知道|发现)"
)
_INNER_LEN_LIMIT = 20

# 右引号比左引号多，说明前面「XX做出「」被截断只剩了尾巴（常见于「」的表情/样子这类配语）。
_STRAY_CLOSE_QUOTE_TAIL_RE = re.compile(r"」\s*的(表情|样子|语气|声音|口气)[，,。.!！]*")


_MD_FENCE_RE = re.compile(r"```[\w+-]*[ \t]*\n?([\s\S]*?)```")
_MD_HEADING_RE = re.compile(r"^#{1,6}[ \t]+", re.M)
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_MD_LEFTOVER_FENCE_RE = re.compile(r"```[\w+-]*")


def looks_like_markdown(text: str) -> bool:
    """模型偶发把回复包进代码围栏 / 加粗 / 标题。"""
    raw = text or ""
    if "```" in raw:
        return True
    if _MD_BOLD_RE.search(raw) or _MD_HEADING_RE.search(raw):
        return True
    if _MD_INLINE_CODE_RE.search(raw):
        return True
    return False


def markdown_hits(text: str) -> List[str]:
    return ["markdown格式"] if looks_like_markdown(text) else []


def scrub_markdown_markup(text: str) -> str:
    """QQ 群只发纯文本：拆掉围栏/加粗/标题/行内代码，空围栏整段丢掉。"""
    out = text or ""
    out = _MD_FENCE_RE.sub(lambda m: (m.group(1) or "").strip(), out)
    out = _MD_LEFTOVER_FENCE_RE.sub("", out)
    out = _MD_HEADING_RE.sub("", out)
    out = _MD_BOLD_RE.sub(r"\1", out)
    out = _MD_LINK_RE.sub(r"\1", out)
    out = _MD_INLINE_CODE_RE.sub(r"\1", out)
    out = out.replace("**", "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


_QUOTED_THOUGHT_HINT = re.compile(
    r"才不想|才不是|才要|心里|腹诽|不能让她|别让她|不想让|别看出来|偷偷|不理我怎么办|才不是特意"
)
_QUOTE_PAIR_RE = re.compile(r"[「『]([^」』]{1,48})[」』]")
_SPEAKER_PREFIX_RE = re.compile(
    r"^(?:千早爱音|长崎素世|小爱音|爱音|素世|anon(?:\s*chan)?|soyorin|soyo)\s*[：:]\s*",
    re.IGNORECASE,
)


def restore_quoted_inner_asides(text: str) -> str:
    """把内心从语录「」还原成（）；剧本式 角色：「」 拆掉外壳。"""
    raw = (text or "").strip()
    if not raw:
        return raw
    raw = _SPEAKER_PREFIX_RE.sub("", raw).strip()

    def as_aside(inner: str) -> str:
        inner = (inner or "").strip()
        if _QUOTED_THOUGHT_HINT.search(inner):
            return f"（{inner}）"
        return inner

    whole = re.fullmatch(r"[「『]([^」』]+)[」』][。．.!！]?", raw)
    if whole:
        return as_aside(whole.group(1))

    def repl(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        if _QUOTED_THOUGHT_HINT.search(inner):
            return f"（{inner}）"
        return m.group(0)

    out = _QUOTE_PAIR_RE.sub(repl, raw)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def scrub_stray_close_quote(text: str) -> str:
    """清掉多余的右引号残留：只在「」数量不配对时动手，不影响正常成对使用。"""
    raw = text or ""
    if raw.count("」") <= raw.count("「"):
        return raw
    out = _STRAY_CLOSE_QUOTE_TAIL_RE.sub("", raw)
    out = out.replace("」", "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def scrub_long_inner_aside(text: str) -> str:
    """内心括号只留一拍反应：写成两段式剧情揭秘或超长的，直接去掉这一句括号。"""

    def repl(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        raw = m.group(0)
        if not _INNER_HINT.search(inner):
            return raw
        if _INNER_NOVEL_RE.search(inner) or len(inner) > _INNER_LEN_LIMIT:
            return ""
        return raw

    out = _INNER_ASIDE_RE.sub(repl, text or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"^[。．，,\s]+", "", out)
    return out.strip()


def strip_inner_asides_for_peer(text: str) -> str:
    """同伴入站：括号内心听不见，只保留会说出口的字。"""
    out = re.sub(r"[（(][^）)]{0,48}[）)]", "", text or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def scrub_wrong_inner_style(character: str, text: str) -> str:
    """拆掉串到另一人风格的内心括号；保留本人风格。"""
    forbid = _SOYO_INNER_FORBIDDEN if character == "soyo" else _ANON_INNER_FORBIDDEN

    def repl(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        if not _INNER_HINT.search(inner):
            return m.group(0)
        if forbid.search(inner):
            return ""
        return m.group(0)

    out = _INNER_ASIDE_RE.sub(repl, text or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"^[。．，,\s]+", "", out)
    return out.strip()


def scrub_soyo_catchphrase(text: str) -> str:
    """素世出口：去掉反复出现的固定内心口头禅。"""
    out = _SOYO_CATCHPHRASE.sub("", text or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"^[。．，,\s]+", "", out)
    return out.strip()


def scrub_soyo_fixed_voice(text: str) -> str:
    """爱音出口：删掉素世固定句，避免提示里的禁例被原样发出。"""
    out = _SOYO_FIXED_VOICE.sub("", text or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"^[。．，,\s]+", "", out)
    out = re.sub(r"[。．]{2,}", "。", out)
    return out.strip()


_AI_SECRETARY_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"我记下了"), "我记下了"),
    (re.compile(r"你负责"), "你负责"),
    (re.compile(r"的样子我还记得"), "的样子我还记得"),
    (re.compile(r"别再看手机"), "别再看手机"),
    (re.compile(r"这次我帮你"), "这次我帮你"),
    (re.compile(r"你先说"), "你先说"),
    (re.compile(r"我听着"), "我听着"),
    (re.compile(r"这个我熟"), "这个我熟"),
]
# AI 段落句：让步 + 条件兜底 + 约时间，读起来像助理排期。
_AI_PARAGRAPH_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"(也行|好吧|行吧)[，,].{0,24}(要是|如果)"), "AI让步条件句"),
    (re.compile(r"(踩雷|搞砸|弄砸).{0,10}(我找你|找你|你负责)"), "AI行程兜底句"),
    (re.compile(r"(周末|周[一二三四五六日天]|明天|后天|下午|晚上).{0,8}吧[，,].{0,10}(我空着|我有空|没事干|有空)"), "AI约时间句"),
    (re.compile(r"(安排明白|安排清楚|帮你约好|我来安排)"), "AI安排腔"),
    (re.compile(r"就[两二三四五六七八九十\d]{1,2}[张杯碗次口轮件]"), "AI数量收束句"),
    (re.compile(r"(拍|吃|喝|看|买|照|逛)完立刻"), "AI流程说明书"),
    (re.compile(r"立刻开(喝|吃|走|拍|逛)"), "AI流程说明书"),
]
_OPEN_SOYO = re.compile(r"^[\s\*＿_]*(?:……|…+|\.{2,})?小爱音[，,]")
_OPEN_ANON = re.compile(r"(?i)^[\s\*＿_]*(?:……|…+|\.{2,})?soyorin[，,]")
_VOCATIVE_HEADER = {
    "soyo": re.compile(r"(?m)^[\s\*＿_]*(?:……|…+|\.{2,})?小爱音[，,]\s*"),
    "anon": re.compile(r"(?mi)^[\s\*＿_]*(?:……|…+|\.{2,})?soyorin[，,]\s*"),
}


def scrub_vocative_header(character: str, text: str) -> str:
    """清掉「小爱音，/soyorin，」当段落抬头；名字仍可留在句中。"""
    pat = _VOCATIVE_HEADER.get((character or "").strip() or "soyo")
    if not pat:
        return text or ""
    out = pat.sub("", text or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()

# 环境音里没有对话对象：一旦对着人说话就破坏代入感。
_ENV_ADDRESS_RE = re.compile(r"[你您]")
_ENV_ANSWER_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(是的|对啊|对呀|没错|对哦|嗯对|当然)"), "环境音里答话"),
    (re.compile(r"(群里|群友|刚才谁|谁说的)"), "环境音里找说话人"),
]

_INTERVIEW_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"你问的"), "你问的"),
    (re.compile(r"怎么突然问"), "怎么突然问"),
    (re.compile(r"有人问"), "有人问"),
    (re.compile(r"有人提到"), "有人提到"),
    (re.compile(r"刚好有人提到"), "刚好有人提到"),
    (re.compile(r"关于这个问题"), "关于这个问题"),
    (re.compile(r"关于这[个件事]"), "关于这"),
    (re.compile(r"其实是这样"), "其实是这样"),
    (re.compile(r"提问者"), "提问者"),
    (re.compile(r"群友问"), "群友问"),
    (re.compile(r"你怎么问"), "你怎么问"),
]

# 「不行不行 / 不要不要」是爱音着急叠词，不是「行不行」选择问。
_PANIC_REDUP_RE = re.compile(r"不行不行|不要不要|不是不是")
_VOICE_Q_TIC_RE = re.compile(r"(?:诶|哈|啊|哇|喂)[？?]+|(?:真的假的)[？?]?")
_PEER_DISTRESS_RE = re.compile(
    r"(哭了|在哭|好像在哭|要跑|跑了|跑掉|追上|快追|去追|追呀|追啊|"
    r"要你追|追不到|追她|快去追|人都没了|人都沒了|别回来|別回來|"
    r"不要你了|不要她了|太坏了|始乱终弃)"
)
_CARE_CLAUSE_RE = re.compile(r"(去看|追上|得去|不行不行|担心|哭|别跑|等等我)")
_COLD_CLAUSE_RE = re.compile(r"(麻烦死了|算了.{0,10}明天|反正明天|谁爱追)")
_SHOE_EXCUSE_RE = re.compile(
    r"(鞋带.{0,12}(没系|沒系|要是|松了)|追什么追|又不差这一会儿|"
    r"总行了吧|怪你们|你们这些|催命鬼)"
)
_CHASE_IN_FLIGHT_RE = re.compile(
    r"(别跑|等等我|一直在追|我这不是一直在追|追上去了|我现在就追|"
    r"马上追上来|追不到也要追|还不去追)"
)
_YOU_VS_SOYORIN_RE = re.compile(
    r"(?i)你.{0,24}比soyorin|比soyorin.{0,16}(跑|快)|你鞋带"
)
_CHASER_CLAIM_RE = re.compile(r"(追到了|去追小爱音|我去追|追上她了)")


def looks_chase_in_flight(text: str) -> bool:
    """同伴已经在追 / 喊别跑：互聊应续场面，不是闲聊收束。"""
    return bool(_CHASE_IN_FLIGHT_RE.search(text or ""))


def _uses_second_person(text: str) -> bool:
    raw = text or ""
    return bool(re.search(r"你(?!们)", raw))


def peer_call_of(character: str) -> str:
    return "soyorin" if (character or "").strip() == "anon" else "小爱音"


def scrub_peer_second_person(character: str, text: str) -> str:
    """互聊里不要「你」：已有称呼就删掉代词，否则换成规定称呼。"""
    raw = (text or "").strip()
    if not raw or not re.search(r"你(?!们)", raw):
        return raw
    call = peer_call_of(character)
    out = re.sub(r"你好[啊呀嘛哇]?", call, raw)
    has_name = (
        bool(re.search(r"(?i)soyorin", out))
        if character == "anon"
        else ("小爱音" in out)
    )
    if has_name:
        out = re.sub(r"你(?!们)", "", out)
    else:
        out = re.sub(r"你(?!们)", call, out, count=1)
        out = re.sub(r"你(?!们)", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"([，,。.!！?？])\1+", r"\1", out)
    return out.strip()

_QA_BODY_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"([\u4e00-\u9fff]{1,2})不\1"), "复读选择问"),
    (re.compile(r"让她自己来问|要她自己来问|她自己来问"), "向提问者转述同伴"),
    (re.compile(r"她这么说的|她自己都说了"), "向提问者求证"),
    (re.compile(r"记得有这么回事|有这么回事"), "向提问者确认"),
]
_QA_LEAD_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"^别催"), "回答催促的提问者"),
    (re.compile(r"^(不看|不亲|不给看)([。.!！…]|$)"), "向提问者表态许可"),
    (re.compile(r"算是吧[。.!！…]*\s*$"), "向提问者确认"),
]

REWRITE_USER = (
    "[CRITICAL] 刚才的回复违规：{reasons}。"
    "整段重写。禁止问答体、禁止提及提问者、禁止导演复盘「这个状况」。"
    "禁止复读问题（紧不紧张/看不看），禁止向提问者表态（不看/让她自己来问/别催），"
    "禁止用「她」向外转述同伴。"
    "禁止反问（吗/对吧/真的假的/要不要），禁止答题（会的/大概就是）。"
    "禁止AI段落句：不要「也行，要是踩雷了就找你。周末下午吧，我空着」这种让步+兜底+约时间。"
    "也不要「拍照就两张，拍完立刻开喝」这种把流程一次排完的说明书。"
    "改成角色正在发的一句短微信，碎一点、停半拍，不要排期说明书。"
    "{address}"
    "用角色本人说话，禁止秘书腔（我记下了/你负责/我来安排）。"
    "禁止陪聊腔：你先说、我听着、这个我熟。"
    "禁止「soyorin，」或「小爱音，」当抬头。不要动作说明书。"
)

# 重写仍脏时的硬兜底（无问号、无禁用称呼、不答题）
_FALLBACK_DIRECT = {
    "anon": "哇——等等！",
    "soyo": "嗯。",
}
_FALLBACK_ENV = {
    "anon": "……好困。",
    "soyo": "水开了。",
}
_FALLBACK_PEER = {
    "anon": "嗯！",
    "soyo": "……嗯。",
}


def fallback_safe_reply(
    character: str,
    *,
    trigger_mode: bool = False,
    peer_mode: bool = False,
    env_mode: bool = False,
    user_text: str = "",
) -> str:
    cid = character if character in ("anon", "soyo") else "soyo"
    if looks_chase_in_flight(user_text) or looks_peer_distress_cue(user_text):
        if cid == "soyo":
            return "……小爱音，你追这么急。"
        return "soyorin等等我！"
    if env_mode:
        return _FALLBACK_ENV[cid]
    if peer_mode:
        return _FALLBACK_PEER[cid]
    if trigger_mode:
        return _FALLBACK_DIRECT[cid]
    return _FALLBACK_DIRECT[cid]


_NAME_VIOLATIONS = {
    "爱音",
    "爱音酱",
    "Anon",
    "千早",
    "素世",
    "素世酱",
    "素世世",
    "soyo",
    "自称soyorin",
    "未称呼小爱音",
    "未称呼soyorin",
}


def _rewrite_address(
    character: str,
    reasons: List[str],
    peer_mode: bool,
    env_mode: bool = False,
    env_peer_mode: bool = False,
) -> str:
    extra = ""
    if any(
        r in reasons
        for r in ("提问句", "求证提问", "答题式回应", "答题式列举")
    ):
        extra = "把提问改成一句陈述反应，不要答题，不要反问；没有问号的会不会/什么呢/对吧也要改掉。"
    if any(
        r in reasons
        for r in (
            "AI让步条件句",
            "AI行程兜底句",
            "AI约时间句",
            "AI安排腔",
            "AI三段安排句",
            "AI数量收束句",
            "AI流程说明书",
        )
    ):
        extra += (
            "拆掉排期腔：不要一次说完「也行+要是踩雷+周末空着」。"
            "也不要把行程压成「就两张、拍完立刻开喝」。"
            "改成一两句短反应，时间含糊带过或干脆不约。"
        )
    if "危急却收束" in reasons:
        extra += (
            "同伴在跑或在哭：必须立刻追上去，禁止算了明天见、禁止拿鞋带当借口停住。"
            "上一句那些冷收束是口误，这轮作废。"
        )
    if "把soyorin当第三人称" in reasons:
        extra += (
            "对面就是 soyorin，当面喊 soyorin，不要用「你」。"
            "禁止把 soyorin 说成旁边第三个人。"
            "鞋带若散了是自己的，不是她的。"
        )
    if "被追却去追" in reasons:
        extra += (
            "你是跑开/被追的那一方，小爱音在追你。不要说自己追到了，不要去追她。"
        )
    if "天气限流" in reasons:
        extra += (
            "本轮不要提天气、冷热、晴雨、潮闷、体感、天色。改成眼前别的一句短反应。"
        )
    if "markdown格式" in reasons:
        extra += (
            "禁止 markdown。不要代码围栏、不要**加粗**、不要#标题、不要行内代码。"
            "只输出微信纯文本。"
        )
    if "账号编号外泄" in reasons:
        extra += "不要写出任何账号或编号。对同伴只用规定称呼，不要用「你」。"
    if "公式转进" in reasons:
        extra += (
            "不要「小爱音……你说，是不是」这种转进。"
            "接住眼前这句就停，不要另起一句去问同伴，也不要用「你」。"
        )
    if "互聊用了你" in reasons:
        call = peer_call_of(character)
        extra += f"对同伴不要用「你」，只喊「{call}」。"
    if env_peer_mode:
        call = "soyorin" if character == "anon" else "小爱音"
        return extra + (
            f"本轮是环境闲聊里主动点同伴：必须出现「{call}」，"
            f"禁止用「你」，只喊「{call}」。禁止回答旁白、禁止找说话人；不要动作括号。"
            "内心至多一句且用本人腔。保留 [CQ:at,qq=…] 原样。"
        )
    if env_mode:
        return extra + (
            "本轮是环境音，没有对话对象：不要回答、不要称呼任何人、"
            "不要提是谁说的，只做自己的反应。"
            + (
                "本轮无爱好命中：禁止硬切吉他音准/调弦或红茶练团填空；"
                "改成情绪、时间或眼前物的一句自言自语。"
                if any(r.startswith("idle硬切") for r in reasons)
                else ""
            )
        )
    if peer_mode or "未称呼小爱音" in reasons or "未称呼soyorin" in reasons:
        call = "soyorin" if character == "anon" else "小爱音"
        return extra + (
            f"本轮是互聊。若要点名，把「{call}」塞进句子中间或末尾，"
            f"禁止「{call}，」起手当抬头。禁止用「你」，只喊「{call}」。"
        )
    if any("Phone禁括号" in r or r.startswith("括号过长") for r in reasons):
        return extra + (
            "去掉动作/神态括号；Phone 用 emoji 或纯文字暗示；"
            "F2F 动作括号单段≤6字。不要把另一人的固定收口写进这条回复。只输出正文。\n"
        )
    if any(r in _NAME_VIOLATIONS for r in reasons):
        return extra + (
            "称呼：素世称同伴只能「小爱音」；爱音称同伴只能「soyorin」。"
            "本轮若本来不该提同伴，就不要提。"
        )
    return extra + "本轮不必硬提同伴。"


def _env_hits(text: str, *, allow_peer_address: bool = False) -> List[str]:
    hits: List[str] = []
    raw = text or ""
    if not allow_peer_address and _ENV_ADDRESS_RE.search(raw):
        hits.append("环境音里称呼对方")
    for pattern, label in _ENV_ANSWER_RULES:
        if pattern.search(_lead_text(raw)) or pattern.search(raw):
            hits.append(label)
    for pattern, label in _INTERVIEW_RULES:
        if pattern.search(raw):
            hits.append(label)
    return hits


# idle_ambient + env：禁止把无关旁白硬切成角色主爱好填空
_ANON_IDLE_PIVOT_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"吉他.{0,12}(音准|调弦|弦)|音准|调弦|弦又松|拨弦|练琴"), "idle硬切吉他"),
]
_SOYO_IDLE_PIVOT_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"红茶|大吉岭|通心粉|练到九点|练团|贝斯弦"), "idle硬切红茶练团"),
]


def _idle_pivot_hits(character: str, text: str) -> List[str]:
    raw = text or ""
    rules = _ANON_IDLE_PIVOT_RULES if character == "anon" else _SOYO_IDLE_PIVOT_RULES
    hits: List[str] = []
    for pattern, label in rules:
        if pattern.search(raw):
            hits.append(label)
    return hits


def _secretary_hits(character: str, text: str) -> List[str]:
    hits: List[str] = []
    raw = text or ""
    for pattern, label in _AI_SECRETARY_RULES:
        if pattern.search(raw):
            hits.append(label)
    if character == "anon" and _OPEN_ANON.search(raw):
        hits.append("称呼当抬头")
    elif character != "anon" and _OPEN_SOYO.search(raw):
        hits.append("称呼当抬头")
    return hits


def _ai_paragraph_hits(text: str) -> List[str]:
    """拦截「也行，要是踩雷了找你。周末下午吧，我空着」这类AI段落。"""
    raw = text or ""
    hits: List[str] = []
    for pattern, label in _AI_PARAGRAPH_RULES:
        if pattern.search(raw):
            hits.append(label)
    soft = bool(re.search(r"(也行|好吧|行吧|也不是不行)", raw))
    fallback = bool(re.search(r"(要是|如果).{0,16}(找你|我找你|你负责|算你的)", raw))
    schedule = bool(re.search(r"(周末|周[一二三四五六日天]|明天|下午|晚上).{0,8}(吧|我空着|我有空)", raw))
    if soft and fallback and schedule:
        hits.append("AI三段安排句")
    elif soft and schedule:
        hits.append("AI三段安排句")
    return hits


def _compact_len(text: str) -> int:
    t = re.sub(r"<memory_point>[\s\S]*?</memory_point>", "", text or "", flags=re.I)
    t = re.sub(r"<<\s*STATE[\s\S]*?>>", "", t, flags=re.I)
    return len(re.sub(r"\s+", "", t))


def looks_like_question(text: str) -> bool:
    """提问语气：没有问号也算（会不会 / 什么呢 / 对吧 / 吗）。

    不把爱音式兴奋标点（！？/？！）、叠问「在哪在哪」当成对外人的问答体。
    """
    t = (text or "").strip()
    if not t:
        return False
    # 兴奋语气：抹茶巴菲！？ / 真的假的？！ —— 去掉后再判
    t_chk = re.sub(r"[！!][？?]|[？?][！!]", "", t)
    if re.search(r"[？?]", t_chk):
        return True
    if re.search(r"吗([。.!！…\s]|$)", t):
        return True
    if re.search(r"(对吧|是吧|不是吧)([。.!！…\s]|$)", t):
        return True
    # 「真的假的」单独作惊叹时可放行；带吗/啊再问才算
    if re.search(r"真的假的[吗啊呢]", t):
        return True
    if re.search(r"(怎么了|为什么|为啥)([。.!！…\s]|$)", t):
        return True
    if re.search(r"(会不会|要不要|是不是|能不能|好不好|行不行)", _PANIC_REDUP_RE.sub("", t)):
        return True
    if re.search(r"(什么呢|什么啊|啥呢|看到什么|发了什么|都有什么)", t):
        return True
    # 叠词兴奋「在哪在哪」放行；「在哪家店/快说在哪」仍算提问
    if re.search(r"(在哪在哪|哪呢哪|哪里哪里)", t) and not re.search(
        r"快说|哪家|哪家店|告诉我", t
    ):
        pass
    elif re.search(r"(去哪|在哪|哪去).{0,8}(呢|啊|吗|家|店)", t):
        return True
    elif re.search(r"快说.{0,8}(哪|什么|多少)", t):
        return True
    if re.search(r"(还能有什么|还有什么)", t):
        return True
    if re.search(r"先问问|去问问|再问问", t):
        return True
    return False


def _account_leak_hits(text: str, user_text: str = "") -> List[str]:
    """拦截把账号/编号念出来。用户原文里出现过的数字放过。"""
    raw = text or ""
    raw = re.sub(r"\b20\d{2}\b", "", raw)
    src = user_text or ""
    if re.search(r"(?:QQ|qq|群号)\s*[：:=]?\s*\d{5,}", raw):
        return ["账号编号外泄"]
    for m in re.finditer(r"\b\d{8,11}\b", raw):
        if m.group(0) in src:
            continue
        return ["账号编号外泄"]
    return []


def looks_peer_distress_cue(text: str) -> bool:
    """有人在描述同伴跑开/哭/不要你了：这是场面，不是向外答题。"""
    return bool(_PEER_DISTRESS_RE.search(text or ""))


def scrub_truncated_tail(text: str) -> str:
    """清掉生成中断残渣：谁说的！s / ……好。a"""
    out = re.sub(r"([。！!…])\s*[A-Za-z]\s*$", r"\1", text or "")
    return out.strip()


def _ask_hits(text: str) -> List[str]:
    raw = text or ""
    if re.search(r"哪有|才不是|谁要啊", raw):
        return []
    # 诶？/哈？ 是爱音惊叹口癖，不是在问群友。
    raw_n = _VOICE_Q_TIC_RE.sub("", raw)
    # 纯兴奋叠问：在哪在哪——！
    if re.search(r"(在哪在哪|哪里哪里)", raw_n) and not re.search(
        r"快说|哪家|告诉我|吗([。.!！…\s]|$)", raw_n
    ):
        # 若整段几乎只有兴奋句，不记提问
        stripped = re.sub(
            r"(在哪在哪|哪里哪里)[—\-！!。.…\s]*",
            "",
            re.sub(r"[！!][？?]|[？?][！!]", "", raw_n),
        )
        stripped = re.sub(r"[\s…]+", "", stripped)
        if len(stripped) <= 12 and not re.search(r"[？?吗]", stripped):
            return []
    hits: List[str] = []
    t_chk = re.sub(r"[！!][？?]|[？?][！!]", "", raw_n)
    if re.search(r"[？?]", t_chk):
        hits.append("提问句")
    if re.search(r"吗([。.!！…\s]|$)", raw):
        hits.append("提问句")
    if re.search(r"(对吧|是吧|不是吧)([。.!！…\s]|$)", raw):
        hits.append("求证提问")
    if re.search(r"真的假的[吗啊呢]", raw):
        hits.append("求证提问")
    if re.search(r"(会不会|要不要|是不是|能不能|好不好|行不行)", _PANIC_REDUP_RE.sub("", raw)):
        hits.append("提问句")
    if re.search(r"(什么呢|什么啊|啥呢|看到什么|发了什么|都有什么|还能有什么|还有什么)", raw):
        hits.append("提问句")
    if re.search(r"先问问|去问问|再问问", raw):
        hits.append("提问句")
    if re.search(r"(怎么了|为什么|为啥)([。.!！…？?\s]|$)", raw):
        hits.append("提问句")
    if re.search(r"快说.{0,8}(哪|什么|多少)", raw):
        hits.append("提问句")
    if re.search(r"(去哪|在哪|哪去).{0,8}(呢|啊|吗|家|店)", raw) and not re.search(
        r"(在哪在哪|哪里哪里)", raw
    ):
        hits.append("提问句")
    if not hits and looks_like_question(raw):
        hits.append("提问句")
    return hits


def last_user_text(prompt: Optional[List[LLMChatMessage]]) -> str:
    for msg in reversed(prompt or []):
        if getattr(msg, "role", None) != "user":
            continue
        bits: List[str] = []
        for part in getattr(msg, "content", None) or []:
            t = getattr(part, "text", None)
            if t:
                bits.append(str(t))
        if bits:
            return "\n".join(bits)
    return ""


def trigger_source_text(prompt: Optional[List[LLMChatMessage]] = None, fallback: str = "") -> str:
    blob = last_user_text(prompt) or (fallback or "")
    m = re.search(r"触发内容：([^\n]+)", blob)
    return (m.group(1) if m else blob).strip()


def salvage_non_ask_reply(text: str, original: str = "") -> Optional[str]:
    """重写仍脏时：尽量保留不含提问的分句，避免发出空洞兜底。"""
    raw = (text or "").strip()
    src = (original or raw).strip()
    if not raw:
        return None

    def _parts(blob: str) -> List[str]:
        bits = []
        for p in re.split(r"(?<=[。！!？?\n])\s*", blob or ""):
            bit = (p or "").strip()
            if bit:
                bits.append(bit)
        return bits

    # 同伴哭/跑的场面：优先留「去看/追上」，不要只剩嫌麻烦。
    if _CARE_CLAUSE_RE.search(src) or looks_peer_distress_cue(src):
        care = [b for b in _parts(src) if _CARE_CLAUSE_RE.search(b) and not _ask_hits(b)]
        if care:
            out = "".join(care).strip()
            if out and not _COLD_CLAUSE_RE.search(out):
                return out

    # 按断句切；保留不含提问的片段
    kept: List[str] = []
    for bit in _parts(raw):
        if _ask_hits(bit):
            continue
        kept.append(bit)
    if not kept:
        # 再试：去掉「在哪…」「快说…」后的残留
        cleaned = re.sub(r"(快说.{0,12}|在哪(?:在哪)?[^。！!\n]{0,12})", "", raw)
        cleaned = re.sub(r"[？?]+", "！", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned and not _ask_hits(cleaned) and len(re.sub(r"\s+", "", cleaned)) >= 2:
            if _COLD_CLAUSE_RE.search(cleaned) and _CARE_CLAUSE_RE.search(src):
                return None
            return cleaned
        return None
    out = "".join(kept).strip()
    if _COLD_CLAUSE_RE.search(out) and _CARE_CLAUSE_RE.search(src) and not _CARE_CLAUSE_RE.search(out):
        return None
    if out and not _ask_hits(out):
        return out
    return None


def _faq_answer_hits(reply: str, user: str) -> List[str]:
    u = user or ""
    r = reply or ""
    if not u or not r:
        return []
    asked = looks_like_question(u)
    lead = _lead_text(r)
    hits: List[str] = []
    if asked and re.match(
        r"^(会的|会看|不会|要啊|要吧|不要|是啊|是的|不是|能|不能|大概就是|一般都是|其实就是|那当然|肯定会|当然会|那会)",
        lead,
    ):
        hits.append("答题式回应")
    if asked and re.search(r"大概就是些|一般都是|主要是些|其实就是些", r):
        hits.append("答题式列举")
    if re.search(r"会不会", u) and re.search(r"(会看的|会的|不会管|会在意|不太会管)", r):
        hits.append("答题式回应")
    if re.search(r"(看到什么|发了什么|什么呢|都有什么)", u) and re.search(
        r"(大概就是|一般都是|会看到|刷到的是|还能有什么|还有什么|无非是|不就是|偶尔夹)",
        r,
    ):
        hits.append("答题式列举")
    if re.search(r"(看到什么|发了什么|什么呢|都有什么)", u) and re.search(
        r"(自拍|排练|日常|感想).{0,12}(加|偶尔|夹)",
        r,
    ):
        hits.append("答题式列举")
    return hits


def source_names_peer(character: str, text: str) -> bool:
    """触发原文是否在叫同伴（当面点名）。只是提到名字不算。"""
    try:
        from .characters import peer_id_for
        from .peer import looks_vocative_to

        pid = peer_id_for(character)
        return bool(pid) and looks_vocative_to(text or "", pid)
    except Exception:
        return False


def _trigger_qa_hits(text: str, user_text: str = "", allow_ask: bool = False) -> List[str]:
    """群友 @ 才拦问答/反问；allow_ask 表示本轮是对同伴说话，问句放行。"""
    hits: List[str] = []
    raw = text or ""
    lead = _lead_text(raw)
    for pattern, label in _INTERVIEW_RULES:
        if pattern.search(raw):
            hits.append(label)
    for pattern, label in _QA_BODY_RULES:
        if not pattern.search(raw):
            continue
        if label == "复读选择问":
            # 不行不行 = 着急叠词，里面碰巧含「行不行」
            if not pattern.search(_PANIC_REDUP_RE.sub("", raw)):
                continue
            if allow_ask:
                if not (user_text and pattern.search(user_text)):
                    continue
        hits.append(label)
    for pattern, label in _QA_LEAD_RULES:
        if pattern.search(lead) or pattern.search(raw.strip()):
            hits.append(label)
    if not allow_ask:
        hits.extend(_ask_hits(raw))
    hits.extend(_faq_answer_hits(raw, user_text))
    return hits


def _third_person_peer_hits(character: str, text: str) -> List[str]:
    """禁止用「她」对群友转述同伴；但句内已有规定称呼则放行。"""
    raw = text or ""
    if "她" not in raw:
        return []
    if character == "anon":
        if re.search(r"(?i)soyorin", raw):
            return []
        return ["用她转述同伴"]
    if "小爱音" in raw:
        return []
    return ["用她转述同伴"]


def fix_third_person_peer(character: str, text: str) -> Optional[str]:
    """本地把「她」改成规定称呼，避免为转述再烧一轮 LLM / 掉进收束兜底。"""
    raw = (text or "").strip()
    if "她" not in raw:
        return None
    if character == "anon":
        if re.search(r"(?i)soyorin", raw):
            return None
        out = raw.replace("她", "soyorin")
    else:
        if "小爱音" in raw:
            return None
        out = raw.replace("她", "小爱音")
    if out == raw or _third_person_peer_hits(character, out):
        return None
    return out


def _uniq(hits: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in hits:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def find_anon_violations(
    text: str,
    trigger_mode: bool = False,
    require_address: bool = False,
    env_mode: bool = False,
    env_peer_mode: bool = False,
    user_text: str = "",
    allow_ask: bool = False,
    topic_idle: bool = False,
    peer_mode: bool = False,
) -> List[str]:
    """爱音回复：合法 soyorin 不算「soyo」；拦截素世/素世酱等。"""
    hits: List[str] = []
    body = (text or "").replace("soyorin", "\u0000PEER\u0000")
    body = re.sub(r"(?i)soyorin", "\u0000PEER\u0000", body)
    for pattern, label in (
        (re.compile(r"素世酱"), "素世酱"),
        (re.compile(r"素世世"), "素世世"),
        (re.compile(r"素世"), "素世"),
        (re.compile(r"(?i)\bsoyo\b"), "soyo"),
    ):
        if pattern.search(body):
            hits.append(label)
    for pattern, label in _DIRECTOR_RULES:
        if pattern.search(text or ""):
            hits.append(label)
    hits.extend(_secretary_hits("anon", text))
    hits.extend(_ai_paragraph_hits(text))
    hits.extend(markdown_hits(text))
    hits.extend(_account_leak_hits(text, user_text))
    if env_peer_mode:
        hits.extend(_env_hits(text, allow_peer_address=True))
        if topic_idle:
            hits.extend(_idle_pivot_hits("anon", text))
        if _compact_len(text) >= 8 and not re.search(r"(?i)soyorin", text or ""):
            hits.append("未称呼soyorin")
    elif env_mode:
        hits.extend(_env_hits(text))
        if topic_idle:
            hits.extend(_idle_pivot_hits("anon", text))
    if (peer_mode or env_peer_mode) and _uses_second_person(text):
        hits.append("互聊用了你")
    if require_address and _compact_len(text) >= 12:
        if not re.search(r"(?i)soyorin", text or ""):
            hits.append("未称呼soyorin")
    if peer_mode and _YOU_VS_SOYORIN_RE.search(text or ""):
        hits.append("把soyorin当第三人称")
    if trigger_mode:
        hits.extend(_trigger_qa_hits(text, user_text, allow_ask=allow_ask))
        hits.extend(_third_person_peer_hits("anon", text))
        lead = _lead_text(text)
        for pattern, label in _ANON_FACT_QA:
            if pattern.search(lead):
                hits.append(label)
        if looks_peer_distress_cue(user_text) and (
            re.search(
                r"(算了.{0,16}明天|反正明天就能|麻烦死了|又不差这一会儿|追什么追)",
                text or "",
            )
            or _SHOE_EXCUSE_RE.search(text or "")
        ):
            hits.append("危急却收束")
    return _uniq(hits)


def find_character_violations(
    character: str,
    text: str,
    trigger_mode: bool = False,
    peer_mode: bool = False,
    env_mode: bool = False,
    env_peer_mode: bool = False,
    user_text: str = "",
    allow_ask: bool = False,
    topic_idle: bool = False,
    require_address: Optional[bool] = None,
) -> List[str]:
    if require_address is None:
        require_address = bool(peer_mode)
    if character == "anon":
        return find_anon_violations(
            text,
            trigger_mode=trigger_mode,
            require_address=require_address,
            env_mode=env_mode,
            env_peer_mode=env_peer_mode,
            user_text=user_text,
            allow_ask=allow_ask or peer_mode or env_peer_mode,
            topic_idle=topic_idle,
            peer_mode=peer_mode,
        )
    if character == "soyo":
        return find_soyo_violations(
            text,
            trigger_mode=trigger_mode,
            require_address=require_address,
            env_mode=env_mode,
            env_peer_mode=env_peer_mode,
            user_text=user_text,
            allow_ask=allow_ask or peer_mode or env_peer_mode,
            topic_idle=topic_idle,
            peer_mode=peer_mode,
        )
    return []


def find_soyo_violations(
    text: str,
    trigger_mode: bool = False,
    require_address: bool = False,
    env_mode: bool = False,
    env_peer_mode: bool = False,
    user_text: str = "",
    allow_ask: bool = False,
    topic_idle: bool = False,
    peer_mode: bool = False,
) -> List[str]:
    """返回命中的违规标签；合法「小爱音」不会被算作「爱音」。"""
    hits: List[str] = []
    body = (text or "").replace(_ALLOWED_PEER, _PEER_TOKEN)
    for pattern, label in _NAME_RULES:
        if pattern.search(body):
            hits.append(label)
    if _SELF_SOYORIN.search(text or ""):
        hits.append("自称soyorin")
    for pattern, label in _DIRECTOR_RULES:
        if pattern.search(text or ""):
            hits.append(label)
    hits.extend(_secretary_hits("soyo", text))
    hits.extend(_ai_paragraph_hits(text))
    hits.extend(markdown_hits(text))
    hits.extend(_account_leak_hits(text, user_text))
    if re.search(r"小爱音[…。.\s]{0,8}你说[，,]?\s*是不是", text or ""):
        hits.append("公式转进")
    if env_peer_mode:
        hits.extend(_env_hits(text, allow_peer_address=True))
        if topic_idle:
            hits.extend(_idle_pivot_hits("soyo", text))
        if _compact_len(text) >= 8 and "小爱音" not in (text or ""):
            hits.append("未称呼小爱音")
    elif env_mode:
        hits.extend(_env_hits(text))
        if topic_idle:
            hits.extend(_idle_pivot_hits("soyo", text))
    if (peer_mode or env_peer_mode) and _uses_second_person(text):
        hits.append("互聊用了你")
    if require_address and _compact_len(text) >= 12:
        if "小爱音" not in (text or ""):
            hits.append("未称呼小爱音")
    if peer_mode and (
        looks_chase_in_flight(user_text) or looks_peer_distress_cue(user_text)
    ):
        if _CHASER_CLAIM_RE.search(text or "") or re.search(
            r"^(也好|嗯，追到了)", (text or "").strip()
        ):
            hits.append("被追却去追")
    if trigger_mode:
        hits.extend(_trigger_qa_hits(text, user_text, allow_ask=allow_ask))
        hits.extend(_third_person_peer_hits("soyo", text))
        lead = _lead_text(text)
        for pattern, label in _SOYO_FACT_QA:
            if pattern.search(lead):
                hits.append(label)
    return _uniq(hits)


def replace_assistant_text(resp: LLMChatResponse, text: str) -> LLMChatResponse:
    cleaned = resp.model_copy(deep=True)
    if not cleaned.message or not cleaned.message.content:
        return cleaned
    replaced = False
    for part in cleaned.message.content:
        if isinstance(part, LLMChatTextContent):
            part.text = text if not replaced else ""
            replaced = True
    return cleaned


def retry_rewrite(
    llm_manager: LLMManager,
    prompt: List[LLMChatMessage],
    reasons: List[str],
    logger,
    model_id: str = "",
    character: str = "soyo",
    peer_mode: bool = False,
    env_mode: bool = False,
    env_peer_mode: bool = False,
    dirty_text: str = "",
    user_text: str = "",
) -> Optional[LLMChatResponse]:
    """轻量重写：只送角色短设定 + 脏回复，避免把整段 5k+ prompt 再烧一遍。"""
    mid = (model_id or "").strip()
    if not mid:
        try:
            cfg = getattr(llm_manager, "config", None)
            mid = (getattr(getattr(cfg, "defaults", None), "llm_model", None) or "").strip()
        except Exception:
            mid = ""
    if not mid:
        logger.warning("style_guard retry skipped: no default model")
        return None
    llm = llm_manager.get_llm(mid)
    if not llm:
        logger.warning(f"style_guard retry skipped: model not registered {mid}")
        return None

    voice = (
        "你是千早爱音。碎、快、先惊、可抢话、可 Anyway。不要端茶，不要软声圆场，不要复读同伴收口。只输出一句短微信正文。"
        if character == "anon"
        else "你是长崎素世。软、先应再讲，意思放后半句。禁止爱音腔：诶？、真的假的、走啊现在、Anyway、碎句感叹号。只输出一句短微信正文。"
    )
    src = (dirty_text or "").strip()
    if not src:
        # 兜底：从原 prompt 末条 assistant 抽（少见）
        for msg in reversed(prompt or []):
            if getattr(msg, "role", None) == "assistant":
                for part in getattr(msg, "content", None) or []:
                    t = getattr(part, "text", None)
                    if t:
                        src = str(t).strip()
                        break
            if src:
                break
    if not src:
        return None

    address = _rewrite_address(
        character,
        reasons,
        peer_mode,
        env_mode=env_mode,
        env_peer_mode=env_peer_mode,
    )
    cue = (user_text or "").strip()
    cue_line = f"对方刚说：{cue[:80]}\n" if cue else ""
    keep = ""
    if looks_peer_distress_cue(cue) or _CARE_CLAUSE_RE.search(src):
        keep = (
            "原文里若在追、去看、担心同伴，必须留下这个方向；"
            "禁止改成嫌麻烦、算了明天见、鞋带搞定就完了。提问改陈述，情绪不能反。"
        )
    retry_prompt = [
        LLMChatMessage(
            role="system",
            content=[LLMChatTextContent(text=voice)],
        ),
        LLMChatMessage(
            role="user",
            content=[
                LLMChatTextContent(
                    text=(
                        f"违规：{'、'.join(reasons)}\n"
                        f"{address}"
                        f"{cue_line}"
                        f"原文：{src}\n"
                        f"{keep}"
                        "整段重写。禁止问答体、禁止提及提问者、禁止导演复盘。"
                        "不要动作说明书。只输出正文，不要解释。"
                    )
                )
            ],
        ),
    ]
    try:
        resp = llm.chat(LLMChatRequest(messages=retry_prompt, model=mid))
        try:
            from .token_meter import format_chat_token_report

            logger.info(
                format_chat_token_report(
                    retry_prompt, model=mid, resp=resp, purpose="style_guard"
                )
            )
        except Exception:
            pass
        return resp
    except Exception as exc:
        logger.warning(f"style_guard retry failed model={mid}: {exc}")
        return None
