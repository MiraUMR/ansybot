from pathlib import Path
import re

idx = Path("/opt/kirara-ai/webui/assets/index.js").read_text(encoding="utf-8", errors="replace")

# history constructor
m = re.search(r".{200}history:Ny\([^)]*\)(.{200})", idx)
print("=== history context ===")
print(m.group(0) if m else "missing")

# define Ny
print("\n=== Ny function-ish ===")
for pat in [r"function Ny\(", r"Ny=function", r"const Ny=", r"Ny=e=>", r",Ny=", r"Ny=t=>"]:
    i = idx.find(pat.replace("\\", "") if False else pat)
print("Ny= count", idx.count("Ny="), "function Ny", idx.count("function Ny"))

# find Ny assignment near createWebHistory semantics: pushState
i = idx.find("history:Ny")
# search backwards for Ny=
chunk = idx[max(0, i-5000):i]
assigns = [m.start() for m in re.finditer(r"\bNy=", chunk)]
print("Ny= in preceding 5k", len(assigns))
if assigns:
    s = assigns[-1]
    print(chunk[s:s+400])

print("\n=== login name / beforeEach ===")
for needle in ['name:"login"', "beforeEach", "requiresAuth", "password.hash", "check-first"]:
    print(needle, idx.count(needle))

# print windows around name:"login"
for m in re.finditer(r'name:"login".{0,80}', idx):
    print("login route", m.group(0))

for m in re.finditer(r'requiresAuth.{0,120}', idx):
    print("auth", m.group(0)[:120])
    break

# router routes snippet
m = re.search(r"path:\"/\",component:.{0,500}", idx)
print("\n=== root route ===")
print(m.group(0) if m else "no")
