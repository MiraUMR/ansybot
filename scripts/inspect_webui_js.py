from pathlib import Path
t = Path("/opt/kirara-ai/webui/assets/index.js").read_text(encoding="utf-8", errors="replace")
html = Path("/opt/kirara-ai/webui/index.html").read_text(encoding="utf-8", errors="replace")
print("a2", 'return"/qqbot/"+e' in t)
print("a2 leftover", 'return"/"+e' in t)
print("hist", 'Ny("/qqbot/")' in t)
print("query on entry", "?v=" in html)
print("html:")
print(html)
