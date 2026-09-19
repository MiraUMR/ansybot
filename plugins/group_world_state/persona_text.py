"""人设正文与工作流套层分离。

作者在「角色人设」里只写角色；互斥、层级、防降级由工作流在注入时套上。
文件里若误贴了 Kirara / [P0] 声明，读写时会剥掉，避免和工作流抢优先级。

同伴身份写在 base 模块的 ```peer 代码块里，由系统解析后用于 QQ 分流。
"""
from __future__ import annotations

import re
from typing import Dict

import yaml

_KIRARA_TITLE = re.compile(
    r"^#\s*⚠(?:️)?\s*Kirara AI工作流兼容声明\s*$",
    re.M,
)
_KIRARA_QUOTE = re.compile(
    r"^>\s*⚠(?:️)?\s*Kirara工作流适配声明：[^\n]*\n?",
    re.M,
)
_TAIL_SECTIONS = re.compile(
    r"\n*## (?:防降级锚点|边界限定)\n[\s\S]*$",
)
_PEER_FENCE = re.compile(
    r"```peer\s*\n([\s\S]*?)\n```",
    re.I,
)

_DOWNGRADE_STOP = (
    "【工作流 · 防降级】若感到「应该先回答再表演」「应该接住对方的话」"
    "「应该给出准确信息」，立刻停。那是 Base/Companion 残留。"
    "禁止问答体，按本模块从第一条重新生成。"
)

_PEER_KEYS = (
    "self_id",
    "self_display",
    "self_qq",
    "peer_id",
    "peer_display",
    "peer_qq",
    "peer_call",
    "peer_absent",
    "peer_forbid",
)


def strip_workflow_chrome(text: str) -> str:
    """去掉误写进人设文件的工作流声明，只留角色正文。"""
    t = (text or "").replace("\r\n", "\n").lstrip("\n")
    if _KIRARA_TITLE.search(t[:80] if len(t) > 80 else t) or t.startswith(
        "# ⚠️ Kirara AI工作流兼容声明"
    ):
        idx = t.find("\n\n")
        t = t[idx + 2 :] if idx >= 0 else ""
    t = _KIRARA_QUOTE.sub("", t)
    t = _TAIL_SECTIONS.sub("\n", t)
    t = t.strip()
    return (t + "\n") if t else ""


def parse_peer_binding(text: str) -> Dict[str, str]:
    """从人设正文解析同伴绑定；优先 PERSONA_PACK.peer，其次 ```peer 块。"""
    out = {k: "" for k in _PEER_KEYS}
    raw = text or ""
    try:
        from .persona_pack import parse_persona_pack, peer_dict_from_pack

        pack = parse_persona_pack(raw, "base")
        peer = peer_dict_from_pack(pack)
        if any(peer.values()):
            return peer
    except Exception:
        pass
    m = _PEER_FENCE.search(raw)
    if not m:
        return out
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return out
    if not isinstance(data, dict):
        return out
    for key in _PEER_KEYS:
        val = data.get(key)
        if val is None:
            continue
        out[key] = str(val).strip()
    return out


def peer_binding_summary(binding: Dict[str, str]) -> str:
    """给人设 / 提示用的短摘要。账号只在代码里匹配，不写进提示。"""
    display = binding.get("peer_display") or binding.get("peer_id") or "同伴"
    call = binding.get("peer_call") or display
    return (
        f"同伴当面称「{call}」（{display}）。"
        "仅系统判定的同伴走互聊；其他人一律当眼前的人。"
    )


def envelop_module(module: str, body: str, mode: str = "") -> str:
    """按本轮 message_mode 套工作流层级。空正文不注入。"""
    body = (body or "").strip()
    if not body:
        return ""
    module = (module or "").strip()
    mode = (mode or "").strip()

    if module == "base":
        prefix = _base_prefix(mode)
        return f"{prefix}{body}" if prefix else body

    if module == "trigger":
        return (
            "【工作流 P2 · 被@】本轮唯一条件模块。"
            "系统提示末尾 [P0] 覆盖 Base 接话与 Companion。\n\n"
            f"{body}\n\n{_DOWNGRADE_STOP}"
        )

    if module == "companion":
        return (
            "【工作流 P3 · 同伴互聊】仅 Bot 互聊（message_mode=peer）时注入。"
            "本轮若是 @ 或故事，工作流不会加载本段；"
            "不得用「接话/互动强化」覆盖 Trigger/Story。"
            "同伴身份以 Base 的【同伴绑定】为准。\n\n"
            f"{body}"
        )

    if module == "story":
        return (
            "【工作流 P1 · 故事】本轮唯一条件模块。"
            "系统提示末尾 [P0] 覆盖日常接话与 Companion 收束。\n\n"
            f"{body}\n\n{_DOWNGRADE_STOP}"
        )

    if module == "scene":
        return (
            "【工作流 · 环境场面】仅环境音/场面轮注入。"
            "被 @ 时不加载本段（场面仍可能从别处进入提示）。不是有人在问你。\n\n"
            f"{body}"
        )

    if module == "mode_phone":
        return (
            "【工作流 · PHONE MODE】优先级高于 Base speech。"
            "ABSOLUTE FORBID：禁止任何 ()【】（）动作/神态（覆盖 Base 的 F2F 稀疏许可）。"
            "用 <break> 碎句、emoji、[图片]/[语音] 占位符表达在线状态。\n\n"
            f"{body}"
        )

    return body


def _base_prefix(mode: str) -> str:
    if mode in ("direct", "story"):
        return (
            "【工作流】本轮已注入更高层模块。"
            "下面身份、称呼、性格仍有效；"
            "「说话方式」里的接话/有来有回/先回应对方：本轮全部作废，不得当成问答体依据。"
            "禁止客服讲解腔，禁止把眼前的人当考题作答。\n\n"
        )
    if mode == "peer":
        return (
            "【工作流】本轮是同伴互聊。"
            "下面身份、称呼、性格仍有效；日常「有来有回」让位给 Companion 的收束规则。"
            "同伴 QQ/称呼以【同伴绑定】为准。\n\n"
        )
    if mode in ("env", "scene"):
        return (
            "【工作流】本轮是环境/场面，不是有人在问你。"
            "下面身份仍有效；「接话/有来有回」让位。\n\n"
        )
    return ""
