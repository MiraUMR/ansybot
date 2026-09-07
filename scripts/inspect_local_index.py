import re
from pathlib import Path

root = Path(r"E:\qq_bot\web")
for p in list(root.rglob("*.js")) + list(root.rglob("*.html")) + list(root.rglob("*.css")):
    d = p.read_text(encoding="utf-8", errors="replace")
    hits = []
    if "history:Ny" in d:
        hits.append(re.findall(r"history:Ny\([^)]*\)", d))
    if "/backend-api" in d:
        hits.append(("backend", d.count("/backend-api")))
    if "/assets/" in d:
        hits.append(("assets", d.count("/assets/")))
    if 'Ql="' in d:
        hits.append(re.findall(r'Ql="[^"]+"', d))
    if hits:
        print(p.name, hits)
