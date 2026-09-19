#!/usr/bin/env python3
"""Install CowAgent HTTPS console on ansy.love:8444, same host as QQ /qqbot/."""
from pathlib import Path
import shutil
import subprocess
import sys

SRC = Path("/opt/kirara-ai/scripts/momo.nginx.conf")
DST = Path("/www/server/panel/vhost/nginx/momo.ansy.love.conf")
MAIN = Path("/www/server/panel/vhost/nginx/ansy.love.conf")

REDIRECT = """
    location = /momo {
        return 302 https://$host:8444/;
    }
    location = /momo/ {
        return 302 https://$host:8444/;
    }
"""


def main() -> int:
    if not SRC.exists():
        print("missing", SRC, file=sys.stderr)
        return 1
    shutil.copyfile(SRC, DST)
    print("wrote", DST)

    text = MAIN.read_text(encoding="utf-8")
    if "return 302 https://$host:8444/" in text:
        print("ansy.love.conf already redirects /momo")
    else:
        needle = "    location = /qqbot {\n        return 302 /qqbot/;\n    }\n"
        if needle not in text:
            print("qqbot anchor not found", file=sys.stderr)
            return 1
        MAIN.write_text(text.replace(needle, needle + REDIRECT, 1), encoding="utf-8")
        print("patched", MAIN, "with /momo redirect")

    t = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    sys.stderr.write(t.stderr)
    sys.stdout.write(t.stdout)
    if t.returncode != 0:
        return t.returncode
    subprocess.run(["nginx", "-s", "reload"], check=True)
    print("nginx reloaded")

    subprocess.run(["ufw", "allow", "8444/tcp"], check=False)
    subprocess.run(
        ["iptables", "-I", "INPUT", "-p", "tcp", "--dport", "8444", "-j", "ACCEPT"],
        check=False,
    )
    print("firewall 8444 opened")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
