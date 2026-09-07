#!/usr/bin/env python3
"""Migrate flat world_state/*.yaml into anon/<group>.yaml (idempotent)."""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1] / "data" / "world_state"


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    anon = ROOT / "anon"
    anon.mkdir(parents=True, exist_ok=True)
    for path in sorted(ROOT.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        dest = anon / path.name
        if dest.exists():
            print("skip existing", dest)
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("group_id", path.stem)
        data.setdefault("character", "anon")
        dest.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        bak = path.with_suffix(".yaml.legacy")
        shutil.move(str(path), str(bak))
        print("migrated", path.name, "->", dest.relative_to(ROOT), "bak", bak.name)


if __name__ == "__main__":
    main()
