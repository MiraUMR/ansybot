from pathlib import Path
import re

d = Path("/opt/kirara-ai/webui/assets/index.js").read_text(encoding="utf-8", errors="replace")

print("=== route paths ===")
for p in re.findall(r'path:"[^"]+"', d):
    if "path:" in p:
        print(p)

print("\n=== workflow route windows ===")
for m in re.finditer(r'path:"/workflow[^"]*"', d):
    print(d[m.start()-30:m.start()+220])
    print("---")

print("\n=== router-link / push workflow ===")
for pat in [r'push\("[^"]*workflow[^"]*"\)', r'to:"[^"]*workflow[^"]*"', r'name:"workflow[^"]*"']:
    print(pat, re.findall(pat, d)[:20])

print("\n=== Ny function start ===")
i = d.find("function Ny(")
print(d[i:i+600])
