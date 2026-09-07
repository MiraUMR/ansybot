"""人类发言 → 环境旁白：分类、模板包装、轻量 LLM 改写。"""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

try:
    from kirara_ai.logger import get_logger

    logger = get_logger("WorldState.Narration")
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("WorldState.Narration")

NARRATION_SYSTEM = """你是群聊 RP 的场景书记。把群友的一句中文发言改写成第三人称环境旁白或环境音效，供角色感知世界用。
规则：
1. 不要出现真实群友昵称、QQ、@；不要写成「有人问你」。
2. 用「空气中 / 窗外 / 耳边 / 场地里」等非指向性主体。
3. 保留原意与情绪，1 句即可，可加轻描写，不要扩写成小剧场。
4. 开头必须是 [场景旁白] 或 [环境描写] 之一。
5. 只输出旁白正文，不要解释。
6. 原文若有 @、你/你们/您，必须改成无人称环境音，禁止保留第二人称，禁止写成有人在对角色说话。
示例：
输入：你今天晚上吃什么？
输出：[场景旁白] 空气中传来一句随意的询问，似乎有人在关心今晚的餐食安排。
输入：@张三 你看这个
输出：[环境描写] 场地里有人在跟旁边的人说话，声音并不针对谁。
输入：外面下雨了好大
输出：[环境描写] 窗外突然传来淅淅沥沥的雨声，雨势渐大。
"""

_AT_LEAD_RE = re.compile(r"^[@＠]\S+\s+")
_CQ_AT_RE = re.compile(r"\[CQ:at,[^\]]+\]", re.IGNORECASE)
_CQ_REPLY_RE = re.compile(r"\[CQ:reply,[^\]]+\]", re.IGNORECASE)
_AT_TOKEN_RE = re.compile(r"[@＠]\S+")
_BOT_MARK_RE = re.compile(r"(?i)@bot\b")
_YOU_RE = re.compile(r"(你|你们|您)")


def strip_addressing(text: str) -> str:
    """去掉 @、引用和明显的第二人称指向，避免旁白仍像在对角色说话。"""
    cleaned = (text or "").strip()
    cleaned = _CQ_AT_RE.sub(" ", cleaned)
    cleaned = _CQ_REPLY_RE.sub(" ", cleaned)
    cleaned = _BOT_MARK_RE.sub(" ", cleaned)
    cleaned = _AT_TOKEN_RE.sub(" ", cleaned)
    cleaned = _AT_LEAD_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


_EMOJI_RE = re.compile(
    r"^["
    r"\U0001F300-\U0001F9FF"
    r"\U00002600-\U000027BF"
    r"\U0001FA00-\U0001FAFF"
    r"\U0000200D"
    r"\U0000FE0F"
    r"\U00002194-\U00002199"
    r"❤♥♡♪★☆～~…。．·・！!？?（）()【】\[\]『』「」"
    r"]+$",
    re.UNICODE,
)
_KAOMOJI_RE = re.compile(
    r"^[\(（\[【]?[（(]?[><￣´`¯\^;；:：\-—_~～．.。\*＊\^\-∇△▽●○□■◇◆★☆´∀｀ωДT∇￣▽]+[)）\]】]?[)）]?$"
)


def _is_emoji_or_kaomoji_only(compact: str) -> bool:
    if not compact:
        return True
    if _EMOJI_RE.match(compact):
        return True
    # 去掉常见空白变体后再判颜文字
    if _KAOMOJI_RE.match(compact):
        return True
    # 全是标点/符号且无汉字数字字母
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", compact):
        return True
    return False


def classify_human_utterance(
    text: str,
    *,
    short_max: int = 4,
    llm_min: int = 12,
    discard_only_emoji: bool = True,
) -> str:
    """返回 discard | template | llm"""
    t = strip_addressing(text)
    if not t:
        return "discard"
    compact = re.sub(r"\s+", "", t)
    if len(compact) < short_max:
        return "discard"
    if discard_only_emoji and _is_emoji_or_kaomoji_only(compact):
        return "discard"
    if len(compact) < llm_min and not re.search(r"[？?！!…]", t):
        return "template"
    if len(compact) < llm_min:
        return "template"
    return "llm"


