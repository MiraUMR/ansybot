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
    sents = _sentences(para)
    if len(sents) >= 2 and _is_reaction(sents[0]):
        sents = sents[1:]
    sent = (sents[0] if sents else para).strip()
    clauses = _clauses(sent)
    while len(clauses) > 1 and _is_filler(clauses[0]):
        clauses = clauses[1:]
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


def normalize_ja_for_tts(text: str) -> str:
    """给 GPT-SoVITS 的日文：拉长音、补句号，减少吞字。"""
    t = (text or "").strip().strip("\"'`「」『』")
    t = t.replace("～", "ー").replace("~", "ー")
    t = t.replace("……", "、").replace("…", "、")
    t = t.replace("——", "、").replace("—", "、")
    t = re.sub(r"\s+", "", t)
    if t and t[-1] not in "。！？!?":
        t += "。"
    return t


def spoken_japanese(text: str, character: str, max_sentences: int = 2) -> str:
    """先切语义短句，能词典译就译。"""
    clip = first_voice_clip(text)
    return clip_to_japanese(clip, character) or clip
