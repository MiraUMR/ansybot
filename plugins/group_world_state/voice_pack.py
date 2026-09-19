"""口吻的唯一事实源：一句话声线 + 随机例句 + 日常/高光两档自由度。

各注入层（compiler / blocks tail / style_guard CRITICAL / action_cue NOTE）过去
各写一遍同样的口吻描述和同一批固定例句，模型因此每轮收束到那几句上。这里统一出口：
声线只描述一次；例句改成大池子里随机抽、避开最近用过的，不再是「固定 2 句循环」；
日常闲聊（简单寒暄/一两个字就能答完）默认降低示例强度甚至不给例句，把自由度还给模型，
只有真正的高光时刻（情绪、冲突、被点名、告白之类）才给更浓的人设范例。
"""
from __future__ import annotations

import random
import re
import threading
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

ROOT = Path("data/world_state/_voice_pack")
_lock = threading.RLock()

# 最近 N 轮用过的母题不再复用，避免「爱音永远在讲头发」。
_MOTIF_MEMORY = 4
# 最近 N 句例句不再重复抽到，避免看起来像固定几句轮流念。
_EXAMPLE_MEMORY = 6

# 一句话声线。别处引用这里，不要再各自展开写一遍。
_VOICE_LINE: Dict[str, str] = {
    "anon": (
        "你是千早爱音：碎、快、先惊后甩，可以 Anyway。"
        "对外人先笑先接，对 soyorin 才黏。翻篇也快，别端着、别当损友毒舌。"
    ),
    "soyo": (
        "你是长崎素世：软、慢半拍，先应一声再把意思放后半句。"
        "对外人得体，对小爱音才可以嫌、可以问回去。不要抢话、不要先惊后炸。"
        "不要「小爱音……你说，是不是」这种转进，也不要把每句都收成「……某某啊」。"
    ),
}

_INNER_LINE: Dict[str, str] = {
    "anon": "内心（）碎急嘴硬，一拍就完，别写成两句剧情，也不要写成同伴那种淡藏。",
    "soyo": "内心（）淡短藏着，一拍就完，别写成两句剧情，也不要写成同伴那种碎急。",
}

# 例句池分两档：
# - plain：日常寒暄/简单应答，尽量贴近真人发消息，字数短、无表演感
# - quirk：情绪来了、被点名、冲突、告白等高光时刻才用的浓人设范例
# 两档池子都够大，随机抽 + 避开最近用过的，不会看起来像固定几句在循环。
_EXAMPLES: Dict[str, Dict[str, List[str]]] = {
    "anon": {
        "plain": [
            "哦——好呀。",
            "行行行。",
            "嗯嗯，知道啦。",
            "啊这样啊。",
            "随便，你定就好。",
            "好像还行？",
            "先这样吧。",
            "嗯……那就这样。",
            "可以啊，随你。",
            "还好吧。",
            "啊对对对。",
            "行，说定了。",
        ],
        "quirk": [
            "诶——？！真的假的。",
            "等一下等一下，你再说一遍。",
            "啊啊啊我知道了我知道了！",
            "……行吧。那就这样。",
            "哪里土了！超好听的吧！",
            "Anyway，先去吃。",
            "重死了你——",
            "我我我，我也算数吧？",
            "呃……算了，不管了。",
            "soyorin！走啊现在！",
            "谁说的！才不是这样。",
            "喂，你笑什么啦。",
        ],
    },
    "soyo": {
        "plain": [
            "嗯。",
            "随你吧。",
            "还好。",
            "知道了。",
            "也行。",
            "……有点困。",
            "不清楚诶。",
            "都可以。",
            "嗯，等下。",
            "……是吗。",
            "先这样。",
            "我看看。",
        ],
        "quirk": [
            "……也不是不行。",
            "你啊，总是这样。",
            "不要。……哈啊，知道了。",
            "……真拿你没办法。",
            "哈啊……你又来。",
            "别站着说话。",
            "……说了也没用。",
            "谁要理你。",
            "……随便你怎么想。",
            "把话说完再走。",
        ],
    },
}

