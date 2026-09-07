from pathlib import Path

p = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
text = p.read_text(encoding="utf-8")
old = """    location /qqbot/ {
        alias /opt/kirara-ai/webui/;
        index index.html;
        try_files $uri $uri/ @kirara_spa;
    }"""
new = """    location /qqbot/ {
        alias /opt/kirara-ai/webui/;
        index index.html;
        try_files $uri $uri/ @kirara_spa;
        add_header Cache-Control "no-cache, must-revalidate";
    }"""
if old not in text:
    raise SystemExit("block not found")
p.write_text(text.replace(old, new, 1), encoding="utf-8")
print("nginx patched")
