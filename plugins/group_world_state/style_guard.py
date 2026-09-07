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
        "⚠️ 特别注意（素世版）：事实/日期/设定题也用素世的口气直接说，"
        "可以模糊、可以夹私货。禁止百科句，禁止先写动作说明书，禁止纠错腔。"
    ),
    "anon": (
        "⚠️ 特别注意（爱音版）：事实题先有点情绪再带出信息，允许夸张。"
        "不要平铺直叙。不要每条都拐去 soyorin；只有事实本身关于她时才点名。"
    ),
}


def critical_block_for(character: str) -> str:
    addon = CRITICAL_ADDONS.get(character) or CRITICAL_ADDONS["soyo"]
    call = "小爱音" if character != "anon" else "soyorin"
    if character == "anon":
        voice = (
            "用千早爱音的口吻：碎、快、可以抢话、可以 Anyway。"
            "不是温柔秘书，不是完整礼貌句。"
        )
    else:
        voice = (
            "用长崎素世的口吻：淡、短、可以懒、可以嫌。"
            "不是客服完整句，不是行程安排。"
        )
    return (
        "[CRITICAL]\n"
        f"{voice}禁止问答体。禁止提及提问者（不要说有人问/你问的）。\n"
        "不要把无关问题都转化成找同伴；若本轮已经涉及同伴，必须用规定称呼"
        f"（{call}），这不是强制绑定。\n"
        f"{addon}\n"
        "禁止导演复盘，禁止动作说明书和小说旁白。像本人发微信，不是客服。\n"
        "[/CRITICAL]"
    )


def critical_instruction_for(character: str, mode: str) -> str:
    """工作流 P0：仅 story / direct（Trigger）非空，挂在系统提示末尾覆盖低层规则。"""
    cid = character if character in ("soyo", "anon") else "soyo"
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
    if cid == "anon":
        fact = (
            "事实查询：先有口气再带出信息，允许夸张；禁止平铺确认腔；"
            "不要每条都拐去 soyorin。"
        )
    else:
        fact = (
            "事实查询：用素世口气直接说，可以模糊、可以夹私货；"
            "禁止纠错腔；禁止百科句。"
        )
    return (
        "[P0: NARRATIVE LOCK ACTIVE]\n"
        "⚠️ direct/@ 最高优先级：Trigger + 本指令覆盖 Base「接话」惯性。\n"
        f"- {fact}\n"
        "- 对群友：禁问答体/复读选择问/给许可拒绝；无问号提问也改陈述。\n"
        "- 点名同伴：类型3，用规定称呼当面说；禁「她」向群友转述。\n"
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

_AI_SECRETARY_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"我记下了"), "我记下了"),
    (re.compile(r"你负责"), "你负责"),
    (re.compile(r"的样子我还记得"), "的样子我还记得"),
    (re.compile(r"别再看手机"), "别再看手机"),
    (re.compile(r"这次我帮你"), "这次我帮你"),
]
# AI 段落句：让步 + 条件兜底 + 约时间，读起来像助理排期。
_AI_PARAGRAPH_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"(也行|好吧|行吧)[，,].{0,24}(要是|如果)"), "AI让步条件句"),
    (re.compile(r"(踩雷|搞砸|弄砸).{0,10}(我找你|找你|你负责)"), "AI行程兜底句"),
    (re.compile(r"(周末|周[一二三四五六日天]|明天|后天|下午|晚上).{0,8}吧[，,].{0,10}(我空着|我有空|没事干|有空)"), "AI约时间句"),
    (re.compile(r"(安排明白|安排清楚|帮你约好|我来安排)"), "AI安排腔"),
]
_OPEN_SOYO = re.compile(r"^[\s\*＿_]*小爱音[，,]")
_OPEN_ANON = re.compile(r"(?i)^[\s\*＿_]*soyorin[，,]")

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
    "禁止用「她」向群友转述同伴。"
    "禁止反问（吗/对吧/真的假的/要不要），禁止答题（会的/大概就是）。"
    "禁止AI段落句：不要「也行，要是踩雷了就找你。周末下午吧，我空着」这种让步+兜底+约时间。"
    "改成角色正在发的一句短微信，碎一点、停半拍，不要排期说明书。"
    "{address}"
    "用角色本人说话，禁止秘书腔（我记下了/你负责/我来安排）。"
    "禁止「soyorin，」或「小爱音，」当抬头。不要动作说明书，不要叙事内化。"
)

# 重写仍脏时的硬兜底（无问号、无禁用称呼、不答题）
_FALLBACK_DIRECT = {
    "anon": "哇——等等！",
    "soyo": "……稍等。",
}
_FALLBACK_ENV = {
    "anon": "……好困。",
    "soyo": "……水开了。",
}
_FALLBACK_PEER = {
    "anon": "嗯！",
    "soyo": "知道了。",
}


