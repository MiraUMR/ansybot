#!/bin/bash
ls -la /opt/kirara-ai/data/world_state/
echo "===="
python3 - <<'PY'
from pathlib import Path
root = Path("/opt/kirara-ai/data/world_state")
for path in sorted(root.glob("*.yaml")):
    if path.name.startswith("_"):
        continue
    print("---", path.name, "---")
    print(path.read_text(encoding="utf-8"))
    print()
PY
