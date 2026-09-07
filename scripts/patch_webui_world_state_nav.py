"""Add 长期设定 to Kirara WebUI sidebar."""
from pathlib import Path

root = Path("/opt/kirara-ai/webui")
old_menu = '{label:()=>"插件管理",key:"plugins",icon:o($2)},{label:()=>"系统设置",key:"settings",icon:o(Q2)}]'
new_menu = '{label:()=>"插件管理",key:"plugins",icon:o($2)},{label:()=>"长期设定",key:"world-state",icon:o(j2)},{label:()=>"系统设置",key:"settings",icon:o(Q2)}]'
old_click = "l=a=>{r.push(`/${a}`),n.setCurrentModule(a)}"
new_click = 'l=a=>{a==="world-state"?window.location.assign("/qqbot/world-state"):(r.push(`/${a}`),n.setCurrentModule(a))}'

changed = 0
for path in root.rglob("index.js"):
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    original = text
    if "key:\"world-state\"" not in text and "key:'world-state'" not in text:
        if old_menu not in text:
            print("MENU_PATTERN_MISSING", path)
        else:
            text = text.replace(old_menu, new_menu, 1)
            print("menu patched", path)
    else:
        print("menu already patched", path)
    if 'a==="world-state"' not in text:
        if old_click not in text:
            print("CLICK_PATTERN_MISSING", path)
        else:
            text = text.replace(old_click, new_click, 1)
            print("click patched", path)
    else:
        print("click already patched", path)
    if text != original:
        path.write_text(text, encoding="utf-8", errors="surrogateescape")
        changed += 1
print("files_changed", changed)