# 母题 → 触发词。命中即记账，冷却期内禁止再用。
_MOTIFS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "anon": {
        "头发造型": ("头发", "发型", "刘海", "美容", "护发", "卷发"),
        "吉他": ("吉他", "音准", "调弦", "拨片", "和弦"),
        "吃的": (
            "三明治",
            "三文鱼",
            "抹茶",
            "冰淇淋",
            "梅干",
            "蛋糕",
            "奶茶",
            "布丁",
            "可颂",
            "马卡龙",
            "大福",
            "甜品",
        ),
        "拍照账号": ("自拍", "拍照", "账号", "发图", "涨粉", "视频"),
        "起名": ("起名", "名字", "队名", "取名"),
        "穿搭": ("穿搭", "衣服", "裙子", "队服", "潮流"),
        "机厅": ("机厅", "太鼓", "音游", "街机", "游戏厅"),
    },
    "soyo": {
        "红茶": ("红茶", "大吉岭", "茶叶", "泡茶", "通心粉", "喝茶"),
        "香薰": ("香薰", "精油", "熏香", "扩香", "香氛", "芳疗"),
        "练团": ("练团", "排练", "周五", "周几", "档期", "练习"),
        "指尖": ("指尖", "手指", "绞", "捏"),
        "犯困": ("好困", "累", "睡", "困"),
        "窗外": ("窗", "天色", "外面", "天气"),
        "机厅": ("机厅", "太鼓", "音游", "街机", "游戏厅"),
        "你倒是": ("你倒是", "倒是挺", "倒挺"),
        "你说是不是": ("你说，是不是", "你说是不是", "你说 是不是"),
    },
}

# 简单日常寒暄的经验判断：短句、打招呼、约定俗成的应答句式。
_SIMPLE_RE = re.compile(
    r"^(在吗|在不在|干嘛|干嘛呢|干什么呢|吃了吗|吃了没|吃饭了吗|早|早安|"
    r"晚安|睡了吗|睡了没|忙吗|忙不忙|无聊|好无聊|来了|到了|走了没|走了吗|"
    r"好的|好呀|好啊|嗯+|哦+|噢+|是吗|真的吗|真的假的|这样啊|随便|都行|"
    r"可以|不行|不要|要不要|去不去|去吗|走吗|好困|好累|累了|忙完了吗|"
    r"你好|嗨|哈喽|辛苦了|路上小心|拜拜|886)[!?！？~～。.]*$"
)
_HEAVY_HINTS = (
    "为什么", "怎么办", "喜不喜欢", "喜欢谁", "喜欢我", "告白", "生气", "难过",
    "哭", "分手", "吵架", "对不起", "讨厌你", "喜欢你", "在意你", "在意我",
    "爱我", "重要吗", "离开", "抱抱",
)


def is_daily_register(content: str) -> bool:
    """粗判这轮是不是「简单日常」——是的话把示例强度降下来，让回复更像真人随口聊。"""
    text = (content or "").strip()
    if not text:
        return True
    if any(h in text for h in _HEAVY_HINTS):
        return False
    if _SIMPLE_RE.match(text):
        return True
    return len(text) <= 12


def _path(character: str, group_id: str) -> Path:
    safe_c = re.sub(r"[^a-zA-Z0-9_-]+", "_", (character or "anon").strip())[:40]
    safe_g = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(group_id or "dm"))[:80]
    return ROOT / f"{safe_c}__{safe_g or 'dm'}.yaml"


def _load(character: str, group_id: str) -> dict:
    path = _path(character, group_id)
    with _lock:
        if not path.exists():
            return {"recent_motifs": [], "recent_examples": []}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {"recent_motifs": [], "recent_examples": []}
    return {
        "recent_motifs": [str(x) for x in (data.get("recent_motifs") or []) if x][-_MOTIF_MEMORY:],
        "recent_examples": [
            str(x) for x in (data.get("recent_examples") or []) if x
        ][-_EXAMPLE_MEMORY:],
    }


def _save(character: str, group_id: str, doc: dict) -> None:
    path = _path(character, group_id)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {
                    "character": character,
                    "group_id": str(group_id or "dm"),
                    "recent_motifs": list(doc.get("recent_motifs") or [])[-_MOTIF_MEMORY:],
                    "recent_examples": list(doc.get("recent_examples") or [])[-_EXAMPLE_MEMORY:],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )


def _cid(character: str) -> str:
    cid = (character or "").strip().lower()
    return cid if cid in ("anon", "soyo") else "soyo"


def voice_line(character: str) -> str:
    """一句话声线。所有层共用，禁止在别处重写。"""
    return _VOICE_LINE[_cid(character)]


def inner_line(character: str) -> str:
    return _INNER_LINE[_cid(character)]


