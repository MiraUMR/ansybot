#!/usr/bin/env python3
"""Download Anon / Soyo RVC v2 weights from HuggingFace into data/tts/models/."""
from __future__ import annotations

import argparse
import os
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TTS_ROOT = ROOT / "data" / "tts"
HF = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
REPO = "Wanlau/RVC_BanGDream"

FILES = {
    "anon": [
        ("Anon_v2/Anon_v2.pth", "models/anon/Anon_v2.pth"),
        (
            "Anon_v2/added_IVF4511_Flat_nprobe_1_Anon_v2_v2.index",
            "models/anon/added_IVF4511_Flat_nprobe_1_Anon_v2_v2.index",
        ),
    ],
    "soyo": [
        ("Soyo1_v2/Soyo1_v2.pth", "models/soyo/Soyo1_v2.pth"),
        (
            "Soyo1_v2/added_IVF2023_Flat_nprobe_1_Soyo1_v2_v2.index",
            "models/soyo/added_IVF2023_Flat_nprobe_1_Soyo1_v2_v2.index",
        ),
    ],
}


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"GET {url}")
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "qq-bot-tts/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        with tmp.open("wb") as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if total:
                    pct = 100.0 * got / total
                    print(f"\r  {dest.name}: {got / 1e6:.1f}/{total / 1e6:.1f} MB ({pct:.0f}%)", end="")
        print()
    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-index", action="store_true", help="also download faiss index (better, ~800MB)")
    parser.add_argument("--character", choices=("anon", "soyo", "all"), default="all")
    args = parser.parse_args()
    names = ("anon", "soyo") if args.character == "all" else (args.character,)
    for name in names:
        entries = FILES[name]
        if not args.with_index:
            entries = [item for item in entries if not item[1].endswith(".index")]
        for remote, local in entries:
            dest = TTS_ROOT / local
            if dest.exists() and dest.stat().st_size > 1_000_000:
                print(f"skip existing {dest}")
                continue
            url = f"{HF}/{REPO}/resolve/main/{remote}?download=true"
            try:
                _download(url, dest)
            except Exception as exc:
                print(f"FAILED {remote}: {exc}", file=sys.stderr)
                if dest.with_suffix(dest.suffix + ".part").exists():
                    dest.with_suffix(dest.suffix + ".part").unlink()
                return 1
            print(f"saved {dest} ({dest.stat().st_size} bytes)")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
