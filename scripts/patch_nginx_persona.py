#!/usr/bin/env python3
from pathlib import Path

p = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
text = p.read_text(encoding="utf-8")
text2 = text.replace(
    "proxy_pass http://127.0.0.1:8080/backend-api/api/persona/ui;",
    "proxy_pass http://127.0.0.1:8080/backend-api/api/semantic-classify/ui;",
    1,
)
if text2 == text:
    raise SystemExit("persona proxy_pass not found")
text = text2
if "location = /qqbot/persona-modules" not in text:
    block = """    location = /qqbot/persona-modules {
        proxy_pass http://127.0.0.1:8080/backend-api/api/persona/ui;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_intercept_errors off;
    }

"""
    needle = "    location = /qqbot/children-mode {"
    if needle not in text:
        raise SystemExit("children-mode block not found")
    text = text.replace(needle, block + needle, 1)
p.write_text(text, encoding="utf-8")
print("NGINX_PATCHED")
