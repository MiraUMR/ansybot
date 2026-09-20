"""从 Bestdori 抓区域对话/后台闲聊台词，本地炼成说话模式 yaml。"""
from __future__ import annotations

import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "speech_model",
    ROOT / "plugins" / "group_world_state" / "speech_model.py",
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
lock_example = _mod.lock_example
peer_safe = _mod.peer_safe

OUT = ROOT / "data" / "voice_patterns"
CACHE = OUT / "cache"
CORPUS = OUT / "corpus"
INFO_URL = "https://bestdori.com/api/explorer/{locale}/assets/_info.json"
LIST_URL = "https://bestdori.com/api/explorer/{locale}/assets/{path}.json"
ASSET_URL = "https://bestdori.com/assets/{locale}/{path}_rip/{name}"
UA = "Mozilla/5.0 (compatible; ansy-bot-speech/1.0)"
CHAR_IDS = {37: "anon", 39: "soyo"}
CHAT_MAX = 36
CHAT_MIN = 2

# 聊天语音：地图气泡 ActionSet、区域/afterlive 剧情、MyGO band 小剧场、后台 talkset。
WALK_PREFIXES = (
    ("actionset",),
    ("scenario", "actionset"),
    ("scenario", "afterlivetalk"),
    ("scenario", "band", "045"),
    ("backstage", "talkset"),
)

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_KANA = re.compile(r"[\u3040-\u30ff]")
_QUIRK = re.compile(r"[！!？?~～…]|诶|Anyway|anyway|哈啊|啊啊|呜|才不|才不是")
STARTERS = (
    "诶",
    "啊",
    "嗯",
    "哈",
    "Anyway",
    "那个",
    "不是",
    "好啦",
    "喂",
    "……",
    "行",
)


def _req(url: str, timeout: int = 30) -> bytes:
    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            last = exc
            time.sleep(0.4 * (attempt + 1))
    raise last or RuntimeError(url)


def _load_json(url: str) -> Any:
    return json.loads(_req(url).decode("utf-8"))


def _clean(text: str) -> str:
    t = _TAG.sub("", text or "")
    t = t.replace("\r", " ").replace("\n", "")
    t = t.replace("「", "").replace("」", "")
    return _SPACE.sub(" ", t).strip()


def _leaf_dirs(node: Any, prefix: Tuple[str, ...]) -> List[Tuple[str, ...]]:
    if isinstance(node, dict):
        out: List[Tuple[str, ...]] = []
        for key, child in node.items():
            out.extend(_leaf_dirs(child, (*prefix, str(key))))
        return out
    return [prefix]


def list_assets(locale: str, directory: Tuple[str, ...]) -> List[str]:
    path = "/".join(directory)
    url = LIST_URL.format(locale=locale, path=path)
    try:
        names = _load_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    out: List[str] = []
    for n in names:
        if not isinstance(n, str) or not n.endswith(".asset") or n.startswith("."):
            continue
        if "Timeline" in n or n.startswith(("Animation", "Character", "Camera")):
            continue
        if n.startswith(("ActionSet", "Scenario", "BackstageTalkSet")):
            out.append(n)
    return out


def download_asset(locale: str, directory: Tuple[str, ...], name: str) -> Optional[Path]:
    rel = Path(*directory) / name
    dest = CACHE / locale / rel
    if dest.exists() and dest.stat().st_size > 40:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = ASSET_URL.format(locale=locale, path="/".join(directory), name=name)
    try:
        data = _req(url)
    except Exception:
        return None
    if not data or data[:1] == b"<":
        return None
    dest.write_bytes(data)
    return dest


def _row(cid: int, text: str, voice_id: str, source: str) -> Dict[str, Any]:
    return {
        "character": CHAR_IDS[cid],
        "character_id": cid,
        "text": text,
        "voice_id": voice_id,
        "source": source,
    }


def _ids_from(value: Any) -> List[int]:
    if isinstance(value, int) and value in CHAR_IDS:
        return [value]
    if isinstance(value, list):
        return [int(x) for x in value if x in CHAR_IDS]
    return []


