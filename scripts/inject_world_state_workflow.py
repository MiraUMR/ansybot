"""Idempotent: add long-term world-state nodes without replacing the character prompt."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data" / "workflows" / "chat" / "normal.yaml"

PROMPT_SECTION = """
        # 本群长期关系（会随剧情更新，仅对本群有效）
        下面覆盖「现在进行到哪一步」。如果写了已经告白或正在交往，就按告白后相处，不要再演单箭头。
        不可推翻的三条（性向、喜欢素世、已成年）仍然最高优先级；关系阶段以本段为准。
        {world_state}
"""

STATE_FOOTER = """
        # 长期设定更新（用户看不见）
        只有当本群默认关系或长期设定真正改变时（告白被接受、开始交往、分手、公开恋情、约定固定称呼等），在回复最末尾追加，不要解释、不要念出来。没有变化就整段不要写，也不要照抄下面的格式说明。
        格式：
        <<STATE
        SET relationship 一句话写清当前关系阶段
        >>
        SET 覆盖同名条目，DEL key 删除条目。key 用英文小写加下划线，例如 relationship。
"""

RULE2_OLD = "这是单箭头也要咬着不放的真心"
RULE2_NEW = (
    "这是真心，不是玩笑。关系进行到哪一步（暗恋 / 已告白 / 交往 / 冷战）"
    "以「本群长期关系」为准；没有长期关系记录时，默认还没告白成功，按别扭暗恋相处。"
)

NEW_BLOCKS = [
    {
        "type": "world_state:query",
        "name": "query_world_state",
        "params": {},
        "position": {"x": 530, "y": 530},
        "connected_to": [
            {
                "target": "inject_world_state",
                "mapping": {"from": "text", "to": "new_text"},
            }
        ],
    },
    {
        "type": "internal:text_replace_block",
        "name": "inject_world_state",
        "params": {"variable": "{world_state}"},
        "position": {"x": 740, "y": 330},
        "connected_to": [
            {
                "target": "ChatMessageConstructor_kcjgyy",
                "mapping": {"from": "text", "to": "system_prompt_format"},
            }
        ],
    },
    {
        "type": "world_state:apply",
        "name": "apply_world_state",
        "params": {},
        "position": {"x": 1480, "y": 138},
        "connected_to": [
            {
                "target": "ChatResponseConverter_23c2qz",
                "mapping": {"from": "llm_resp", "to": "resp"},
            },
            {
                "target": "ChatMemoryStore_bfgmao",
                "mapping": {"from": "llm_resp", "to": "llm_resp"},
            },
        ],
    },
]


def _block(data: dict, name: str) -> dict:
    for item in data["blocks"]:
        if item.get("name") == name:
            return item
    raise KeyError(name)


def _has(data: dict, name: str) -> bool:
    return any(item.get("name") == name for item in data["blocks"])


def _ensure_wire(node: dict, target: str, src: str, dst: str) -> None:
    wires = node.setdefault("connected_to", [])
    for wire in wires:
        if (
            wire.get("target") == target
            and (wire.get("mapping") or {}).get("from") == src
            and (wire.get("mapping") or {}).get("to") == dst
        ):
            return
    wires.append({"target": target, "mapping": {"from": src, "to": dst}})


def _drop_wire(node: dict, target: str, dst: str | None = None) -> None:
    wires = node.get("connected_to") or []
    kept = []
    for wire in wires:
        if wire.get("target") != target:
            kept.append(wire)
            continue
        if dst and (wire.get("mapping") or {}).get("to") != dst:
            kept.append(wire)
            continue
    node["connected_to"] = kept


def patch_prompt(text: str) -> str:
    if "{world_state}" not in text:
        marker = "        # 当前信息"
        section = PROMPT_SECTION.rstrip() + "\n\n"
        if marker in text:
            text = text.replace(marker, section + marker, 1)
            print("inserted world_state prompt section")
        else:
            print("WARN: current-info marker not found, appending world_state section")
            text = text.rstrip() + "\n" + section
    else:
        print("prompt already has {world_state}")
    if "<<STATE" not in text:
        text = text.rstrip() + "\n" + STATE_FOOTER
        print("appended STATE footer")
    else:
        print("prompt already has STATE footer")
    if RULE2_OLD in text:
        text = text.replace(RULE2_OLD, RULE2_NEW, 1)
        print("softened 单箭头 rule")
    return text


def patch_workflow(data: dict) -> dict:
    data = deepcopy(data)
    existing = {item["name"] for item in data["blocks"]}
    for block in NEW_BLOCKS:
        if block["name"] not in existing:
            data["blocks"].append(deepcopy(block))
            print(f"added block {block['name']}")
        else:
            print(f"block {block['name']} already exists")

    get_message = _block(data, "get_message")
    _ensure_wire(get_message, "query_world_state", "sender", "chat_sender")
    _ensure_wire(get_message, "apply_world_state", "sender", "chat_sender")

    system_prompt = _block(data, "system_prompt")
    _drop_wire(system_prompt, "ChatMessageConstructor_kcjgyy", "system_prompt_format")
    _ensure_wire(system_prompt, "inject_world_state", "text", "text")
    system_prompt["params"]["text"] = patch_prompt(system_prompt["params"]["text"])

    llm_chat = _block(data, "llm_chat")
    _drop_wire(llm_chat, "ChatResponseConverter_23c2qz")
    _drop_wire(llm_chat, "ChatMemoryStore_bfgmao", "llm_resp")
    _ensure_wire(llm_chat, "apply_world_state", "resp", "llm_resp")

    apply_block = _block(data, "apply_world_state")
    _ensure_wire(apply_block, "ChatResponseConverter_23c2qz", "llm_resp", "resp")
    _ensure_wire(apply_block, "ChatMemoryStore_bfgmao", "llm_resp", "llm_resp")
    return data


def main() -> None:
    path = WORKFLOW
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    patched = patch_workflow(data)
    path.write_text(
        yaml.safe_dump(patched, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
