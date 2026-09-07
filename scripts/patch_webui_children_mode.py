"""Add 儿童模式 nginx shortcut + WebUI sidebar."""
from pathlib import Path

CONF = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
WEBUI = Path("/opt/kirara-ai/webui")

INSERT = """    location = /qqbot/children-mode {
        proxy_pass http://127.0.0.1:8080/backend-api/api/children-mode/ui;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_intercept_errors off;
    }

"""

OLD_CLICK = 'a==="world-state"?window.location.assign("/qqbot/world-state")'
NEW_CLICK = (
    'a==="world-state"?window.location.assign("/qqbot/world-state"):'
    'a==="children-mode"?window.location.assign("/qqbot/children-mode")'
)
OLD_MENU = '{label:()=>"长期设定",key:"world-state",icon:o(j2)},{label:()=>"系统设置"'
NEW_MENU = (
    '{label:()=>"长期设定",key:"world-state",icon:o(j2)},'
    '{label:()=>"儿童模式",key:"children-mode",icon:o(j2)},'
    '{label:()=>"系统设置"'
)


def patch_nginx() -> None:
    if not CONF.is_file():
        print("nginx conf missing", CONF)
        return
    text = CONF.read_text(encoding="utf-8")
    if "location = /qqbot/children-mode" in text:
        print("nginx already has children-mode")
        return
    for needle in (
        "    location = /qqbot/world-state {",
        "    location /qqbot/backend-api/ {",
        "    location /qqbot/ {",
    ):
        if needle in text:
            CONF.write_text(text.replace(needle, INSERT + needle, 1), encoding="utf-8")
            print("nginx children-mode inserted before", needle.strip())
            return
    print("NGINX_NEEDLE_MISSING")


def patch_webui() -> int:
    changed = 0
    if not WEBUI.is_dir():
        return 0
    for path in WEBUI.rglob("index.js"):
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
        original = text
        if 'key:"children-mode"' not in text and "key:'children-mode'" not in text:
            if OLD_MENU in text:
                text = text.replace(OLD_MENU, NEW_MENU, 1)
                print("menu patched", path)
            else:
                print("MENU_PATTERN_MISSING", path)
        else:
            print("menu already patched", path)
        if 'a==="children-mode"' not in text:
            if OLD_CLICK in text:
                text = text.replace(OLD_CLICK, NEW_CLICK, 1)
                print("click patched", path)
            else:
                print("CLICK_PATTERN_MISSING", path)
        else:
            print("click already patched", path)
        if text != original:
            path.write_text(text, encoding="utf-8", errors="surrogateescape")
            changed += 1
    return changed


if __name__ == "__main__":
    patch_nginx()
    print("webui files_changed", patch_webui())
