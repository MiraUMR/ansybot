#!/usr/bin/env python3
"""Rewrite Kirara WebUI so it can be served under /qqbot/ without colliding with the main site."""
from pathlib import Path

root = Path("/opt/kirara-ai/webui")
replacements = [
    # Vue Router base: push("/login") then becomes /qqbot/login automatically.
    ('history:Ny("/")', 'history:Ny("/qqbot/")'),
    # Vite modulepreload: "assets/Foo.js" was turned into "/assets/Foo.js"
    # and hit the main site SPA instead of Kirara.
    ('a2=function(e){return"/"+e}', 'a2=function(e){return"/qqbot/"+e}'),
    # WorkflowList opens the editor with window.open, which ignores Vue Router base.
    ('window.open("/workflow/', 'window.open("/qqbot/workflow/'),
    ('window.open(`/workflow/', 'window.open(`/qqbot/workflow/'),
    ("/backend-api", "/qqbot/backend-api"),
    ("/assets/", "/qqbot/assets/"),
    ('href="/favicon.ico"', 'href="/qqbot/favicon.ico"'),
]

count_files = 0
for path in list(root.rglob("*.js")) + list(root.rglob("*.css")) + list(root.rglob("*.html")):
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    original = text
    for old, new in replacements:
        text = text.replace(old, new)
    text = text.replace("/qqbot/qqbot/", "/qqbot/")
    # Do not add ?v= on the entry script: GuideView imports ./index.js without
    # a query string, and two module URLs would create two Vue copies (white screen).
    if path.name == "index.html" and "webui-prefix" not in text:
        text = text.replace("<title>Kirara AI</title>", "<title>Kirara AI</title>\n    <!-- webui-prefix /qqbot/ -->")
    if text != original:
        path.write_text(text, encoding="utf-8", errors="surrogateescape")
        count_files += 1
        print("patched", path)
print("files_changed", count_files)
