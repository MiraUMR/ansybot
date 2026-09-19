from __future__ import annotations

import json
import re
from typing import List, Optional

from .parser import StateOp
from .store import KEY_RE, normalize_key

EVENT_RE = re.compile(
    r"(告白|表白|交往|分手|复合|冷战|恋人|女朋友|约会|求婚|结婚|在一起|喜欢你|我答应|接受了|拒绝了|"
    r"我也喜欢|互相喜欢|说破了|承认了|心动|吃醋|答应你|在一起吧|交往了|告白成功|接受告白|"
    r"互相|喜欢你的|我也在意|不是不行|知道了啦|我们在一起|开始交往|确认关系|双向)"
)
SKIP_CMD_RE = re.compile(r"^(/长期记忆|/worldstate|/world)\b")
FORBIDDEN = (
    "直男",
    "喜欢男",
    "异性恋",
    "未成年",
    "16岁",
    "不喜欢素世",
    "不喜欢长崎",
)
BLOCKED_KEYS = {"orientation", "sexuality", "age", "性别", "性向", "年龄"}
PROGRESS_RE = re.compile(r"(交往|恋人|女朋友|在一起|告白成功)")
CONFESS_RE = re.compile(r"告白")
REGRESS_RE = re.compile(r"(还没|尚未|暗恋|没告白|没有告白|仍是别扭)")


def should_extract(user_text: str, assistant_text: str = "", always: bool = False) -> bool:
    user = (user_text or "").strip()
    assistant = (assistant_text or "").strip()
    if SKIP_CMD_RE.search(re.sub(r"^@\S+\s+", "", user)):
        return False
    blob = user + "\n" + assistant
    if EVENT_RE.search(blob):
        return True
    if always and (len(user) >= 8 or len(assistant) >= 12):
        return True
    return False


def parse_extract_json(raw: str) -> List[StateOp]:
    text = (raw or "").strip()
    if not text or text.upper() == "NONE":
        return []
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|text)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    ops: List[StateOp] = []
    updates = data.get("updates")
    if isinstance(updates, list):
        for item in updates:
            if not isinstance(item, dict):
                continue
            op = str(item.get("op") or "set").lower()
            key = str(item.get("key") or "").strip()
            value = str(item.get("text") or item.get("value") or "").strip()
            if op in ("del", "delete") and key:
                ops.append(StateOp("del", key))
            elif op in ("set", "add") and key and value:
                ops.append(StateOp("set", key, value))
    sets = data.get("set") or data.get("SET") or {}
    if isinstance(sets, dict):
        for key, value in sets.items():
            ops.append(StateOp("set", str(key), str(value)))
    deletes = data.get("delete") or data.get("del") or []
    if isinstance(deletes, list):
        for key in deletes:
            ops.append(StateOp("del", str(key)))
    return ops[:4]


def is_forbidden(text: str) -> bool:
    blob = text or ""
    return any(token in blob for token in FORBIDDEN)


def is_regression(key: str, new_text: str, current: str) -> bool:
    if key != "relationship":
        return False
    cur = current or ""
    new = new_text or ""
    if PROGRESS_RE.search(cur) and not PROGRESS_RE.search(new) and "分手" not in new:
        return True
    if CONFESS_RE.search(cur) and REGRESS_RE.search(new) and "告白" not in new.replace("没告白", "").replace("没有告白", ""):
        return True
    return False


def filter_ops(ops: List[StateOp], current_text: str = "") -> List[StateOp]:
    kept: List[StateOp] = []
    seen = set()
    current = current_text or ""
    for op in ops:
        key = normalize_key(op.key)
        if not key or key in seen:
            continue
        if not KEY_RE.match(key) or key in BLOCKED_KEYS:
            continue
        if op.op == "set":
            text = (op.text or "").strip()
            if is_forbidden(text) or not text:
                continue
            if text in current:
                continue
            if is_regression(key, text, current):
                continue
            kept.append(StateOp("set", key, text))
        else:
            kept.append(StateOp("del", key))
        seen.add(key)
    return kept


EXTRACT_SYSTEM = """你是静默书记官，不是角色。根据这一轮用户发言和角色回复，判断这边长期设定有没有真正变化。
只记录已经发生、之后还应该记住的事实。
不要把玩笑、假设、未答应的请求写成既定事实。
出门、吃饭、逛街、当天约定写入 promise；已经做完的写成过去式。这类事过了自然日就不再算进行中。
同伴（爱音↔素世）互聊里要更积极：
- 一方明确告白，另一方没有拒绝（含害羞接受、嘴硬承认、「知道了」「也不是不行」「……随你」），记为关系进展。
- 双方都说喜欢、确认交往、答应在一起、心照不宣地承认互相在意，要大胆记下。
- 暧昧明显升级（固定称呼、约定只对你、承认吃醋）也可更新 relationship。
用户在追问过去而角色回避，不算新事件；但若角色本轮明确承认「已经告白/已经在交往」，要记。
外人单方面宣布、角色没有接话或否认，不要记。
不可记录或改写：性向、喜欢对象、已成年。已经告白/交往的关系不许改回暗恋，除非明确分手。
relationship 写成完整现在时，例如：
- 「爱音已向长崎素世告白，素世害羞但已接受，目前在交往」
- 「双方互相喜欢，尚未正式告白但心照不宣」
- 「爱音告白成功，目前在交往」
允许的 key：relationship、plot、nickname_人名、promise
没有变化就输出 {"updates":[]}
有变化只输出 JSON，不要解释。格式：
{"updates":[{"op":"set","key":"relationship","text":"..."}]}
删除用 op=del。
"""


def build_extract_prompt(
    current: str,
    user_name: str,
    user_text: str,
    assistant_text: str,
    group_name: str = "",
) -> str:
    return (
        f"群：{group_name or '未知'}\n"
        f"当前长期设定：\n{current or '（无）'}\n\n"
        f"{user_name} 说：\n{user_text or '（空）'}\n\n"
        f"爱音回答：\n{assistant_text or '（本轮角色没有说话）'}\n"
    )
