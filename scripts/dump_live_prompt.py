import yaml
from pathlib import Path

p = Path("/opt/kirara-ai/data/workflows/chat/normal.yaml")
d = yaml.safe_load(p.read_text(encoding="utf-8"))
sp = next(b for b in d["blocks"] if b["name"] == "system_prompt")
Path("/tmp/live_system_prompt.txt").write_text(sp["params"]["text"], encoding="utf-8")
print("len", len(sp["params"]["text"]))
print("blocks", [b["name"] for b in d["blocks"]])
