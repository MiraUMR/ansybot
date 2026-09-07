#!/usr/bin/env python3
import yaml
p = "/opt/kirara-ai/data/workflows/chat/normal.yaml"
data = yaml.safe_load(open(p, encoding="utf-8"))
print("==== send / converter ====")
for b in data["blocks"]:
    if b.get("type") in ("internal:send_message", "internal:chat_response_converter"):
        targets = [c.get("target") for c in (b.get("connected_to") or [])]
        print(b.get("name"), b.get("type"), "params=", b.get("params"), "targets=", targets)
