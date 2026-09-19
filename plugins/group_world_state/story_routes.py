"""Public story form API (HMAC auth, no WebUI login)."""
from __future__ import annotations

import html as html_lib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from quart import Blueprint, Response, g, redirect, request

from .host_manager import StoryHostManager, public_api_prefix, verify_token

story_bp = Blueprint("story_host", __name__)
TEMPLATE = Path(__file__).with_name("templates") / "story_form.html"


def _mgr() -> StoryHostManager:
    try:
        return g.container.resolve(StoryHostManager)
    except Exception:
        mgr = StoryHostManager(g.container)
        try:
            g.container.register(StoryHostManager, mgr)
        except Exception:
            pass
        return mgr


async def _auth_from_form() -> Tuple[str, str, str]:
    form = await request.form
    sid = (form.get("sid") or request.args.get("sid") or "").strip()
    uid = (form.get("uid") or request.args.get("uid") or "").strip()
    token = (form.get("token") or request.args.get("token") or "").strip()
    return sid, uid, token


def _authorize(session: Optional[Dict[str, Any]], sid: str, uid: str, token: str) -> Optional[str]:
    if not session:
        return "会话不存在"
    if str(session.get("initiator_qq") or "") != uid:
        return "403"
    if not verify_token(sid, uid, str(session.get("group_id") or ""), token):
        return "403"
    return None


def _history_text(session: Dict[str, Any]) -> str:
    lines = []
    for item in session.get("history_log") or []:
        if not isinstance(item, dict):
            continue
        bot = item.get("bot") or "?"
        lines.append(f"#{item.get('turn')} [{bot}] 引导：{item.get('prompt')}")
        lines.append(str(item.get("response") or ""))
        lines.append("")
    return "\n".join(lines).strip() or "（尚无记录）"


def _render(
    *,
    session: Optional[Dict[str, Any]] = None,
    sid: str = "",
    uid: str = "",
    token: str = "",
    flash: str = "",
    error: str = "",
) -> Response:
    raw = TEMPLATE.read_text(encoding="utf-8")
    status = str((session or {}).get("status") or "")
    active = status == "ACTIVE"
    html = (
        raw.replace("__ERROR__", html_lib.escape(error) if error else "")
        .replace("__ERROR_CLASS__", "" if error else "hidden")
        .replace("__FLASH__", html_lib.escape(flash) if flash else "")
        .replace("__FLASH_CLASS__", "" if flash else "hidden")
        .replace("__BODY_CLASS__", "hidden" if error else "")
        .replace("__SCENE_DESC__", html_lib.escape(str((session or {}).get("scene_desc") or "")))
        .replace("__SCENE_TYPE__", html_lib.escape(str((session or {}).get("scene_type") or "")))
        .replace("__TURN__", str((session or {}).get("turn_count") or 0))
        .replace("__MAX__", str((session or {}).get("max_turns") or 7))
        .replace("__STATUS__", html_lib.escape(status))
        .replace("__HISTORY__", html_lib.escape(_history_text(session) if session else ""))
        .replace("__FORM_CLASS__", "" if active else "hidden")
        .replace("__DONE_CLASS__", "hidden" if active else "")
        .replace("__SID__", html_lib.escape(sid))
        .replace("__UID__", html_lib.escape(uid))
        .replace("__TOKEN__", html_lib.escape(token))
        .replace("__API_PREFIX__", html_lib.escape(public_api_prefix()))
    )
    return Response(html, mimetype="text/html; charset=utf-8")


@story_bp.route("/form", methods=["GET"])
async def story_form():
    sid = (request.args.get("sid") or "").strip()
    uid = (request.args.get("uid") or "").strip()
    token = (request.args.get("token") or "").strip()
    mgr = _mgr()
    session = mgr.get_session(sid) if sid else None
    err = _authorize(session, sid, uid, token)
    if err == "403":
        return Response("403 Forbidden", status=403)
    if err:
        return _render(error=err, sid=sid, uid=uid, token=token)
    flash = (request.args.get("flash") or "").strip()
    return _render(session=session, sid=sid, uid=uid, token=token, flash=flash)


@story_bp.route("/submit", methods=["POST"])
async def story_submit():
    sid, uid, token = await _auth_from_form()
    form = await request.form
    target = (form.get("target_bot") or "anon").strip().lower()
    action = (form.get("action_prompt") or "").strip()
    mgr = _mgr()
    session = mgr.get_session(sid) if sid else None
    err = _authorize(session, sid, uid, token)
    if err == "403":
        return Response("403 Forbidden", status=403)
    if err:
        return _render(error=err, sid=sid, uid=uid, token=token)
    if not action:
        q = urlencode({"sid": sid, "uid": uid, "token": token, "flash": "请填写行动引导"})
        return redirect(f"{public_api_prefix()}/form?{q}")
    try:
        result = mgr.process_turn(sid, target, action, send_to_group=True)
        flash = f"第 {result['turn']} 幕已发送到群"
    except Exception as exc:
        flash = f"生成失败：{exc}"
    q = urlencode({"sid": sid, "uid": uid, "token": token, "flash": flash})
    return redirect(f"{public_api_prefix()}/form?{q}")


@story_bp.route("/end", methods=["POST"])
async def story_end():
    sid, uid, token = await _auth_from_form()
    mgr = _mgr()
    session = mgr.get_session(sid) if sid else None
    err = _authorize(session, sid, uid, token)
    if err == "403":
        return Response("403 Forbidden", status=403)
    if err:
        return _render(error=err, sid=sid, uid=uid, token=token)
    try:
        summary = mgr.finalize(sid, quiet=False)
        flash = f"已结束。{summary}"
    except Exception as exc:
        flash = f"结束失败：{exc}"
    q = urlencode({"sid": sid, "uid": uid, "token": token, "flash": flash})
    return redirect(f"{public_api_prefix()}/form?{q}")
