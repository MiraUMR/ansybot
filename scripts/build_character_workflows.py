"""Build chat:anon / chat:soyo from chat:normal and apply persona files.

Usage:
  python scripts/build_character_workflows.py
  python scripts/apply_persona_split.py --character anon
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PERSONA_ROOT = ROOT / "data" / "persona"
WORKFLOW_DIR = ROOT / "data" / "workflows" / "chat"
NORMAL = WORKFLOW_DIR / "normal.yaml"

USER_PROMPT = "本轮用户发言"
CORE = "核心人设（身份性格与不可推翻）"
WORLD_INTRO = "本群长期关系导语"
LORE = "补充设定（素世·乐队·群友）"
RUNTIME = "当场上下文（群名·时间·近期聊天）"
UPDATE = "回复规则（分段符与记忆标记）"
CONCAT_WORLD = "拼接本群关系事实"
CONCAT_CORE_WORLD = "拼接人设与本群关系"
CONCAT_LORE = "拼接补充设定"
CONCAT_RUNTIME = "拼接当场上下文"
CONCAT_FINAL = "拼成完整系统提示词"

NAME_MAP = {
    "user_prompt": USER_PROMPT,
    "persona_core": CORE,
    "persona_world_intro": WORLD_INTRO,
    "persona_lore": LORE,
    "persona_runtime": RUNTIME,
    "persona_update": UPDATE,
    "concat_world": CONCAT_WORLD,
    "concat_core_world": CONCAT_CORE_WORLD,
    "concat_lore": CONCAT_LORE,
    "concat_runtime": CONCAT_RUNTIME,
    "concat_final": CONCAT_FINAL,
}

SECTIONS = [
    (CORE, "01_core.txt", 80, 300),
    (WORLD_INTRO, "02_world_intro.txt", 80, 520),
    (LORE, "03_lore.txt", 80, 700),
    (RUNTIME, "04_runtime.txt", 80, 920),
    (UPDATE, "05_update.txt", 80, 1100),
]

CONCATS = [
    (CONCAT_WORLD, 420, 520, WORLD_INTRO, "text", "query_world_state", "text"),
    (CONCAT_CORE_WORLD, 680, 300, CORE, "text", CONCAT_WORLD, "text"),
    (CONCAT_LORE, 940, 300, CONCAT_CORE_WORLD, "text", LORE, "text"),
    (CONCAT_RUNTIME, 1200, 300, CONCAT_LORE, "text", RUNTIME, "text"),
    (CONCAT_FINAL, 1460, 300, CONCAT_RUNTIME, "text", UPDATE, "text"),
]

# 分层注入：核心人设与补充设定改由 world_state:persona_layers 按需拼接，
# 不再把 01_core.txt / 03_lore.txt 全量烤进工作流。
PERSONA_LAYERS = "persona_layers"
LAYERED_CHARACTERS = {"soyo", "anon"}
LAYERED_SECTIONS = {"01_core.txt", "03_lore.txt"}
LAYERED_CONCATS = [
    (CONCAT_WORLD, 420, 520, WORLD_INTRO, "text", "query_world_state", "text"),
    (CONCAT_CORE_WORLD, 680, 300, PERSONA_LAYERS, "text", CONCAT_WORLD, "text"),
    (CONCAT_RUNTIME, 1200, 300, CONCAT_CORE_WORLD, "text", RUNTIME, "text"),
    (CONCAT_FINAL, 1460, 300, CONCAT_RUNTIME, "text", UPDATE, "text"),
]


def _sections_for(character: str):
    if character in LAYERED_CHARACTERS:
        return [s for s in SECTIONS if s[1] not in LAYERED_SECTIONS]
    return SECTIONS


def _concats_for(character: str):
    return LAYERED_CONCATS if character in LAYERED_CHARACTERS else CONCATS

DROP = {"system_prompt", "inject_world_state", *NAME_MAP.keys()}

CHAR_META = {
    "anon": {
        "name": "聊天 - 千早爱音",
        "description": "扮演千早爱音。同性恋，喜欢长崎素世。官方号+爱音 NapCat 双发。",
        "memory_scope": "anon_group",
        "im_send": ["qq_official_bot", "qq_user_bot"],
        "lore_title": "补充设定（素世·乐队·群友）",
    },
    "soyo": {
        "name": "聊天 - 长崎素世",
        "description": "扮演长崎素世。同性恋，喜欢千早爱音。仅素世 NapCat 发送。",
        "memory_scope": "soyo_group",
        "im_send": ["qq_soyo"],
        "lore_title": "补充设定（爱音·乐队·群友）",
    },
}


def _persona_dir(character: str) -> Path:
    path = PERSONA_ROOT / character
    if path.is_dir():
        return path
    return PERSONA_ROOT


def _load_text(character: str, name: str) -> str:
    raw = (_persona_dir(character) / name).read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    return raw + "\n\n"


def _ensure_block(blocks: list, name: str, payload: dict) -> None:
    for i, item in enumerate(blocks):
        if item.get("name") == name:
            keep_pos = item.get("position") or payload["position"]
            blocks[i] = payload
            blocks[i]["position"] = keep_pos
            return
    blocks.append(payload)


def _drop_wires_to(blocks: list, targets: set[str]) -> None:
    for item in blocks:
        wires = item.get("connected_to") or []
        item["connected_to"] = [w for w in wires if w.get("target") not in targets]


def _ensure_wire(node: dict, target: str, src: str, dst: str) -> None:
    wires = node.setdefault("connected_to", [])
    for wire in wires:
        mapping = wire.get("mapping") or {}
        if wire.get("target") == target and mapping.get("from") == src and mapping.get("to") == dst:
            return
    wires.append({"target": target, "mapping": {"from": src, "to": dst}})


def _block(blocks: list, name: str) -> dict:
    for item in blocks:
        if item.get("name") == name:
            return item
    raise KeyError(name)


def _migrate_names(blocks: list) -> None:
    have = {item.get("name") for item in blocks}
    kept = []
    for item in blocks:
        old = item.get("name")
        if old in NAME_MAP:
            new = NAME_MAP[old]
            if new in have and new != old:
                continue
            item["name"] = new
            have.add(new)
        for wire in item.get("connected_to") or []:
            target = wire.get("target")
            if target in NAME_MAP:
                wire["target"] = NAME_MAP[target]
        kept.append(item)
    blocks[:] = kept


def _set_param(block: dict, key: str, value) -> None:
    params = block.setdefault("params", {})
    params[key] = value


def patch_character(data: dict, character: str) -> dict:
    meta = CHAR_META[character]
    data = deepcopy(data)
    data["name"] = meta["name"]
    data["description"] = meta["description"]
    blocks = list(data["blocks"])
    _migrate_names(blocks)
    blocks = [b for b in blocks if b.get("name") not in DROP]
    data["blocks"] = blocks

    # rename lore node title for soyo display (optional keep same for wiring)
    lore_name = LORE
    if character == "soyo":
        # keep wire-compatible Chinese name used in concat
        lore_name = LORE

    if character in LAYERED_CHARACTERS:
        dropped = {CORE, LORE, CONCAT_LORE}
        blocks[:] = [b for b in blocks if b.get("name") not in dropped]
        _drop_wires_to(blocks, dropped)
        _ensure_block(
            blocks,
            PERSONA_LAYERS,
            {
                "type": "world_state:persona_layers",
                "name": PERSONA_LAYERS,
                "params": {"character": character},
                "position": {"x": 530, "y": 300},
                "connected_to": [],
            },
        )
        data["blocks"] = blocks

    for name, filename, x, y in _sections_for(character):
        text_name = name
        _ensure_block(
            blocks,
            text_name,
            {
                "type": "internal:text_block",
                "name": text_name,
                "params": {"text": _load_text(character, filename)},
                "position": {"x": x, "y": y},
                "connected_to": [],
            },
        )

    for name, x, y, src1, from1, src2, from2 in _concats_for(character):
        _ensure_block(
            blocks,
            name,
            {
                "type": "internal:text_concat_block",
                "name": name,
                "params": {},
                "position": {"x": x, "y": y},
                "connected_to": [],
            },
        )
        _ensure_wire(_block(blocks, src1), name, from1, "text1")
        _ensure_wire(_block(blocks, src2), name, from2, "text2")

    for bname in ("query_world_state", "apply_world_state", "extract_world_state"):
        try:
            _set_param(_block(blocks, bname), "character", character)
        except KeyError:
            pass

    # 回复模型跟随模型管理：清空工作流硬编码，走 defaults.llm_model + 后端 models 自动切换
    for item in blocks:
        btype = item.get("type") or ""
        params = item.setdefault("params", {})
        if btype == "internal:chat_completion":
            params.pop("model_name", None)
            params.pop("vision_model_name", None)
            params["enable_model_failover"] = True
        if btype in ("world_state:extract", "world_state:extract_user"):
            params.pop("model_name", None)

    query = _block(blocks, "query_world_state")
    _drop_wires_to([query], {"inject_world_state", CONCAT_WORLD, "concat_world"})
    _ensure_wire(query, CONCAT_WORLD, "text", "text2")

    # memory scopes + replace store with gated store
    for item in list(blocks):
        if item.get("type") == "internal:chat_memory_query":
            _set_param(item, "scope_type", meta["memory_scope"])
        if item.get("type") == "world_state:gated_memory":
            _set_param(item, "scope_type", meta["memory_scope"])
        if item.get("type") == "internal:chat_memory_store":
            old_name = item.get("name")
            item["type"] = "world_state:gated_memory"
            item["name"] = "gated_chat_memory"
            _set_param(item, "scope_type", meta["memory_scope"])
            # retarget wires that pointed at old store
            for b in blocks:
                for wire in b.get("connected_to") or []:
                    if wire.get("target") == old_name:
                        wire["target"] = "gated_chat_memory"

    # dialogue context
    _ensure_block(
        blocks,
        "dialogue_context",
        {
            "type": "world_state:dialogue",
            "name": "dialogue_context",
            "params": {"character": character},
            "position": {"x": 530, "y": 700},
            "connected_to": [],
        },
    )
    _ensure_block(
        blocks,
        "query_scene_context",
        {
            "type": "world_state:query_scene",
            "name": "query_scene_context",
            "params": {"character": character},
            "position": {"x": 530, "y": 860},
            "connected_to": [],
        },
    )
    _ensure_block(
        blocks,
        "append_scene_context",
        {
            "type": "world_state:append_scene",
            "name": "append_scene_context",
            "params": {"character": character},
            "position": {"x": 1710, "y": 520},
            "connected_to": [],
        },
    )
    get_message = _block(blocks, "get_message")
    _ensure_wire(get_message, "dialogue_context", "sender", "chat_sender")
    _ensure_wire(get_message, "dialogue_context", "msg", "user_msg")
    _ensure_wire(get_message, "query_scene_context", "sender", "chat_sender")
    _ensure_wire(get_message, "append_scene_context", "sender", "chat_sender")
    _ensure_wire(get_message, "append_scene_context", "msg", "user_msg")
    if character in LAYERED_CHARACTERS:
        _ensure_wire(get_message, PERSONA_LAYERS, "sender", "chat_sender")
        _ensure_wire(
            _block(blocks, "dialogue_context"), PERSONA_LAYERS, "message_mode", "message_mode"
        )
        _ensure_wire(
            _block(blocks, "dialogue_context"),
            PERSONA_LAYERS,
            "interaction_mode",
            "interaction_mode",
        )
        _ensure_wire(
            _block(blocks, "query_scene_context"), PERSONA_LAYERS, "text", "current_scene"
        )

    ctor = next(b for b in blocks if b.get("type") == "internal:chat_message_constructor")
    _drop_wires_to(blocks, {ctor["name"]})
    _ensure_wire(get_message, ctor["name"], "msg", "user_msg")
    _ensure_wire(_block(blocks, USER_PROMPT), ctor["name"], "text", "user_prompt_format")
    _ensure_wire(_block(blocks, "query_memory"), "gate_memory_query", "memory_content", "memory_content")
    _ensure_block(
        blocks,
        "gate_memory_query",
        {
            "type": "world_state:gate_memory",
            "name": "gate_memory_query",
            "params": {},
            "position": {"x": 740, "y": 338},
            "connected_to": [],
        },
    )
    _ensure_wire(_block(blocks, "gate_memory_query"), ctor["name"], "memory_content", "memory_content")
    _ensure_wire(
        _block(blocks, "dialogue_context"),
        "gate_memory_query",
        "message_mode",
        "message_mode",
    )
    _ensure_wire(_block(blocks, CONCAT_FINAL), ctor["name"], "text", "system_prompt_format")
    _ensure_wire(_block(blocks, "dialogue_context"), ctor["name"], "text", "dialogue_target")
    _ensure_wire(
        _block(blocks, "dialogue_context"), ctor["name"], "user_prompt_text", "user_prompt_text"
    )
    _ensure_wire(
        _block(blocks, "dialogue_context"), ctor["name"], "critical_instruction", "critical_instruction"
    )
    _ensure_wire(
        _block(blocks, "query_scene_context"), ctor["name"], "text", "current_scene"
    )

    # gated memory: skip flag from dialogue
    try:
        gated = _block(blocks, "gated_chat_memory")
        _ensure_wire(get_message, "gated_chat_memory", "msg", "user_msg")
        _ensure_wire(
            _block(blocks, "dialogue_context"),
            "gated_chat_memory",
            "skip_chat_memory",
            "skip_chat_memory",
        )
    except KeyError:
        pass

    _ensure_wire(get_message, "query_world_state", "sender", "chat_sender")
    _ensure_wire(get_message, "apply_world_state", "sender", "chat_sender")
    _ensure_wire(get_message, "apply_world_state", "msg", "user_msg")

    _ensure_block(
        blocks,
        "extract_world_state",
        {
            "type": "world_state:extract",
            "name": "extract_world_state",
            "params": {
                "always": True,
                "character": character,
            },
            "position": {"x": 1710, "y": 450},
            "connected_to": [],
        },
    )
    apply_block = _block(blocks, "apply_world_state")
    _ensure_wire(apply_block, "extract_world_state", "llm_resp", "llm_resp")
    _ensure_wire(apply_block, "extract_world_state", "user_msg", "user_msg")
    _ensure_wire(apply_block, "extract_world_state", "chat_sender", "chat_sender")
    _ensure_wire(
        _block(blocks, "dialogue_context"),
        "extract_world_state",
        "extract_priority",
        "extract_priority",
    )
    # env scene append after reply
    _ensure_wire(apply_block, "append_scene_context", "llm_resp", "llm_resp")
    _ensure_wire(
        _block(blocks, "dialogue_context"),
        "append_scene_context",
        "message_mode",
        "message_mode",
    )
    _ensure_wire(
        _block(blocks, "dialogue_context"),
        "append_scene_context",
        "narration",
        "narration",
    )
    _ensure_wire(
        _block(blocks, "dialogue_context"),
        "append_scene_context",
        "narration_source",
        "narration_source",
    )
    if "gated_chat_memory" in {b.get("name") for b in blocks}:
        _ensure_wire(apply_block, "gated_chat_memory", "llm_resp", "llm_resp")

    if character in LAYERED_CHARACTERS:
        _ensure_block(
            blocks,
            "guard_character_reply",
            {
                "type": "world_state:guard_reply",
                "name": "guard_character_reply",
                "params": {"character": character},
                "position": {"x": 1380, "y": 138},
                "connected_to": [],
            },
        )
        llm_chat = next(b for b in blocks if b.get("type") == "internal:chat_completion")
        ctor = next(b for b in blocks if b.get("type") == "internal:chat_message_constructor")
        _drop_wires_to([llm_chat], {"apply_world_state", "guard_character_reply"})
        _ensure_wire(llm_chat, "guard_character_reply", "resp", "llm_resp")
        _ensure_wire(ctor, "guard_character_reply", "llm_msg", "prompt")
        _ensure_wire(
            _block(blocks, "dialogue_context"),
            "guard_character_reply",
            "message_mode",
            "message_mode",
        )
        _ensure_wire(get_message, "guard_character_reply", "sender", "chat_sender")
        _ensure_wire(
            _block(blocks, "guard_character_reply"),
            "apply_world_state",
            "llm_resp",
            "llm_resp",
        )

    # send adapters
    converter = next(b for b in blocks if b.get("type") == "internal:chat_response_converter")
    send_blocks = [b for b in blocks if b.get("type") == "internal:send_message"]
    for sb in send_blocks:
        _drop_wires_to([converter], {sb["name"]})
    blocks[:] = [b for b in blocks if b.get("type") != "internal:send_message"]

    positions = [{"x": 2140, "y": 60}, {"x": 2140, "y": 220}]
    names = {
        "qq_official_bot": "SendOfficialBot",
        "qq_user_bot": "SendUserBot",
        "qq_soyo": "SendSoyoBot",
    }
    for i, im in enumerate(meta["im_send"]):
        sname = names[im]
        _ensure_block(
            blocks,
            sname,
            {
                "type": "internal:send_message",
                "name": sname,
                "params": {"im_name": im},
                "position": positions[min(i, len(positions) - 1)],
                "connected_to": [],
            },
        )
        _ensure_wire(converter, sname, "msg", "msg")

    return data


def build_memory_store(character: str) -> dict:
    return {
        "name": f"记录聊天内容（{character}）",
        "description": f"仅同伴/@ 写入对话记忆；长期抽取写入 {character} 作用域。",
        "blocks": [
            {
                "type": "internal:get_message",
                "name": "get_message",
                "params": {},
                "position": {"x": 100, "y": 138},
                "connected_to": [
                    {
                        "target": "filter_fallback_memory",
                        "mapping": {"from": "msg", "to": "user_msg"},
                    },
                    {
                        "target": "extract_user_world_state",
                        "mapping": {"from": "msg", "to": "user_msg"},
                    },
                    {
                        "target": "extract_user_world_state",
                        "mapping": {"from": "sender", "to": "chat_sender"},
                    },
                ],
            },
            {
                "type": "world_state:filter_fallback_memory",
                "name": "filter_fallback_memory",
                "params": {"character": character},
                "position": {"x": 320, "y": 138},
                "connected_to": [
                    {
                        "target": "gated_chat_memory",
                        "mapping": {"from": "user_msg", "to": "user_msg"},
                    },
                    {
                        "target": "gated_chat_memory",
                        "mapping": {"from": "skip_chat_memory", "to": "skip_chat_memory"},
                    },
                ],
            },
            {
                "type": "world_state:gated_memory",
                "name": "gated_chat_memory",
                "params": {"scope_type": CHAR_META[character]["memory_scope"]},
                "position": {"x": 560, "y": 138},
                "connected_to": [],
            },
            {
                "type": "world_state:extract_user",
                "name": "extract_user_world_state",
                "params": {
                    "character": character,
                },
                "position": {"x": 420, "y": 300},
                "connected_to": [],
            },
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", choices=["anon", "soyo", "all"], default="all")
    args = parser.parse_args()
    characters = ["anon", "soyo"] if args.character == "all" else [args.character]

    base = yaml.safe_load(NORMAL.read_text(encoding="utf-8"))
    for character in characters:
        patched = patch_character(base, character)
        out = WORKFLOW_DIR / f"{character}.yaml"
        out.write_text(yaml.safe_dump(patched, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print("wrote", out)

        mem = build_memory_store(character)
        mem_out = WORKFLOW_DIR / f"memory_store_{character}.yaml"
        mem_out.write_text(yaml.safe_dump(mem, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print("wrote", mem_out)

    # keep chat:normal as alias of anon for old links
    anon = yaml.safe_load((WORKFLOW_DIR / "anon.yaml").read_text(encoding="utf-8"))
    NORMAL.write_text(yaml.safe_dump(anon, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("synced", NORMAL, "← anon")


if __name__ == "__main__":
    main()