def wrap_template(raw: str) -> str:
    cleaned = strip_addressing(raw)
    if not cleaned:
        return "[环境描写] 周围有人在说话，声音并不针对谁。"
    if _YOU_RE.search(cleaned) or cleaned.endswith(("?", "？")):
        return "[环境描写] 空气中飘过一句并不针对谁的闲话。"
    return f"[环境描写] 空气里隐约有人说起「{cleaned}」这类话，并不是在叫谁。"


def rewrite_with_llm(
    raw: str,
    container: Any,
    model_name: str = "",
) -> Optional[str]:
    """调用轻量模型改写；失败返回 None。"""
    try:
        from kirara_ai.llm.format.message import LLMChatMessage, LLMChatTextContent
        from kirara_ai.llm.format.request import LLMChatRequest
        from kirara_ai.llm.llm_manager import LLMManager
    except Exception as exc:
        logger.debug(f"narration llm import failed: {exc}")
        return None

    cleaned = strip_addressing(raw)
    if not cleaned:
        return None

    try:
        manager: LLMManager = container.resolve(LLMManager)
    except Exception as exc:
        logger.warning(f"narration resolve LLMManager failed: {exc}")
        return None

    candidates = []
    if model_name and str(model_name).strip():
        candidates.append(str(model_name).strip())
    try:
        from kirara_ai.config.global_config import GlobalConfig

        cfg = container.resolve(GlobalConfig)
        default = str(getattr(getattr(cfg, "defaults", None), "llm_model", "") or "").strip()
        if default and default not in candidates:
            candidates.append(default)
        for ref in (getattr(getattr(getattr(cfg, "llms", None), "priority", None), "text", None) or []):
            r = str(ref or "").strip()
            if r and r not in candidates:
                candidates.append(r)
    except Exception:
        pass

    prompt = [
        LLMChatMessage(
            role="system",
            content=[LLMChatTextContent(text=NARRATION_SYSTEM)],
        ),
        LLMChatMessage(
            role="user",
            content=[LLMChatTextContent(text=f"输入：{cleaned}")],
        ),
    ]

    last_err = None
    for mid in candidates[:4]:
        llm = manager.get_llm(mid)
        if not llm:
            continue
        try:
            resp = llm.chat(LLMChatRequest(messages=prompt, model=mid, max_tokens=120, temperature=0.4))
            try:
                from .token_meter import format_simple_call

                logger.info(
                    format_simple_call(
                        purpose="narration",
                        model=mid,
                        system=NARRATION_SYSTEM,
                        user=f"输入：{cleaned}",
                        resp=resp,
                    )
                )
            except Exception:
                pass
            text = ""
            msg = getattr(resp, "message", None)
            for part in getattr(msg, "content", None) or []:
                text += getattr(part, "text", None) or ""
            text = (text or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:\w+)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text).strip()
            if not text:
                continue
            if not (text.startswith("[场景旁白]") or text.startswith("[环境描写]") or text.startswith("[环境音]")):
                text = f"[场景旁白] {text}"
            return text
        except Exception as exc:
            last_err = exc
            logger.warning(f"narration rewrite failed model={mid}: {exc}")
            continue
    if last_err:
        logger.warning(f"narration rewrite all failed last={last_err}")
    return None


def to_narration(
    raw: str,
    container: Any = None,
    *,
    short_max: int = 4,
    llm_min: int = 12,
    discard_only_emoji: bool = True,
    narration_model: str = "",
) -> Tuple[str, str]:
    """
    返回 (kind, narration)
    kind: discard | template | llm
    discard 时 narration 为空。
    """
    kind = classify_human_utterance(
        raw,
        short_max=short_max,
        llm_min=llm_min,
        discard_only_emoji=discard_only_emoji,
    )
    if kind == "discard":
        return "discard", ""
    if kind == "template":
        return "template", wrap_template(raw)
    # llm
    rewritten = None
    if container is not None:
        rewritten = rewrite_with_llm(raw, container, model_name=narration_model)
    if rewritten:
        return "llm", rewritten
    return "template", wrap_template(raw)
