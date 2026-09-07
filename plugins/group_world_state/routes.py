from pathlib import Path

from quart import Blueprint, Response, g, request

from kirara_ai.web.auth.middleware import require_auth

from .store import WorldStateStore

world_state_bp = Blueprint("world_state", __name__)
UI_PATH = Path(__file__).with_name("ui.html")


def _store() -> WorldStateStore:
    return g.container.resolve(WorldStateStore)


def _normalize_scope(raw: str) -> str:
    """Accept anon/1035... or legacy bare group id (→ anon/...)."""
    text = (raw or "").strip().replace("\\", "/")
    if not text:
        return "anon/unknown"
    if "/" not in text:
        return f"anon/{text}"
    return text


@world_state_bp.route("/ui", methods=["GET"])
async def ui():
    return Response(UI_PATH.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")


@world_state_bp.route("/groups", methods=["GET"])
@require_auth
async def list_groups():
    return {"groups": _store().list_groups()}


@world_state_bp.route("/groups/<path:scope>", methods=["GET"])
@require_auth
async def get_group(scope: str):
    scope = _normalize_scope(scope)
    doc = _store().get(scope)
    doc["rendered"] = _store().render(scope)
    doc["scope"] = scope
    return doc


@world_state_bp.route("/groups/<path:scope>", methods=["PUT"])
@require_auth
async def put_group(scope: str):
    scope = _normalize_scope(scope)
    data = await request.get_json() or {}
    facts = data.get("facts") or []
    group_name = data.get("group_name")
    return _store().replace_all(scope, facts, group_name=group_name)


@world_state_bp.route("/groups/<path:scope>/facts/<key>", methods=["PUT"])
@require_auth
async def put_fact(scope: str, key: str):
    scope = _normalize_scope(scope)
    data = await request.get_json() or {}
    text = data.get("text") or ""
    try:
        return _store().set_fact(scope, key, text, source="api", group_name=data.get("group_name"))
    except ValueError as exc:
        return {"error": str(exc)}, 400


@world_state_bp.route("/groups/<path:scope>/facts/<key>", methods=["DELETE"])
@require_auth
async def delete_fact(scope: str, key: str):
    scope = _normalize_scope(scope)
    try:
        return _store().delete_fact(scope, key)
    except KeyError:
        return {"error": "not found"}, 404


@world_state_bp.route("/groups/<path:scope>", methods=["DELETE"])
@require_auth
async def clear_group(scope: str):
    scope = _normalize_scope(scope)
    return _store().clear(scope)
