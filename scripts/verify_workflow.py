import yaml
from pathlib import Path

d = yaml.safe_load(Path("/opt/kirara-ai/data/workflows/chat/normal.yaml").read_text(encoding="utf-8"))
prompt = next(b["params"]["text"] for b in d["blocks"] if b["name"] == "system_prompt")
print("name", d["name"])
print("prompt_len", len(prompt))
print("soyo", "长崎素世" in prompt)
print("lesbian", "女同性恋" in prompt)
print("age18", "18 岁" in prompt)
