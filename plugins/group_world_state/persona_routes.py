"""分角色人设模块 + 爱好分类：网页编辑。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from quart import Blueprint, Response, request

from kirara_ai.web.auth.middleware import require_auth

from .blocks import (
    PERSONA_MODULES,
    load_persona_module,
    persona_module_path,
    read_persona_module_raw,
    save_persona_module,
    save_persona_module_pack,
)
from .persona_text import strip_workflow_chrome
from .characters import get_character
from .persona_pack import (
    MODULE_SECTIONS,
    pack_from_request as persona_pack_from_request,
    parse_persona_pack,
)
from .topic_classify import (
    format_hobby_pack,
    hobby_module_path,
    invalidate_taxonomy,
    list_hobby_ids,
    load_hobby_module,
    load_hobbies_doc,
    normalize_items,
    pack_from_request as hobby_pack_from_request,
    parse_hobby_pack,
    save_hobby_module,
    save_hobbies_doc,
)

persona_bp = Blueprint("persona", __name__)
UI_PATH = Path(__file__).with_name("persona_ui.html")

ALLOWED_CHARS = ("soyo", "anon")
MODULE_META = (
    (
        "base",
        "身份与性格",
        "每轮都注入：身份、性格、称呼。爱好长文已迁到左侧「爱好设定」。",
        "文首【同伴绑定】```peer 块绑定同伴 QQ/称呼/身份；系统按 peer_qq 分流。"
        "只写这个角色是谁、怎么说话、怎么称呼。"
        "不要在 Base 堆吉他/红茶等爱好长文——到「爱好设定」按分类写，系统按本轮话题注入。"
        "不要写「工作流」「优先级」「[P0]」。",
    ),
    (
        "companion",
        "同伴互聊",
        "仅另一位 Bot 对你说话时注入，与 @ / 故事互斥。",
        "只写跟同伴怎么聊、怎么收束。同伴是谁以 Base【同伴绑定】为准；被 @ 或讲故事时不加载。",
    ),
    (
        "trigger",
        "被@响应",
        "仅群友 @ 你或点名时注入，与同伴互聊 / 故事互斥。",
        "只写被点到时怎么回。问答体禁令由工作流在系统提示末尾加 [P0]，不必在文里声明。",
    ),
    (
        "scene",
        "场景氛围",
        "仅环境音 / 场面轮注入；被 @ 时不注入（场面仍会从别处进入提示）。",
        "只写环境/场面怎么带入语气。无爱好命中时的默认反应以爱好设定 idle_ambient 为准。",
    ),
    (
        "story",
        "故事模式",
        "仅故事进行中注入，与 @ / 同伴互聊互斥。",
        "只写故事里怎么演、怎么停。日常接话让位由工作流处理。",
    ),
    (
        "mode_phone",
        "手机模式",
        "命令 /phone 或 [手机模式] 开启后叠加；高于 Base speech。",
        "只写即时通讯碎句、<break>、emoji/占位符。勿写括号动作。关闭：/phone off 或 /mode face。",
    ),
)
WRITE_NOTE = (
    "按模块写角色正文即可。"
    "爱好/喜欢聊什么：请用左侧「爱好设定」（分类关键词 + 分套正文），"
    "系统用 jieba+embedding 识别本轮话题后只注入命中那一套，不会把全部爱好丢进提示词。"
    "同伴 QQ 写在「身份与性格」文首【同伴绑定】。"
)


def _char_or_404(character: str):
    cid = (character or "").strip()
    if cid not in ALLOWED_CHARS:
        return None
    return cid


def _module_or_404(module: str):
    mid = (module or "").strip()
    if mid not in PERSONA_MODULES:
        return None
    return mid


def _meta_of(module: str):
    return next((m for m in MODULE_META if m[0] == module), (module, module, "", ""))


def _module_row(character: str, module: str) -> dict:
    _mid, label, when, hint = _meta_of(module)
    path = persona_module_path(character, module)
    exists = path.is_file()
    updated = ""
    size = 0
    if exists:
        stat = path.stat()
        size = int(stat.st_size)
        updated = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    return {
        "id": module,
        "label": label,
        "when": when,
        "hint": hint,
        "bytes": size,
        "updated_at": updated,
        "exists": exists,
    }


def _hobby_row(character: str, cat: dict) -> dict:
    hid = str(cat.get("id") or "")
    path = hobby_module_path(character, hid)
    exists = path.is_file()
    size = 0
    updated = ""
    if exists:
        stat = path.stat()
        size = int(stat.st_size)
        updated = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    return {
        "id": hid,
        "label": str(cat.get("display_name") or hid),
        "stance": str(cat.get("reply_stance") or "soft"),
        "priority": int(cat.get("priority") or 3),
        "keywords": normalize_items(cat.get("keywords")),
        "aliases": normalize_items(cat.get("aliases")),
        "sample_lines": normalize_items(cat.get("sample_lines")),
        "forbid_pivot": bool(cat.get("forbid_pivot")),
        "mode_hints": list(cat.get("mode_hints") or []),
        "bytes": size,
        "updated_at": updated,
        "exists": exists,
        "when": "仅本轮话题命中时注入正文；关键词用于检测",
    }


@persona_bp.route("/ui", methods=["GET"])
async def ui():
    resp = Response(UI_PATH.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@persona_bp.route("/catalog", methods=["GET"])
@require_auth
async def catalog():
    characters = []
    for cid in ALLOWED_CHARS:
        meta = get_character(cid)
        doc = load_hobbies_doc(cid)
        characters.append(
            {
                "id": cid,
                "display": str(meta.get("display") or cid),
                "modules": [_module_row(cid, mid) for mid, *_rest in MODULE_META],
                "hobbies": [_hobby_row(cid, cat) for cat in (doc.get("categories") or [])],
                "detector": dict(doc.get("detector") or {}),
            }
        )
    return {"characters": characters, "note": WRITE_NOTE}


@persona_bp.route("/<character>/modules/<module>", methods=["GET"])
@require_auth
async def get_module(character: str, module: str):
    cid = _char_or_404(character)
    mid = _module_or_404(module)
    if not cid or not mid:
        return {"error": "not found"}, 404
    try:
        text = strip_workflow_chrome(read_persona_module_raw(cid, mid))
    except FileNotFoundError:
        text = ""
    pack = parse_persona_pack(text, mid)
    pack["module"] = mid
    info = _module_row(cid, mid)
    info["text"] = text
    info["pack"] = pack
    info["sections"] = [
        {"key": k, "label": lab, "kind": kind}
        for k, lab, kind in MODULE_SECTIONS.get(mid, [])
    ]
    info["character"] = cid
    info["injected_len"] = len(load_persona_module(cid, mid))
    info["kind"] = "module"
    info["hint"] = (
        "用表单分条填写；base/trigger 保存为紧凑 XML 注入，其它模块为 [PERSONA_PACK]（注入时去掉 :: 备注）。"
        "旧 Markdown / PERSONA_PACK 打开时会自动拆分。"
    )
    return info


@persona_bp.route("/<character>/modules/<module>", methods=["PUT"])
@require_auth
async def put_module(character: str, module: str):
    cid = _char_or_404(character)
    mid = _module_or_404(module)
    if not cid or not mid:
        return {"error": "not found"}, 404
    data = await request.get_json() or {}
    try:
        if isinstance(data.get("pack"), dict) or any(
            k in data for k, _l, _kd in MODULE_SECTIONS.get(mid, [])
        ):
            saved = save_persona_module_pack(cid, mid, data)
        else:
            saved = save_persona_module(cid, mid, data.get("text") or "")
            saved["pack"] = parse_persona_pack(saved.get("text") or "", mid)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    info = _module_row(cid, mid)
    info.update(saved)
    info["sections"] = [
        {"key": k, "label": lab, "kind": kind}
        for k, lab, kind in MODULE_SECTIONS.get(mid, [])
    ]
    info["injected_len"] = len(load_persona_module(cid, mid))
    info["kind"] = "module"
    return info


@persona_bp.route("/<character>/hobbies/<hobby_id>", methods=["GET"])
@require_auth
async def get_hobby(character: str, hobby_id: str):
    cid = _char_or_404(character)
    hid = (hobby_id or "").strip()
    if not cid or hid not in list_hobby_ids(cid):
        return {"error": "not found"}, 404
    cats = {str(c.get("id")): c for c in load_hobbies_doc(cid).get("categories") or []}
    row = _hobby_row(cid, cats[hid])
    text = load_hobby_module(cid, hid)
    pack = parse_hobby_pack(text)
    if not pack.get("id"):
        pack["id"] = hid
    if not pack.get("stance"):
        pack["stance"] = str(row.get("stance") or "soft")
    row["text"] = text
    row["pack"] = pack
    row["character"] = cid
    row["kind"] = "hobby"
    row["hint"] = (
        "用下方表单填写；保存后自动生成机器可读 [HOBBY_PACK]，"
        "仅本轮话题命中时注入，其它爱好不会加载。"
    )
    return row


@persona_bp.route("/<character>/hobbies/<hobby_id>", methods=["PUT"])
@require_auth
async def put_hobby(character: str, hobby_id: str):
    cid = _char_or_404(character)
    hid = (hobby_id or "").strip()
    if not cid:
        return {"error": "not found"}, 404
    data = await request.get_json() or {}
    doc = load_hobbies_doc(cid)
    cats = list(doc.get("categories") or [])
    found = None
    for cat in cats:
        if str(cat.get("id")) == hid:
            found = cat
            break
    if found is None:
        found = {"id": hid}
        cats.append(found)
    if data.get("label") is not None:
        found["display_name"] = str(data.get("label") or hid)
    if data.get("stance") is not None:
        found["reply_stance"] = str(data.get("stance") or "soft")
    if data.get("priority") is not None:
        try:
            found["priority"] = int(data.get("priority"))
        except (TypeError, ValueError):
            found["priority"] = 3
    if data.get("keywords") is not None:
        found["keywords"] = normalize_items(data.get("keywords"))
    if data.get("aliases") is not None:
        found["aliases"] = normalize_items(data.get("aliases"))
    if data.get("sample_lines") is not None:
        found["sample_lines"] = normalize_items(data.get("sample_lines"))
    if data.get("forbid_pivot") is not None:
        found["forbid_pivot"] = bool(data.get("forbid_pivot"))
    if data.get("mode_hints") is not None:
        found["mode_hints"] = [
            str(x).strip() for x in (data.get("mode_hints") or []) if str(x).strip()
        ]

    has_pack = isinstance(data.get("pack"), dict) or any(
        k in data
        for k in ("facts", "allow", "forbid", "tone", "behaviors", "ex_ok", "ex_bad")
    )
    if has_pack:
        pack = hobby_pack_from_request(
            data, hid, stance=str(found.get("reply_stance") or data.get("stance") or "soft")
        )
        pack["id"] = hid
        text = format_hobby_pack(pack)
    else:
        text = data.get("text") or ""
        pack = parse_hobby_pack(text)
        pack["id"] = hid

    try:
        save_hobbies_doc(cid, {"detector": doc.get("detector") or {}, "categories": cats})
        saved_mod = save_hobby_module(cid, hid, text)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    invalidate_taxonomy(cid)
    row = _hobby_row(cid, found)
    row.update(saved_mod)
    row["pack"] = parse_hobby_pack(saved_mod.get("text") or text)
    row["kind"] = "hobby"
    return row


@persona_bp.route("/<character>/detector", methods=["PUT"])
@require_auth
async def put_detector(character: str):
    cid = _char_or_404(character)
    if not cid:
        return {"error": "not found"}, 404
    data = await request.get_json() or {}
    doc = load_hobbies_doc(cid)
    det = dict(doc.get("detector") or {})
    for key in ("mode", "embed_model", "embed_threshold", "keyword_min_score"):
        if key in data and data[key] is not None:
            det[key] = data[key]
    save_hobbies_doc(cid, {"detector": det, "categories": doc.get("categories") or []})
    return {"character": cid, "detector": det}
