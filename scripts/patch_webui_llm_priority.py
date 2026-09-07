# -*- coding: utf-8 -*-
"""Inject priority controls into Kirara LLM model page + nginx shortcut."""
from pathlib import Path

WEBUI = Path("/opt/kirara-ai/webui")
LOCAL_WEBUI = Path(__file__).resolve().parents[1] / "web"

H2 = "\u6a21\u578b\u7ba1\u7406"  # 模型管理
LIST = "\u6a21\u578b\u5217\u8868"  # 模型列表
BTN = "\u4f18\u5148\u7ea7\u8c03\u6574"  # 优先级调整
OPEN = "\u6253\u5f00\u4f18\u5148\u7ea7\u8c03\u6574"  # 打开优先级调整
HINT = (
    "\u6587\u672c/\u8bc6\u56fe\u8c03\u7528\u987a\u5e8f\u53ef\u5728\u6b64\u8c03\u6574\uff1b"
    "\u8d8a\u9760\u524d\u8d8a\u4f18\u5148\u3002"
)  # 文本/识图调用顺序可在此调整；越靠前越优先。

OPEN_JS = (
    '(()=>{const t=localStorage.getItem("token")||"";'
    'window.open("/qqbot/llm-priority"+(t?"?auth_token="+encodeURIComponent(t):""),"_blank")})()'
)
OLD_OPEN = 'window.open("/qqbot/llm-priority","_blank")'
NEW_OPEN = OPEN_JS

OLD_HEADER = f'C("h2",null,"{H2}",-1)),o(t(S),null,{{default:r(()=>['
NEW_HEADER = (
    f'C("h2",null,"{H2}",-1)),o(t(S),null,{{default:r(()=>['
    f'o(t(N),{{onClick:()=>{OPEN_JS},class:"action-button"}},'
    f'{{default:r(()=>[M(" {BTN} ")]),_:1}}),'
)

OLD_MODELS = f'o(t(j),{{class:"config-section",title:"{LIST}"}}'
NEW_MODELS = (
    f'o(t(j),{{class:"config-section",title:"{BTN}"}},'
    f'{{default:r(()=>[C("div",{{style:"display:flex;gap:8px;align-items:center;flex-wrap:wrap;"}},'
    f'[C("span",{{style:"opacity:.75"}},"{HINT}"),'
    f'o(t(N),{{type:"primary",size:"small",onClick:()=>{OPEN_JS}}},'
    f'{{default:r(()=>[M("{OPEN}")]),_:1}})])])}}),'
    f'o(t(j),{{class:"config-section",title:"{LIST}"}}'
)


def patch_llm_view(root: Path) -> int:
    changed = 0
    for path in root.rglob("LLMView.js"):
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
        original = text
        if OLD_OPEN in text:
            text = text.replace(OLD_OPEN, NEW_OPEN)
            print("open url upgraded", path)
        if BTN in text and OPEN in text and OLD_OPEN not in text and OPEN_JS in text:
            print("already patched", path)
        elif BTN not in text or OPEN not in text:
            if OLD_HEADER in text:
                text = text.replace(OLD_HEADER, NEW_HEADER, 1)
                print("header patched", path)
            else:
                print("HEADER_PATTERN_MISSING", path)
            if OLD_MODELS in text and OPEN not in text:
                text = text.replace(OLD_MODELS, NEW_MODELS, 1)
                print("section patched", path)
            elif OPEN in text:
                print("section already patched", path)
            else:
                print("MODELS_PATTERN_MISSING", path)
        if text != original:
            path.write_text(text, encoding="utf-8", errors="surrogateescape")
            changed += 1
    return changed


def patch_nginx() -> None:
    conf = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
    if not conf.is_file():
        print("nginx conf missing", conf)
        return
    text = conf.read_text(encoding="utf-8")
    if "location = /qqbot/llm-priority" in text:
        print("nginx already has llm-priority")
        return
    insert = """    location = /qqbot/llm-priority {
        proxy_pass http://127.0.0.1:8080/backend-api/api/llm/priority/ui;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

"""
    for needle in (
        "    location = /qqbot/world-state {",
        "    location /qqbot/backend-api/ {",
    ):
        if needle in text:
            conf.write_text(text.replace(needle, insert + needle, 1), encoding="utf-8")
            print("nginx llm-priority inserted before", needle.strip())
            return
    print("NGINX_NEEDLE_MISSING")


if __name__ == "__main__":
    total = 0
    for root in (WEBUI, LOCAL_WEBUI):
        if root.is_dir():
            total += patch_llm_view(root)
    print("files_changed", total)
    if WEBUI.exists() or Path("/www/server/panel/vhost/nginx/ansy.love.conf").exists():
        patch_nginx()
