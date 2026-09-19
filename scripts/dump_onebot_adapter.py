from pathlib import Path
p = Path("/usr/local/lib/python3.11/site-packages/im_onebot_adapters/adapter.py")
print(p.read_text(encoding="utf-8"))
