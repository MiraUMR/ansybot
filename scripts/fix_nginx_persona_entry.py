#!/usr/bin/env python3
"""Point /qqbot/persona at the unified character page (card + classify + modules)."""
from pathlib import Path

p = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
text = p.read_text(encoding="utf-8")
old = "proxy_pass http://127.0.0.1:8080/backend-api/api/persona/ui;"
new = "proxy_pass http://127.0.0.1:8080/backend-api/api/semantic-classify/ui;"
needle = "location = /qqbot/persona {"
i = text.find(needle)
if i < 0:
    raise SystemExit("persona location missing")
end = text.find("\n    }", i)
block = text[i:end]
if "/api/semantic-classify/ui" in block:
    print("already unified")
else:
    if old not in block:
        raise SystemExit("unexpected persona block:\n" + block)
    text = text[:i] + block.replace(old, new, 1) + text[end:]
    p.write_text(text, encoding="utf-8")
    print("persona shortcut now serves unified character page")