def extract_lines(path: Path) -> List[Dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    base = (doc.get("Base") or {}) if isinstance(doc, dict) else {}
    if not isinstance(base, dict):
        return []
    rows: List[Dict[str, Any]] = []
    source = path.name

    for talk in base.get("talkData") or []:
        if not isinstance(talk, dict):
            continue
        body = _clean(str(talk.get("body") or ""))
        if not body:
            continue
        ids: List[int] = []
        voice_id = ""
        for voice in talk.get("voices") or []:
            if not isinstance(voice, dict):
                continue
            cid = voice.get("characterId")
            if cid in CHAR_IDS:
                ids.append(int(cid))
                voice_id = str(voice.get("voiceId") or voice_id)
        if not ids:
            for ch in talk.get("talkCharacters") or []:
                if isinstance(ch, dict):
                    ids.extend(_ids_from(ch.get("characterId")))
        for cid in dict.fromkeys(ids):
            rows.append(_row(cid, body, voice_id, source))

    for det in base.get("details") or []:
        if not isinstance(det, dict):
            continue
        ids = _ids_from(det.get("characterId"))
        if not ids:
            continue
        for ball in det.get("balloons") or []:
            if not isinstance(ball, dict):
                continue
            body = _clean(str(ball.get("message") or ""))
            if not body:
                continue
            for cid in ids:
                rows.append(_row(cid, body, str(ball.get("voiceId") or ""), source))

    for snip in base.get("snippets") or []:
        if not isinstance(snip, dict):
            continue
        body = _clean(str(snip.get("talkText") or snip.get("body") or ""))
        if not body:
            continue
        ids = _ids_from(snip.get("characterIds")) or _ids_from(snip.get("characterId"))
        voice_id = str(snip.get("voiceId") or "")
        for cid in dict.fromkeys(ids):
            rows.append(_row(cid, body, voice_id, source))
    return rows


def collect_targets(info: Dict[str, Any]) -> List[Tuple[str, ...]]:
    targets: List[Tuple[str, ...]] = []
    for prefix in WALK_PREFIXES:
        node: Any = info
        ok = True
        for key in prefix:
            if not isinstance(node, dict) or key not in node:
                ok = False
                break
            node = node[key]
        if not ok:
            continue
        targets.extend(_leaf_dirs(node, prefix))
    return targets


def fetch_locale(locale: str) -> List[Dict[str, Any]]:
    print(f"index {locale} ...")
    info = _load_json(INFO_URL.format(locale=locale))
    dirs = collect_targets(info)
    jobs: List[Tuple[Tuple[str, ...], str]] = []
    for directory in dirs:
        names = list_assets(locale, directory)
        for name in names:
            jobs.append((directory, name))
    print(f"{locale} assets={len(jobs)} dirs={len(dirs)}")
    rows: List[Dict[str, Any]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {
            pool.submit(download_asset, locale, d, n): (d, n) for d, n in jobs
        }
        for fut in as_completed(futs):
            done += 1
            path = fut.result()
            if path:
                rows.extend(extract_lines(path))
            if done % 200 == 0:
                print(f"  {locale} {done}/{len(jobs)} lines={len(rows)}")
    return rows


def _is_chat(text: str) -> bool:
    n = len(re.sub(r"\s+", "", text))
    if n < CHAT_MIN or n > CHAT_MAX:
        return False
    if text.count("。") >= 3:
        return False
    return True


def _is_quirk(text: str) -> bool:
    return bool(_QUIRK.search(text)) or text.endswith(("！", "!", "？", "?"))


def _pct(values: List[int], p: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round((len(s) - 1) * p))))
    return s[idx]


def _top(counter: Counter, n: int) -> List[str]:
    return [k for k, _ in counter.most_common(n) if k]


def distill(character: str, lines: Iterable[str]) -> Dict[str, Any]:
    uniq: List[str] = []
    seen = set()
    for raw in lines:
        t = lock_example(character, re.sub(r"[ \t]{2,}", " ", (raw or "").strip()))
        if not t or t in seen or _KANA.search(t):
            continue
        # soyo 自报家门（我是爽世/我叫素世/我是Soyorin）不进池：否则教她第三人称自称。
        if character == "soyo" and _SELF_NAME_RE.search(t):
            continue
        seen.add(t)
        uniq.append(t)
    chat = [t for t in uniq if _is_chat(t)]
    lengths = [len(re.sub(r"\s+", "", t)) for t in chat] or [0]
    start_c: Counter = Counter()
    end_c: Counter = Counter()
    for t in chat:
        for s in STARTERS:
            if t.startswith(s):
                start_c[s] += 1
                break
        else:
            start_c[t[:1]] += 1
        end_c[t[-1]] += 1
    quirk = [t for t in chat if _is_quirk(t) and peer_safe(t)]
    plain = [t for t in chat if t not in quirk and peer_safe(t)]
    if len(plain) < 12:
        plain = [t for t in chat if not _is_quirk(t)] or chat
    if len(quirk) < 8:
        quirk = [t for t in chat if _is_quirk(t)] or chat
    random.Random(37 if character == "anon" else 39).shuffle(plain)
    random.Random(137 if character == "anon" else 139).shuffle(quirk)
    p50 = _pct(lengths, 0.5)
    p75 = _pct(lengths, 0.75)
    starts = _top(start_c, 6)
    if character == "anon":
        voice = (
            f"官方台词节奏：中位大约{p50}字，少写过{p75}字的说明书。"
            f"常以{'/'.join(starts[:4]) or '诶'}起手，对 soyorin 才黏。"
        )
    else:
        voice = (
            f"官方台词节奏：中位大约{p50}字，少写过{p75}字的说明书。"
            f"常以{'/'.join(starts[:4]) or '嗯'}起手，对小爱音才嫌。"
        )
    return {
        "character": character,
        "source": "bestdori-cn",
        "n_lines": len(uniq),
        "n_chat": len(chat),
        "length": {
            "p25": _pct(lengths, 0.25),
            "p50": p50,
            "p75": p75,
        },
        "starters": starts,
        "endings": _top(end_c, 6),
        "voice_line": voice,
        "plain": plain[:80],
        "quirk": quirk[:80],
    }


def main() -> int:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    CORPUS.mkdir(parents=True, exist_ok=True)
    rows = fetch_locale("cn")
    if sum(1 for r in rows if r["character"] == "anon") < 40:
        print("cn too thin, also fetch jp")
        rows.extend(fetch_locale("jp"))
    by: Dict[str, List[str]] = {"anon": [], "soyo": []}
    for row in rows:
        by[row["character"]].append(row["text"])
    for cid, texts in by.items():
        (CORPUS / f"{cid}.jsonl").write_text(
            "\n".join(json.dumps({"text": t}, ensure_ascii=False) for t in texts),
            encoding="utf-8",
        )
        model = distill(cid, texts)
        path = OUT / f"{cid}.yaml"
        path.write_text(
            yaml.safe_dump(model, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        print(
            f"wrote {path.name} lines={model['n_lines']} chat={model['n_chat']} "
            f"plain={len(model['plain'])} quirk={len(model['quirk'])}"
        )
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
