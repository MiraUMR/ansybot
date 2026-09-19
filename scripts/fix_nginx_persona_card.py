#!/usr/bin/env python3
"""Insert /qqbot/persona-card location if missing."""
from pathlib import Path

p = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
text = p.read_text(encoding="utf-8")
if "location = /qqbot/persona-card" in text:
    print("already present")
    raise SystemExit(0)

block = """
    location = /qqbot/persona-card {
        proxy_pass http://127.0.0.1:8080/backend-api/api/persona/card-ui;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_intercept_errors off;
    }

"""
marker = "    location = /qqbot/persona-modules {"
if marker not in text:
    marker = "    location = /qqbot/world-state {"
if marker not in text:
    raise SystemExit("marker missing")
p.write_text(text.replace(marker, block + marker, 1), encoding="utf-8")
print("persona-card location added")
