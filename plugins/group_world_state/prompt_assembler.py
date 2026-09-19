"""Minimal story-mode prompt assembly (host-driven, no daily modules)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

PERSONA_ROOT = Path("data/persona")

_MINIMAL_IDENTITY: Dict[str, Tuple[str, List[str]]] = {
    "soyo": ("长崎素世", ["克制内敛", "话少意多", "在意爱音"]),
    "anon": ("千早爱音", ["外放热情", "黏人", "渴望被看见"]),
}


def get_minimal_identity(bot_id: str) -> str:
    cid = (bot_id or "").strip().lower()
    try:
        from .persona_config import identity_header

        header = identity_header(cid)
        if header:
            return header
    except Exception:
        pass
    name, traits = _MINIMAL_IDENTITY.get(cid, (cid or "角色", ["沉浸演绎"]))
    trait_line = "、".join(traits[:3])
    return f"{name}（关键词：{trait_line}）"


def load_story_module(bot_id: str) -> str:
    cid = (bot_id or "").strip().lower()
    try:
        from .compiler import USE_COMPILER, build_story_block
        from .persona_config import load_config

        if USE_COMPILER:
            block = build_story_block(load_config(cid))
            if block:
                return block
    except Exception:
        pass
    path = PERSONA_ROOT / cid / "modules" / f"{cid}_story.md"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return f"# STORY MODE: {cid}\nRespond in character. End with <memory_point>一句情节摘要</memory_point>."


def build_story_prompt(
    bot_id: str,
    session_data: Dict[str, Any],
    user_action: str,
) -> str:
    identity = get_minimal_identity(bot_id)
    rules = load_story_module(bot_id)
    try:
        from .compiler import USE_COMPILER, compile_persona

        if USE_COMPILER:
            compiled = compile_persona(
                bot_id,
                mode="story",
                peer_online=False,
                context_text=user_action or "",
                interaction="face",
                story_prompt=str(session_data.get("story_prompt") or user_action or ""),
            )
            if compiled:
                # story_mode is already inside compiled; do not append the markdown again.
                rules = compiled
    except Exception:
        pass
    scene = (session_data.get("scene_desc") or session_data.get("scene") or "").strip()
    previous = (session_data.get("last_response") or session_data.get("previous") or "").strip()
    action = (user_action or "").strip()
    context = (
        f"[SCENE]: {scene or '（未指定）'}\n"
        f"[PREVIOUS]: {previous or '（开场，尚无上一轮回复）'}\n"
        f"[ACTION REQUIRED]: {action or '（推进一小步）'}"
    )
    return (
        "<system_role>\n"
        f"You are {identity} in a high-intensity Roleplay Story.\n"
        "Ignore all daily chat constraints.\n"
        "Follow the STORY MODE rules below strictly.\n"
        "</system_role>\n\n"
        f"{rules}\n\n"
        f"{context}\n\n"
        "[USER INSTRUCTION FROM HOST]\n"
        f"{action}\n\n"
        "Generate response now. Remember to include <memory_point>...</memory_point>."
    )