def fallback_safe_reply(
    character: str,
    *,
    trigger_mode: bool = False,
    peer_mode: bool = False,
    env_mode: bool = False,
) -> str:
    cid = character if character in ("anon", "soyo") else "soyo"
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
        for r in ("AI让步条件句", "AI行程兜底句", "AI约时间句", "AI安排腔", "AI三段安排句")
    ):
        extra += (
            "拆掉排期腔：不要一次说完「也行+要是踩雷+周末空着」。"
            "改成一两句短反应，时间含糊带过或干脆不约。"
        )
    if env_peer_mode:
        call = "soyorin" if character == "anon" else "小爱音"
        return extra + (
            f"本轮是环境闲聊里主动点同伴：必须出现「{call}」，"
            "可对同伴用「你」；禁止回答旁白、禁止找说话人；不要括号动作。"
            "保留 [CQ:at,qq=…] 原样。"
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
        return extra + f"本轮是互聊，必须出现「{call}」，但禁止「{call}，」当抬头。"
    if any("Phone禁括号" in r or r.startswith("括号过长") for r in reasons):
        return extra + (
            "去掉所有 ()【】（）动作/神态括号；Phone 用 emoji 或纯文字暗示；"
            "F2F 若保留动作则单段≤6字且勿心理独白。只输出正文。\n"
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

    不把爱音式兴奋标点（！？/？！）、叠问「在哪在哪」当成对群友的问答体。
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
    if re.search(r"(会不会|要不要|是不是|能不能|好不好|行不行)", t):
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


def _ask_hits(text: str) -> List[str]:
    raw = text or ""
    if re.search(r"哪有|才不是|谁要啊", raw):
        return []
    # 纯兴奋叠问：在哪在哪——！
    if re.search(r"(在哪在哪|哪里哪里)", raw) and not re.search(
        r"快说|哪家|告诉我|吗([。.!！…\s]|$)", raw
    ):
        # 若整段几乎只有兴奋句，不记提问
        stripped = re.sub(
            r"(在哪在哪|哪里哪里)[—\-！!。.…\s]*",
            "",
            re.sub(r"[！!][？?]|[？?][！!]", "", raw),
        )
        stripped = re.sub(r"[\s…]+", "", stripped)
        if len(stripped) <= 12 and not re.search(r"[？?吗]", stripped):
            return []
    hits: List[str] = []
    t_chk = re.sub(r"[！!][？?]|[？?][！!]", "", raw)
    if re.search(r"[？?]", t_chk):
        hits.append("提问句")
    if re.search(r"吗([。.!！…\s]|$)", raw):
        hits.append("提问句")
    if re.search(r"(对吧|是吧|不是吧)([。.!！…\s]|$)", raw):
        hits.append("求证提问")
    if re.search(r"真的假的[吗啊呢]", raw):
        hits.append("求证提问")
    if re.search(r"(会不会|要不要|是不是|能不能|好不好|行不行)", raw):
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


def salvage_non_ask_reply(text: str) -> Optional[str]:
    """重写仍脏时：尽量保留不含提问的分句，避免发出空洞兜底。"""
    raw = (text or "").strip()
    if not raw:
        return None
    # 按断句切；保留不含提问的片段
    parts = re.split(r"(?<=[。！!？?\n])\s*", raw)
    kept: List[str] = []
    for p in parts:
        bit = (p or "").strip()
        if not bit:
            continue
        if _ask_hits(bit):
            continue
        kept.append(bit)
    if not kept:
        # 再试：去掉「在哪…」「快说…」后的残留
        cleaned = re.sub(r"(快说.{0,12}|在哪(?:在哪)?[^。！!\n]{0,12})", "", raw)
        cleaned = re.sub(r"[？?]+", "！", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned and not _ask_hits(cleaned) and len(re.sub(r"\s+", "", cleaned)) >= 2:
            return cleaned
        return None
    out = "".join(kept).strip()
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
        if label == "复读选择问" and allow_ask:
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
    if require_address and _compact_len(text) >= 12:
        if not re.search(r"(?i)soyorin", text or ""):
            hits.append("未称呼soyorin")
    if trigger_mode:
        hits.extend(_trigger_qa_hits(text, user_text, allow_ask=allow_ask))
        hits.extend(_third_person_peer_hits("anon", text))
        lead = _lead_text(text)
        for pattern, label in _ANON_FACT_QA:
            if pattern.search(lead):
                hits.append(label)
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
) -> List[str]:
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
    if require_address and _compact_len(text) >= 12:
        if "小爱音" not in (text or ""):
            hits.append("未称呼小爱音")
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
        "你是千早爱音。碎、快、可抢话。只输出一句短微信正文。"
        if character == "anon"
        else "你是长崎素世。淡、短、可懒。只输出一句短微信正文。"
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
                        f"原文：{src}\n"
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
