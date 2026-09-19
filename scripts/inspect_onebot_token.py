from pathlib import Path

root = Path("/usr/local/lib/python3.11/site-packages")
hits = list(root.glob("**/im_onebot*/**/*.py")) + list(root.glob("**/onebot*/**/*.py"))
print("count", len(hits))
for p in hits[:40]:
    print(p)
for p in hits:
    try:
        t = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    if "access_token" in t or "Authorization" in t:
        print("====", p)
        for i, line in enumerate(t.splitlines(), 1):
            if "access_token" in line or "Authorization" in line:
                print(f"{i}:{line[:180]}")
