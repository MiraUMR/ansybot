from pathlib import Path

root = Path(r"E:\qq_bot\web")
needles = [
    "工作流",
    "调度规则",
    "插件",
    "媒体",
    "控制台",
    "模型管理",
    'path:"/workflow"',
    "聊天平台",
    "key:\"workflow\"",
    "label:\"工作流\"",
]
for p in root.rglob("*.js"):
    t = p.read_text(encoding="utf-8", errors="replace")
    hits = [n for n in needles if n in t]
    if not hits:
        continue
    print("FILE", p.name, hits)
    for n in hits:
        i = t.find(n)
        snippet = t[max(0, i - 100) : i + 140].replace("\n", " ")
        print(" ", n, "=>", snippet)
        print()