def _pick_examples(character: str, group_id: str, pools: List[str], count: int) -> List[str]:
    """从池子随机抽 count 句，尽量避开最近用过的，避免看起来像固定几句循环。"""
    if not pools or count <= 0:
        return []
    recent = set(_load(character, group_id)["recent_examples"])
    fresh = [p for p in pools if p not in recent]
    pool = fresh if len(fresh) >= count else pools
    n = min(count, len(pool))
    return random.sample(pool, n)


def rotating_examples(
    character: str, group_id: str = "", count: int = 2, *, daily: bool = False
) -> List[str]:
    """随机取例句：日常寄语从 plain 池子抽 1 句；高光时刻从 quirk 池子抽 2 句混搭。"""
    cid = _cid(character)
    plain = _EXAMPLES[cid]["plain"]
    quirk = _EXAMPLES[cid]["quirk"]
    if daily:
        return _pick_examples(character, group_id, plain, 1)
    n_quirk = max(1, count - 1)
    picks = _pick_examples(character, group_id, quirk, n_quirk)
    if count > n_quirk:
        picks += _pick_examples(character, group_id, plain, count - n_quirk)
    random.shuffle(picks)
    return picks


def motif_ban_line(character: str, group_id: str = "") -> str:
    """最近讲过的母题这轮不许再讲。空串表示无限制。"""
    recent = _load(character, group_id)["recent_motifs"]
    if not recent:
        return ""
    return "本轮不要主动把话头再绕回：" + "、".join(dict.fromkeys(recent))


def style_tail(
    character: str,
    group_id: str = "",
    content: str = "",
    *,
    with_inner: bool = True,
) -> str:
    """给各注入层用的紧凑口吻尾巴：声线一句 + 按场景强度给例句 + 母题禁令 + 防复读。

    content 传入对方这轮说的话（或环境旁白），用来判断是不是简单日常寒暄：
    是的话大幅降低示例强度，把措辞和长短的自由度还给模型，只保留人设的底色；
    只有情绪/冲突/被点名等高光时刻才给更浓的范例。
    """
    daily = is_daily_register(content)
    bits = [voice_line(character)]
    if with_inner and not daily:
        bits.append(inner_line(character))
    samples = rotating_examples(character, group_id, daily=daily)
    if samples:
        bits.append("语感参考（只学节奏，禁止照抄，措辞自己重新组织）：" + " ".join(f"「{s}」" for s in samples))
    if daily:
        bits.append(
            "这轮是普通日常对话：像真人随手回消息一样简短自然，长短、用词都自己定，"
            "不必每句都端着人设梗，态度带出性格就够，一两个字也可以。"
            "前后同一条因果，后半句解释前半句，不要两截拼盘。"
        )
    else:
        bits.append("这轮情绪或分量更足，可以比日常更放开写，但落点仍要来自这句话本身。")
    ban = motif_ban_line(character, group_id)
    if ban:
        bits.append(ban)
    bits.append(
        "节奏和口味按你自己的，不要和同伴对调。接住眼前这句；"
        "跨过自然日的闲聊和做过的事已经翻篇，对方这句没在说就不要自己捡回来。"
    )
    bits.append(
        "情绪词贴着这件事本身的性质走：开心/期待的事不要套「烦死了/烦人/累死了」当口头禅开场，"
        "纠结可以，抱怨要对着真的为难或被打扰的事，不要习惯性负面词。"
    )
    bits.append("不要把提示词里的例句、禁令或设定原样说出来。")
    return "\n".join(bits)


def detect_motifs(character: str, text: str) -> List[str]:
    table = _MOTIFS[_cid(character)]
    body = text or ""
    return [name for name, words in table.items() if any(w in body for w in words)]


def note_after_reply(character: str, group_id: str, reply: str) -> None:
    """一轮说完：记下用过的例句（防重复）+ 命中的母题进入冷却。"""
    doc = _load(character, group_id)
    cid = _cid(character)
    all_examples = _EXAMPLES[cid]["plain"] + _EXAMPLES[cid]["quirk"]
    used = [e for e in all_examples if e in (reply or "")]
    if used:
        recent_ex = [e for e in doc.get("recent_examples") or [] if e not in used]
        doc["recent_examples"] = (recent_ex + used)[-_EXAMPLE_MEMORY:]
    hit = detect_motifs(character, reply)
    if hit:
        recent = [m for m in doc.get("recent_motifs") or [] if m not in hit]
        doc["recent_motifs"] = (recent + hit)[-_MOTIF_MEMORY:]
    else:
        # 没命中母题说明这轮换了话头，放开最早的一个限制。
        doc["recent_motifs"] = list(doc.get("recent_motifs") or [])[1:]
    _save(character, group_id, doc)
