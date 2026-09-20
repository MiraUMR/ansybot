"""Prompt / API token metering for logs, so prompt sections can be split later.

Logs look like「人设.base 消耗了 1820 token」, not a bare number dump.
Estimates use tiktoken cl100k_base when installed; otherwise a CJK heuristic.
API usage on the response is the billed source of truth.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_ENC = None
_ENC_FAILED = False
TOKENIZER_NAME = "heuristic-cjk"

_CJK_RE = re.compile(
    r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3040-\u30FF\uAC00-\uD7AF]"
)

SYSTEM_MARKERS: List[Tuple[str, str]] = [
    ("人设.P0", r"\[P0:"),
    ("人设.CRITICAL", r"\[CRITICAL"),
    ("人设.role", r"<role\b"),
    ("人设.lock", r"<lock>"),
    ("人设.at_mode", r"<at_mode>"),
    ("人设.companion", r"<companion_mode"),
    ("人设.scene", r"<scene_mode>"),
    ("人设.outsider", r"<outsider>"),
    ("人设.trigger.md", r"(?m)^## 被@时的响应范式"),
    ("人设.companion.md", r"(?m)^## 普通群聊（无标签"),
    ("本群长期关系", r"(?m)^# 本群长期关系"),
    ("当下", r"(?m)^# 当下"),
    ("当前信息", r"(?m)^# 当前信息"),
    ("近期聊天", r"(?m)^# 近期聊天"),
    ("回复规则", r"(?m)^记住："),
]

USER_MARKERS: List[Tuple[str, str]] = [
    ("本轮.P0", r"\[P0:"),
    ("本轮.CRITICAL", r"\[CRITICAL"),
    ("本轮.STORY", r"\[SYSTEM: STORY MODE\]"),
    ("本轮.STORY_END", r"\[SYSTEM: STORY_END\]"),
    ("本轮.TRIGGER", r"\[SYSTEM: EXTERNAL_TRIGGER\]"),
    ("本轮.话题锁", r"【本轮话题锁】"),
    ("本轮.识图", r"已识别图片内容"),
    ("本轮.环境", r"【当前环境】"),
    ("本轮.系统", r"【系统】"),
]


def _encoding():
    global _ENC, _ENC_FAILED, TOKENIZER_NAME
    if _ENC is not None or _ENC_FAILED:
        return _ENC
    try:
        import tiktoken

        _ENC = tiktoken.get_encoding("cl100k_base")
        TOKENIZER_NAME = "cl100k_base"
        return _ENC
    except Exception:
        _ENC_FAILED = True
        TOKENIZER_NAME = "heuristic-cjk"
        return None


def estimate_tokens(text: str) -> int:
    raw = text or ""
    if not raw:
        return 0
    enc = _encoding()
    if enc is not None:
        try:
            return len(enc.encode(raw))
        except Exception:
            pass
    n_cjk = len(_CJK_RE.findall(raw))
    n_other = max(0, len(raw) - n_cjk)
    return max(1, int(round(n_cjk * 0.85 + n_other / 4.0)))


def format_consumed(
    name: str,
    tokens: int,
    *,
    chars: Optional[int] = None,
    pct: Optional[float] = None,
    extra: str = "",
) -> str:
    bits = [f"{name} 消耗了 {int(tokens)} token"]
    if chars is not None:
        bits.append(f"{int(chars)}字")
    if pct is not None:
        bits.append(f"{pct:.0f}%")
    if extra:
        bits.append(extra)
    if len(bits) == 1:
        return bits[0]
    return f"{bits[0]}（{'，'.join(bits[1:])}）"


def usage_dict(resp_or_usage: Any) -> Dict[str, int]:
    usage = resp_or_usage
    if usage is not None and not isinstance(usage, dict) and hasattr(usage, "usage"):
        usage = getattr(usage, "usage", None)
    if not usage:
        return {}
    if isinstance(usage, dict):
        src = usage
    else:
        src = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
    out = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
        try:
            out[key] = int(src.get(key, 0) or 0) if isinstance(src, dict) else int(getattr(src, key, 0) or 0)
        except Exception:
            out[key] = 0
    details = None
    if isinstance(src, dict):
        details = src.get("prompt_tokens_details")
    else:
        details = getattr(src, "prompt_tokens_details", None)
    if isinstance(details, dict) and not out.get("cached_tokens"):
        try:
            out["cached_tokens"] = int(details.get("cached_tokens") or 0)
        except Exception:
            pass
    return out


def format_api_usage(resp_or_usage: Any, *, model: str = "") -> str:
    data = usage_dict(resp_or_usage)
    if not data or not any(data.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
        prefix = f"API model={model} " if model else "API "
        return prefix + "未返回 usage"
    parts = [
        format_consumed("prompt", data.get("prompt_tokens") or 0),
        format_consumed("completion", data.get("completion_tokens") or 0),
        f"合计 {int(data.get('total_tokens') or 0)} token",
    ]
    cached = int(data.get("cached_tokens") or 0)
    if cached:
        parts.append(format_consumed("cached", cached))
    prefix = f"API model={model} " if model else "API "
    return prefix + "，".join(parts)


def split_by_markers(text: str, markers: Sequence[Tuple[str, str]], default_name: str) -> List[Tuple[str, str]]:
    raw = text or ""
    if not raw.strip():
        return []
    hits: List[Tuple[int, str]] = []
    for name, pat in markers:
        match = re.search(pat, raw)
        if match:
            hits.append((match.start(), name))
    hits.sort(key=lambda item: item[0])
    deduped: List[Tuple[int, str]] = []
    seen_pos = set()
    for start, name in hits:
        if start in seen_pos:
            continue
        seen_pos.add(start)
        deduped.append((start, name))
    hits = deduped
    pieces: List[Tuple[str, str]] = []
    if not hits:
        return [(default_name, raw)]
    if hits[0][0] > 0:
        head = raw[: hits[0][0]]
        if head.strip():
            pieces.append((default_name, head))
    for i, (start, name) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(raw)
        chunk = raw[start:end]
        if not chunk.strip():
            continue
        if name == "近期聊天":
            pieces.extend(_split_recent_chat(chunk))
        else:
            pieces.append((name, chunk))
    return pieces


def _split_recent_chat(chunk: str) -> List[Tuple[str, str]]:
    begin = "-- 对话记录开始 --"
    end = "-- 对话记录结束 --"
    i = chunk.find(begin)
    j = chunk.find(end)
    if i < 0 or j < 0 or j <= i:
        return [("近期聊天", chunk)]
    head = chunk[: i + len(begin)]
    body = chunk[i + len(begin) : j]
    tail = chunk[j:]
    out: List[Tuple[str, str]] = []
    skeleton = head + tail
    if skeleton.strip():
        out.append(("近期聊天.骨架", skeleton))
    if body.strip():
        out.append(("近期聊天.内容", body))
    elif not out:
        out.append(("近期聊天", chunk))
    return out


def split_system_prompt(text: str) -> List[Tuple[str, str]]:
    return split_by_markers(text, SYSTEM_MARKERS, "人设.base")


def split_user_prompt(text: str) -> List[Tuple[str, str]]:
    return split_by_markers(text, USER_MARKERS, "本轮.user")


def infer_character(system: str) -> str:
    blob = system or ""
    if "千早爱音" in blob and "长崎素世" not in blob[:200]:
        if "你是千早爱音" in blob or "你就是千早爱音" in blob:
            return "anon"
    if "你是长崎素世" in blob or "你就是长崎素世" in blob:
        return "soyo"
    if "你就是千早爱音本人" in blob:
        return "anon"
    if "你就是长崎素世本人" in blob:
        return "soyo"
    return ""


def _message_text(msg: Any) -> Tuple[str, int]:
    texts: List[str] = []
    images = 0
    for part in getattr(msg, "content", None) or []:
        text = getattr(part, "text", None)
        if text:
            texts.append(str(text))
        media_id = getattr(part, "media_id", None)
        ptype = getattr(part, "type", None) or part.__class__.__name__
        if media_id or "image" in str(ptype).lower():
            images += 1
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("text"):
                        texts.append(str(part.get("text")))
                    if part.get("type") == "image" or part.get("image_url") or part.get("media_id"):
                        images += 1
                elif isinstance(part, str):
                    texts.append(part)
    return "\n".join(texts), images


def _pct(part: int, total: int) -> Optional[float]:
    if total <= 0:
        return None
    return 100.0 * part / total


def format_named_parts(
    parts: Iterable[Tuple[str, str]],
    *,
    total: Optional[int] = None,
    show_pct: bool = True,
) -> List[str]:
    items = [(name, body) for name, body in parts if (body or "").strip()]
    counted = [(name, estimate_tokens(body), len(body), body) for name, body in items]
    denom = total if total is not None else sum(tok for _, tok, _, _ in counted)
    lines = []
    for name, tok, chars, _body in counted:
        if tok <= 0 and chars <= 0:
            continue
        lines.append(
            format_consumed(
                name,
                tok,
                chars=chars,
                pct=_pct(tok, denom) if show_pct else None,
            )
        )
    return lines


def format_module_injection(character: str, mode: str, modules: Sequence[Tuple[str, str]]) -> str:
    lines = format_named_parts(modules)
    total = sum(estimate_tokens(body) for _name, body in modules)
    chars = sum(len(body or "") for _name, body in modules)
    header = (
        f"persona_layers {character} mode={mode or '-'} "
        f"本轮注入合计 消耗了 {total} token（{chars}字） tokenizer={TOKENIZER_NAME}"
    )
    if not lines:
        return header
    return header + "\n  " + "\n  ".join(lines)


def format_static_modules(entries: Sequence[Tuple[str, str]]) -> str:
    lines = format_named_parts(entries, show_pct=False)
    header = f"persona 模块预估 tokenizer={TOKENIZER_NAME}"
    if not lines:
        return header + " （空）"
    return header + "\n  " + "\n  ".join(lines)


def _bucket_name(name: str) -> str:
    label = name or ""
    if label.startswith("近期聊天") or label.startswith("历史."):
        return "历史"
    if label.startswith("本轮."):
        return "本轮"
    if label.startswith("人设.") or label in ("本群长期关系", "当下", "当前信息", "回复规则"):
        return "人设"
    return "其他"


def format_bucket_summary(parts: Sequence[Tuple[str, str]], total: int = 0) -> str:
    buckets = {"人设": 0, "历史": 0, "本轮": 0, "其他": 0}
    for name, body in parts:
        buckets[_bucket_name(name)] += estimate_tokens(body)
    denom = total or sum(buckets.values()) or 1
    bits = []
    for key in ("人设", "历史", "本轮", "其他"):
        tok = buckets[key]
        if key == "其他" and tok <= 0:
            continue
        pct = 100.0 * tok / denom
        bits.append(f"{key}={tok}({pct:.0f}%)")
    return "token 摘要 " + " ".join(bits)


def format_chat_token_report(
    messages: Sequence[Any],
    *,
    model: str = "",
    mode: str = "",
    resp: Any = None,
    purpose: str = "chat",
) -> str:
    msgs = list(messages or [])
    system_text = ""
    history_bits: List[Tuple[str, str]] = []
    current_user = ""
    images = 0
    last_user_idx = -1
    for i, msg in enumerate(msgs):
        role = str(getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else "") or "")
        text, n_img = _message_text(msg)
        images += n_img
        if role == "system" and not system_text:
            system_text = text
        elif role == "user":
            last_user_idx = i
    for i, msg in enumerate(msgs):
        role = str(getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else "") or "")
        text, n_img = _message_text(msg)
        if role == "system":
            continue
        if i == last_user_idx and role == "user":
            current_user = text
            continue
        if not (text or "").strip() and not n_img:
            continue
        extra = f"{n_img}张图" if n_img else ""
        label = f"历史.{role}"
        history_bits.append((label, text if text else extra))

    character = infer_character(system_text)
    named: List[Tuple[str, str]] = []
    named.extend(split_system_prompt(system_text))
    # collapse consecutive 历史.user / 历史.assistant into counted groups later
    hist_groups: Dict[str, List[str]] = {}
    hist_counts: Dict[str, int] = {}
    for label, body in history_bits:
        hist_groups.setdefault(label, []).append(body)
        hist_counts[label] = hist_counts.get(label, 0) + 1
    for label, bodies in hist_groups.items():
        n = hist_counts.get(label, len(bodies))
        named.append((f"{label}×{n}", "\n".join(bodies)))
    named.extend(split_user_prompt(current_user) if current_user.strip() else [])

    est_total = sum(estimate_tokens(body) for _n, body in named)
    lines = format_named_parts(named, total=est_total or None)
    api_line = format_api_usage(resp, model=model)
    ident = " ".join(
        x for x in (
            f"purpose={purpose}",
            f"character={character}" if character else "",
            f"mode={mode}" if mode else "",
            f"model={model}" if model else "",
        ) if x
    )
    header = (
        f"token 拆分 {ident} tokenizer={TOKENIZER_NAME} "
        f"估算合计 消耗了 {est_total} token"
    )
    if images:
        header += f" 另有 image×{images}（视觉 token 以上游 API 为准）"
    chunks = [header, api_line]
    if lines:
        chunks.append("  " + format_bucket_summary(named, est_total))
        chunks.append("  " + "\n  ".join(lines))
    return "\n".join(chunks)


def format_simple_call(
    *,
    purpose: str,
    model: str = "",
    system: str = "",
    user: str = "",
    resp: Any = None,
) -> str:
    parts = []
    if system:
        parts.append(("system", system))
    if user:
        parts.append(("user", user))
    est = sum(estimate_tokens(body) for _n, body in parts)
    lines = format_named_parts(parts, total=est or None)
    header = (
        f"token 拆分 purpose={purpose} model={model or '-'} "
        f"tokenizer={TOKENIZER_NAME} 估算合计 消耗了 {est} token"
    )
    return "\n".join([header, format_api_usage(resp, model=model), "  " + "\n  ".join(lines) if lines else ""]).rstrip()
