from pathlib import Path

p = Path("/opt/kirara-ai/webui/assets/index.js")
t = p.read_text(encoding="utf-8", errors="replace")
i = t.find('label:()=>"控制台"')
if i < 0:
    i = t.find("key:\"guide\"")
print("menu idx", i)
print(t[i : i + 900])
print("==== click handler ====")
j = t.find("r.push(`/${a}`)")
print("push idx", j)
print(t[max(0, j - 200) : j + 250])
print("==== case workflow ====")
k = t.find('case"workflow":return')
print(t[k : k + 500] if k >= 0 else "missing")
