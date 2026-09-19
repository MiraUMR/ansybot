#!/usr/bin/env python3
from pathlib import Path

p = Path("/opt/kirara-ai/data/config.yaml")
lines = p.read_text(encoding="utf-8").splitlines()
start, end = 24, min(80, len(lines))
for i, line in enumerate(lines[start:end], start + 1):
    low = line.lower()
    if "api_key" in low:
        raw = line.split(":", 1)[1] if ":" in line else ""
        k = raw.strip().strip('"').strip("'")
        print("%d: %s -> masked len=%s prefix=%r suffix=%r quoted_raw=%r" % (
            i, line[: line.lower().find("api_key")+7], len(k), k[:12] if k else "", k[-8:] if k else "", raw[:20]
        ))
    else:
        print("%d: %s" % (i, line.rstrip()))

print("--- total lines", len(lines))
print("--- search token-plan / dashscope / sk-")
for i, line in enumerate(lines, 1):
    if any(s in line.lower() for s in ("token-plan", "dashscope", "sk-", "maas.aliyuncs")):
        if "sk-" in line:
            idx = line.find("sk-")
            k = line[idx:].strip().strip('"').strip("'")
            print("%d: ...%s KEY len=%s prefix=%s" % (i, line[:idx], len(k), k[:10]))
        else:
            print("%d: %s" % (i, line.rstrip()))
