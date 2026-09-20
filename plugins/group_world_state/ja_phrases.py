"""把本轮第一句按语义切出一小段，再可选映射成日文。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

PHRASE_PATH = Path("data/tts/ja_phrases.yaml")
_KANA = re.compile(r"[\u3040-\u30ff]")
_PUNCT = re.compile(r"[\s\[\]【】()（）<>《》\"'“”‘’~～、,，.。!！?？…—\-]+")
_SPLIT = re.compile(r"(?:<break>|[。！？!?]|[\n/]|…{1,3}|~{2,})")
_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\U0000FE00-\U0000FE0F"
    "]+"
)
_EXPLAIN = re.compile(r"^(感觉|因为|所以|说是|估计|要是)")
_PUNCHY = re.compile(r"超[～~]?有感觉|太[棒好赞了]|真的假的|好喜欢|好烦|^不行$")
_DEPENDENT = re.compile(r"^(看起来|看上去|好像|感觉|觉得|挺|有点|有点儿)")
_FILLER_CORE = re.compile(r"^(唔+|嗯+|啊+|诶+|哦+|哈+|额+|呃+|唉+|明天啊|那个|就是)$")
_LEAD_MARK = re.compile(r"^(其实|不过|就是|反正|然后)")
_DASH = re.compile(r"[—–\-－]{1,2}")
_REACT_END = re.compile(r"(啦|啊|呀|呢|吧|哦|诶)[！!？?]*$")
_ANON_NAME = re.compile(
    r"千早爱音|小爱音|爱音ちゃん|爱音|"
    r"あのんちゃん|あのん|"
    r"anon[\s\-]*chan|anonchan|\banon\b",
    re.I,
)
_SOYO_NAME = re.compile(
    r"长崎素世|素世世|素世|"
    r"そよりん|(?<![ぁ-んァ-ン])そよ(?![ぁ-んァ-ン])|"
    r"soyorin|\bsoyo\b",
    re.I,
)
_ZH_LEFT = re.compile(
    r"什么|怎么|这样啊|语音|听到|顺耳|太想|闲着|发语音|"
    r"嘿嘿+|哈哈+|诶+|嗯嗯|哦哦|"
    r"[聽发们这这您啥嘿吗嘛啦]"
)
_LAUGH_RE = re.compile(
    r"(?:あ+っ?はは+|わはは+|ははは+|えへへ+|うふふ+|ふふふ+|ひひひ+|"
    r"あっはっは+|aha+|haha+|hehe+|ww+|ｗｗ+)",
    re.I,
)
_KATA_ANON = re.compile(r"アノン(?:[・\s-]?(?:チャン|ちゃん))?", re.I)
_KATA_SOYO = re.compile(r"ソヨリン")
_LAUGH_THEN_NAME = re.compile(
    r"(えへっ|あはっ|ふふっ|わはっ)[ー~～]*[、,]*\s*(あのんちゃん|そよりん)"
)
_JP_SHARED = {
    "突然",
    "明日",
    "今日",
    "一緒",
    "本当",
    "大丈夫",
    "時間",
    "今",
    "声",
    "名前",
}

_cache: Dict[str, object] = {"mtime": None, "data": None}


def _load() -> dict:
    mtime = PHRASE_PATH.stat().st_mtime if PHRASE_PATH.exists() else None
    if _cache["data"] is not None and _cache["mtime"] == mtime:
        return _cache["data"]  # type: ignore[return-value]
    data: dict = {"max_sentences": 2, "common": {}, "anon": {}, "soyo": {}}
    if PHRASE_PATH.exists() and yaml is not None:
        loaded = yaml.safe_load(PHRASE_PATH.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data.update(loaded)
    _cache["mtime"] = mtime
    _cache["data"] = data
    return data


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = t.replace("anyway", "")
    return _PUNCT.sub("", t)


def split_phrases(text: str, max_sentences: int = 2) -> List[str]:
    raw = (text or "").replace("\r", "\n")
    parts = [p.strip(" 　\t-—") for p in _SPLIT.split(raw)]
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if re.fullmatch(r"[\[\]【】.。!！?？~～、,，]+", p):
            continue
        out.append(p)
        if len(out) >= max(1, max_sentences):
            break
    return out


def _table(character: str) -> List[Tuple[str, str, str]]:
    data = _load()
    merged: Dict[str, str] = {}
    for bucket in ("common", character):
        block = data.get(bucket) or {}
        if isinstance(block, dict):
            for k, v in block.items():
                ks, vs = str(k).strip(), str(v).strip()
                if ks and vs:
                    merged[ks] = vs
    rows = [(_norm(k), k, v) for k, v in merged.items() if _norm(k)]
    rows.sort(key=lambda x: len(x[0]), reverse=True)
    return rows


def _already_ja(text: str) -> bool:
    return bool(_KANA.search(text or ""))


def _core_len(text: str) -> int:
    return len(re.sub(r"[^\u4e00-\u9fffA-Za-z0-9ぁ-んァ-ン]", "", text or ""))


def _first_paragraph(text: str) -> str:
    t = (text or "").replace("\r", "\n").replace("<break>", "\n")
    t = _EMOJI.sub("", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n+", "\n", t).strip()
    if not t:
        return ""
    return t.split("\n", 1)[0].strip()


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[。！？!?])\s*", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _is_name_callout(sent: str) -> bool:
    """「soyorin——！」只是叫人，语音切下一句。"""
    core = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9ぁ-んァ-ン]", "", sent or "")
    if not core or len(core) > 12:
        return False
    names = (
        "soyorin",
        "soyo",
        "anon",
        "anonrin",
        "小爱音",
        "爱音",
        "素世",
        "素世世",
        "长崎素世",
        "千早爱音",
        "あのん",
        "そよ",
    )
    return core.lower() in {n.lower() for n in names}


def _is_reaction(sent: str) -> bool:
    s = (sent or "").strip()
    if not s or _core_len(s) > 16:
        return False
    return bool(_REACT_END.search(re.sub(r"\s+", "", s)))


def _clauses(sent: str) -> List[str]:
    parts = re.split(r"[，,、；;]", (sent or "").strip("。！？!? "))
    out: List[str] = []
    for part in parts:
        for bit in _DASH.split(part):
            bit = bit.strip()
            if bit:
                out.append(bit)
    return out


def _is_filler(clause: str) -> bool:
    s = re.sub(r"[\s…·]", "", clause or "")
    if not s:
        return True
    core = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9ぁ-んァ-ン]", "", s)
    if _core_len(core) <= 2 and re.fullmatch(r"[唔嗯啊诶哦哈额呃唉]+", core or ""):
        return True
    return bool(_FILLER_CORE.fullmatch(core))


def _prefer_punchline(clauses: List[str]) -> bool:
    if len(clauses) < 2:
        return False
    last = clauses[-1]
    head = "".join(clauses[:-1])
    if _DEPENDENT.match(last) or _EXPLAIN.match(last) or _core_len(last) > 12:
        return False
    if _PUNCHY.search(last) and _core_len(last) <= 12:
        return True
    return _core_len(last) <= 10 and _core_len(head) >= max(8, int(_core_len(last) * 1.5))


def first_voice_clip(text: str) -> str:
    """本轮第一句按语义切开：跳过口头垫话，带上被形容的那件事。"""
    para = _first_paragraph(text)
    if not para:
        return ""
    sents = [s for s in _sentences(para) if _core_len(s) > 0]
    if len(sents) >= 2 and _is_reaction(sents[0]):
        sents = [sents[0].rstrip() + sents[1]] + sents[2:]
    if len(sents) >= 2 and _is_name_callout(sents[0]):
        sents = [sents[0].rstrip("！!?。 ") + "，" + sents[1]] + sents[2:]
    if not sents:
        rest = (text or "").replace("\r", "\n")
        rest = rest.split("\n", 1)[1].strip() if "\n" in rest else ""
        return first_voice_clip(rest) if rest else ""
    sent = sents[0].strip()
    clauses = _clauses(sent)
    if clauses:
        clauses[0] = _LEAD_MARK.sub("", clauses[0]).strip() or clauses[0]
    clauses = [c for c in clauses if c]
    if not clauses:
        return sent.strip("。！？!? ")
    if _prefer_punchline(clauses):
        return clauses[-1].strip("。！？!? ")
    acc: List[str] = []
    for i, clause in enumerate(clauses):
        if acc and _EXPLAIN.match(clause) and not _DEPENDENT.match(clause):
            break
        nxt = acc + [clause]
        joined = "，".join(nxt)
        next_dep = i + 1 < len(clauses) and _DEPENDENT.match(clauses[i + 1])
        if acc and _core_len(joined) > 24 and not _DEPENDENT.match(clause):
            break
        acc = nxt
        if _core_len("，".join(acc)) >= 12 and len(acc) >= 2 and not next_dep:
            break
    return "，".join(acc).strip("。！？!? ") if acc else clauses[0]


_DEFAULT_JA = {
    "anon": "え、なにそれ",
    "soyo": "ふうん",
}


def clip_to_japanese(clip: str, character: str) -> str:
    """词典精确命中才返回日文；短 key 不再当子串乱配。"""
    t = (clip or "").strip()
    if not t:
        return ""
    if _already_ja(t):
        return normalize_ja_for_tts(t)
    key = _norm(t)
    for nk, _orig, ja in _table(character):
        if key == nk:
            return normalize_ja_for_tts(ja)
    clauses = _clauses(t)
    if len(clauses) < 2:
        return ""
    rows = _table(character)
    bits: List[str] = []
    for clause in clauses:
        ck = _norm(clause)
        hit = ""
        for nk, _orig, ja in rows:
            if ck == nk:
                hit = ja
                break
        if not hit:
            return ""
        bits.append(hit)
    return normalize_ja_for_tts("、".join(bits))


def stabilize_ja_laugh(text: str) -> str:
    """长串笑声在 SoVITS 里容易破音，收成带促音的短笑。"""

    def _one(match: re.Match) -> str:
        raw = match.group(0) or ""
        low = raw.lower()
        if "えへ" in raw or "hehe" in low:
            return "えへっ"
        if "うふ" in raw or "ふふ" in raw:
            return "ふふっ"
        if "わは" in raw:
            return "わはっ"
        return "あはっ"

    t = _LAUGH_RE.sub(_one, text or "")
    t = re.sub(r"嘿嘿+", "えへっ", t)
    t = re.sub(r"哈哈+|呵+", "あはっ", t)
    t = _LAUGH_THEN_NAME.sub(r"\1、\2", t)
    t = re.sub(r"(えへっ|あはっ|ふふっ|わはっ)ー+", r"\1", t)
    return t


def lock_character_names(text: str) -> str:
    """语音日文里人名固定假名：爱音→あのんちゃん，素世→そよりん。罗马音在 all_ja 下会破音。"""
    t = text or ""
    t = _KATA_ANON.sub("あのんちゃん", t)
    t = _KATA_SOYO.sub("そよりん", t)
    t = _ANON_NAME.sub("あのんちゃん", t)
    t = _SOYO_NAME.sub("そよりん", t)
    t = re.sub(r"anon\s*chan", "あのんちゃん", t, flags=re.I)
    return t


def ja_has_zh_leftover(ja: str, zh: str = "") -> bool:
    """日文里还夹着中文词，就不能送 TTS。"""
    t = ja or ""
    if not t:
        return False
    if _ZH_LEFT.search(t):
        return True
    for m in re.findall(r"[\u4e00-\u9fff]{2,}", zh or ""):
        if m in t and m not in _JP_SHARED:
            return True
    return False


def is_spoken_japanese(text: str, zh: str = "") -> bool:
    t = (text or "").strip()
    if not t or ja_has_zh_leftover(t, zh):
        return False
    if _KANA.search(t):
        return True
    low = t.lower()
    return (
        "あのんちゃん" in t
        or "そよりん" in t
        or "anon chan" in low
        or "anonchan" in low
        or "soyorin" in low
    )


def normalize_ja_for_tts(text: str) -> str:
    """给 GPT-SoVITS 的日文：假名称呼、短笑声、拉长音。罗马音和长串はは会破音。"""
    t = (text or "").strip().strip("\"'`「」『』")
    t = stabilize_ja_laugh(t)
    t = lock_character_names(t)
    t = stabilize_ja_laugh(t)
    t = t.replace("～", "ー").replace("~", "ー")
    t = t.replace("……", "、").replace("…", "、")
    t = t.replace("——", "、").replace("—", "、")
    t = re.sub(r"ー{2,}", "ー", t)
    t = re.sub(r"(えへっ|あはっ|ふふっ|わはっ)ー+", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(?<![A-Za-z]) (?![A-Za-z])", "", t)
    t = _LAUGH_THEN_NAME.sub(r"\1、\2", t)
    if t and t[-1] not in "。！？!?":
        t += "。"
    return t


def spoken_japanese(text: str, character: str, max_sentences: int = 2) -> str:
    """先切语义短句，能词典译就译。"""
    clip = first_voice_clip(text)
    return clip_to_japanese(clip, character) or clip
