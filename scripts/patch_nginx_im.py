from pathlib import Path

CONF = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
text = CONF.read_text(encoding="utf-8")

IM_BLOCK = """
    # Kirara QQ webhook only. Do not proxy all of /im/ (WebUI also uses /im).
    location /im/webhook/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_cache off;
        proxy_intercept_errors off;
    }
"""

QQBOT_BLOCK = """
    location = /qqbot {
        return 302 /qqbot/;
    }

    # Kirara WebUI on a dedicated prefix. Does not take over /, /api/, or hashed /assets/.
    location /qqbot/ {
        gzip off;
        proxy_pass http://127.0.0.1:8080/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Accept-Encoding "";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_cache off;
        proxy_intercept_errors off;
        sub_filter_once off;
        sub_filter_types text/html application/javascript text/css;
        sub_filter 'Ql="/backend-api/api"' 'Ql="/qqbot/backend-api/api"';
        sub_filter 'src="/assets/' 'src="/qqbot/assets/';
        sub_filter 'href="/assets/' 'href="/qqbot/assets/';
        sub_filter 'href="/favicon.ico"' 'href="/qqbot/favicon.ico"';
        sub_filter '"/assets/' '"/qqbot/assets/';
        sub_filter 'path:"/' 'path:"/qqbot/';
    }
"""


def replace_location(src: str, prefix: str, new_block: str) -> str:
    token = f"    location {prefix}"
    start = src.find(token)
    if start == -1:
        return src
    brace = src.find("{", start)
    if brace == -1:
        return src
    depth = 0
    i = brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                while end < len(src) and src[end] in "\r\n":
                    end += 1
                return src[:start] + new_block.strip("\n") + "\n\n" + src[end:]
        i += 1
    raise SystemExit(f"unclosed location {prefix}")


if "location /im/" in text and "location /im/webhook/" not in text:
    text = replace_location(text, "/im/", IM_BLOCK)
elif "location /im/webhook/" in text:
    text = replace_location(text, "/im/webhook/", IM_BLOCK)
else:
    marker = "    location /api/ {"
    if marker not in text:
        raise SystemExit("cannot find /api/ location to insert webhook")
    text = text.replace(marker, IM_BLOCK.lstrip("\n") + "\n" + marker, 1)

if "location /qqbot/" in text:
    text = replace_location(text, "/qqbot/", QQBOT_BLOCK)
    # drop a leftover exact /qqbot redirect if duplicated later; rewrite as a pair
else:
    marker = "    location /im/webhook/"
    if marker not in text:
        marker = "    location /api/ {"
    insert_at = text.find(marker)
    if insert_at == -1:
        raise SystemExit("cannot find insert point for /qqbot/")
    text = text[:insert_at] + QQBOT_BLOCK.lstrip("\n") + "\n" + text[insert_at:]

if "location = /qqbot" not in text:
    text = text.replace("    location /qqbot/", "    location = /qqbot {\n        return 302 /qqbot/;\n    }\n\n    location /qqbot/", 1)

CONF.write_text(text, encoding="utf-8")
print(CONF.read_text(encoding="utf-8"))
