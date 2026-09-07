from pathlib import Path

p = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
text = p.read_text(encoding="utf-8")
needle = """    location = /qqbot {
        return 302 /qqbot/;
    }"""
insert = """    location = /qqbot {
        return 302 /qqbot/;
    }

    # WorkflowList uses window.open("/workflow/..."), which would otherwise
    # hit the main site SPA and look like a jump back to the homepage.
    location ^~ /workflow {
        return 302 /qqbot$request_uri;
    }"""
if "location ^~ /workflow" in text:
    print("already present")
elif needle not in text:
    raise SystemExit("qqbot location not found")
else:
    p.write_text(text.replace(needle, insert, 1), encoding="utf-8")
    print("nginx workflow redirect added")
