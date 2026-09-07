from pathlib import Path
import re

root = Path("/opt/kirara-ai/webui/assets")
print("=== leftover /assets/ without /qqbot ===")
for p in sorted(root.glob("*.js")) + sorted(root.glob("*.css")):
    t = p.read_text(encoding="utf-8", errors="replace")
    leftover = []
    start = 0
    while True:
        i = t.find("/assets/", start)
        if i < 0:
            break
        prefix = t[max(0, i-6):i]
        if "/qqbot" not in prefix:
            leftover.append(repr(t[max(0, i-30):i+50]))
        start = i + 1
    if leftover:
        print(p.name, "count", len(leftover))
        for s in leftover[:6]:
            print(" ", s)

print("\n=== a2 helpers ===")
idx = (root / "index.js").read_text(encoding="utf-8", errors="replace")
print("index a2", re.findall(r"\w+=function\(e\)\{return\"[^\"]+\"\+e\}", idx))
for p in root.glob("*.js"):
    t = p.read_text(encoding="utf-8", errors="replace")
    if "return\"/\"+e" in t or "return\"/qqbot/\"+e" in t:
        print(p.name, "has a2-like")

print("\n=== push after login in LoginView ===")
lv = (root / "LoginView.js").read_text(encoding="utf-8", errors="replace")
print(re.findall(r"push\(\"[^\"]*\"\)", lv))
