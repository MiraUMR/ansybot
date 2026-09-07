"""Copy Kirara reverse-WS settings into every NapCat onebot11_*.json.

NapCat writes a per-account file after the first QR login. Run this on the
server if Kirara logs show the OneBot adapter is up but NapCat never connects.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "napcat" / "config"
TEMPLATE = CONFIG_DIR / "onebot11.json"


def main() -> int:
    if not TEMPLATE.is_file():
        print(f"missing template: {TEMPLATE}", file=sys.stderr)
        return 1

    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    clients = template.get("network", {}).get("websocketClients", [])
    if not clients:
        print("template has no websocketClients", file=sys.stderr)
        return 1

    kirara = next((c for c in clients if c.get("name") == "kirara"), clients[0])
    updated = 0
    for path in sorted(CONFIG_DIR.glob("onebot11*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        network = data.setdefault("network", {})
        existing = network.setdefault("websocketClients", [])
        others = [c for c in existing if c.get("name") != "kirara"]
        network["websocketClients"] = [kirara, *others]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated += 1
        print(f"updated {path.name}")

    print(f"done, {updated} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
