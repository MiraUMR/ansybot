import yaml
from pathlib import Path

p = Path("/opt/kirara-ai/data/workflows/chat/normal.yaml")
d = yaml.safe_load(p.read_text(encoding="utf-8"))
sp = next(b for b in d["blocks"] if b["name"] == "system_prompt")
text = sp["params"]["text"]
print("=== HEAD 1200 ===")
print(text[:1200])
print("=== 单箭头 count ===", text.count("单箭头"), text.count("暗恋"), text.count("告白"))
