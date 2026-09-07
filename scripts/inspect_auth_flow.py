from pathlib import Path
import re

d = Path("/opt/kirara-ai/webui/assets/index.js").read_text(encoding="utf-8", errors="replace")

print("=== 401 interceptor ===")
i = d.find('push("/login")')
print(d[max(0, i-250): i+80])

print("\n=== Authorization / token ===")
for m in re.finditer(r".{40}(Authorization|localStorage.getItem\(\"token\"|Bearer).{60}", d):
    print(m.group(0)[:120])
    if m.start() > 0:
        break

# more token windows
idx = 0
n = 0
while n < 8:
    i = d.find('localStorage.getItem("token"', idx)
    if i < 0:
        break
    print("token get", d[i-80:i+120])
    idx = i + 1
    n += 1

print("\n=== beforeEach / requiresAuth ===")
i = d.find("requiresAuth")
print(d[max(0, i-200): i+400] if i >= 0 else "none")

print("\n=== websocket / EventSource ===")
for needle in ["WebSocket", "EventSource", "/backend-api", "system/status"]:
    print(needle, d.count(needle))

i = d.find("system/status")
print("status ctx", d[max(0, i-80): i+80] if i >= 0 else "no")

print("\n=== createWebHistory Ny ===")
i = d.find("history:Ny")
print(d[i-50:i+80])
# Ny definition
i = d.find("function Ny(")
print("function Ny", i)
i = d.find(",Ny=function")
print(",Ny=function", i)
if i < 0:
    i = d.find("Ny=function")
print("Ny=function", i)
if i >= 0:
    print(d[i:i+500])
