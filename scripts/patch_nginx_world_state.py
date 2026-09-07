from pathlib import Path

p = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
text = p.read_text(encoding="utf-8")
if "location = /qqbot/world-state" in text:
    print("nginx already has world-state location")
else:
    needle = """    location /qqbot/backend-api/ {
        proxy_pass http://127.0.0.1:8080/backend-api/;
"""
    insert = """    location = /qqbot/world-state {
        proxy_pass http://127.0.0.1:8080/backend-api/api/world-state/ui;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_intercept_errors off;
    }

    location /qqbot/backend-api/ {
        proxy_pass http://127.0.0.1:8080/backend-api/;
"""
    if needle not in text:
        raise SystemExit("nginx backend-api block not found")
    text = text.replace(needle, insert, 1)
    p.write_text(text, encoding="utf-8")
    print("nginx location added")
