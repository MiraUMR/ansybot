#!/usr/bin/env python3
import json
from pathlib import Path
p = Path("/opt/kirara-ai/data/config.yaml")
text = p.read_text(encoding="utf-8")
print("FILE_LEN", len(text))
# print llm section only with key redacted via naive line filter
for i, line in enumerate(text.splitlines(), 1):
    if "llms" in line or "api_" in line or "adapter:" in line or "models:" in line or "enable:" in line or "name:" in line or "defaults" in line or "llm_model" in line or "deepseek" in line or "dashscope" in line:
        if "api_key" in line or "app_secret" in line or "secret_key" in line:
            print(f"{i}: {line.split(':')[0]}: ***")
        else:
            print(f"{i}: {line}")
