from pathlib import Path

from quart import Blueprint, Response, request

from kirara_ai.web.auth.middleware import require_auth

from . import children

children_bp = Blueprint("children_mode", __name__)
UI_PATH = Path(__file__).with_name("children_ui.html")


@children_bp.route("/ui", methods=["GET"])
async def ui():
    return Response(UI_PATH.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")


@children_bp.route("/config", methods=["GET"])
@require_auth
async def get_config():
    cfg = children.load_config()
    cfg["users"] = children.status_rows()
    return cfg


@children_bp.route("/config", methods=["PUT"])
@require_auth
async def put_config():
    data = await request.get_json() or {}
    saved = children.save_config(data)
    saved["users"] = children.status_rows()
    return saved
