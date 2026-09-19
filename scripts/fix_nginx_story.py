#!/usr/bin/env python3
from pathlib import Path
import re

p = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
text = p.read_text(encoding="utf-8")
text2 = re.sub(
    r"\n    location = /qqbot/story \{.*?\n    \}\n",
    "\n",
    text,
    count=1,
    flags=re.S,
)
block = """
    location = /qqbot/story {
        proxy_pass http://127.0.0.1:8080/backend-api/api/story/form;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_intercept_errors off;
    }

"""
marker = "    location = /qqbot/world-state {"
if "location = /qqbot/story" in text2:
    raise SystemExit("story block still present after strip")
if marker not in text2:
    raise SystemExit("marker missing")
text2 = text2.replace(marker, block + marker, 1)
p.write_text(text2, encoding="utf-8")
print("nginx story location fixed")
