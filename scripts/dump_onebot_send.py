#!/usr/bin/env python3
from pathlib import Path

root = Path("/usr/local/lib/python3.11/site-packages/im_onebot_adapters")
print("files:", sorted(p.name for p in root.glob("*.py")))
for path in sorted(root.rglob("*.py")):
    text = path.read_text(encoding="utf-8")
    if "send_message" in text or "ChatSender" in text:
        print("====", path, "====")
        print(text)
        print()
