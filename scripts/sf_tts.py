#!/usr/bin/env python3
"""SiliconFlow CosyVoice2 helper: build reference clips, register voices, synthesize lines.

Key comes from SILICONFLOW_API_KEY (or SF_KEY). Voice URIs are written back into
data/tts/speakers/<id>.yaml so the runtime block can pick them up.

  python3 scripts/sf_tts.py gen-ref anon soyo      # synth reference clips
  python3 scripts/sf_tts.py upload-ref anon [file] # register trimmed clip as a voice
  python3 scripts/sf_tts.py say anon "文本" out.mp3
  python3 scripts/sf_tts.py list
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TTS_ROOT = ROOT / "data" / "tts"
BASE = os.environ.get("SILICONFLOW_BASE", "https://api.siliconflow.cn").rstrip("/")
MODEL = "FunAudioLLM/CosyVoice2-0.5B"


def _key() -> str:
    key = (os.environ.get("SILICONFLOW_API_KEY") or os.environ.get("SF_KEY") or "").strip()
    if not key:
        raise SystemExit("set SILICONFLOW_API_KEY")
    return key


def _post(path: str, payload: dict, want_audio: bool = False) -> bytes | dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{path} HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:400]}")
    if want_audio:
        return body
    return json.loads(body.decode("utf-8"))


def _speaker_path(sid: str) -> Path:
    return TTS_ROOT / "speakers" / f"{sid}.yaml"


def _speaker(sid: str) -> dict:
    path = _speaker_path(sid)
    if not path.exists():
        raise SystemExit(f"no speaker config: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save_speaker(sid: str, data: dict) -> None:
    _speaker_path(sid).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def synth(voice: str, text: str, speed: float = 1.0, gain: float = 0.0, fmt: str = "mp3") -> bytes:
    payload = {
        "model": MODEL,
        "voice": voice,
        "input": text,
        "response_format": fmt,
        "speed": speed,
        "gain": gain,
    }
    if fmt in ("wav", "pcm"):
        payload["sample_rate"] = 44100
    return _post("/v1/audio/speech", payload, want_audio=True)


def upload_voice(name: str, audio: bytes, text: str) -> str:
    b64 = "data:audio/mpeg;base64," + base64.b64encode(audio).decode("ascii")
    resp = _post(
        "/v1/uploads/audio/voice",
        {"model": MODEL, "customName": name, "audio": b64, "text": text},
    )
    uri = (resp or {}).get("uri")
    if not uri:
        raise SystemExit(f"upload failed: {resp}")
    return uri


def cmd_gen_ref(ids: list[str]) -> None:
    """Synthesize the reference clip only; trim it before upload-ref."""
    for sid in ids:
        cfg = _speaker(sid)
        ref_text = str(cfg.get("ref_text") or "").strip()
        instruct = str(cfg.get("ref_instruct") or "").strip()
        preset = str(cfg.get("preset_voice") or "diana").strip()
        if not ref_text:
            raise SystemExit(f"{sid}: ref_text missing in speaker yaml")
        prompt = f"{instruct}<|endofprompt|>{ref_text}" if instruct else ref_text
        audio = synth(
            f"{MODEL}:{preset}",
            prompt,
            speed=float(cfg.get("ref_speed") or 1.0),
            gain=float(cfg.get("ref_gain") or 0.0),
        )
        out = TTS_ROOT / "refs" / f"{sid}.mp3"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(audio)
        print(f"{sid}: reference {out} ({len(audio)} bytes, preset={preset})")


def cmd_upload_ref(sid: str, path: str | None = None) -> None:
    cfg = _speaker(sid)
    ref_text = str(cfg.get("ref_text") or "").strip()
    src = Path(path) if path else TTS_ROOT / "refs" / f"{sid}.mp3"
    audio = src.read_bytes()
    name = f"{sid}-{uuid.uuid4().hex[:8]}"
    uri = upload_voice(name, audio, ref_text)
    cfg["voice_uri"] = uri
    cfg["voice_name"] = name
    _save_speaker(sid, cfg)
    print(f"{sid}: voice uri {uri} (from {src}, {len(audio)} bytes)")


def cmd_say(sid: str, text: str, dest: str) -> None:
    cfg = _speaker(sid)
    voice = str(cfg.get("voice_uri") or "").strip()
    if not voice:
        preset = str(cfg.get("preset_voice") or "diana").strip()
        voice = f"{MODEL}:{preset}"
        print(f"[warn] {sid}: no voice_uri, falling back to preset {preset}")
    instruct = str(cfg.get("say_instruct") or "").strip()
    payload_text = f"{instruct}<|endofprompt|>{text}" if instruct else text
    audio = synth(
        voice,
        payload_text,
        speed=float(cfg.get("speed") or 1.0),
        gain=float(cfg.get("gain") or 0.0),
    )
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    print(f"{sid}: wrote {path} ({len(audio)} bytes) voice={voice}")


def cmd_list() -> None:
    req = urllib.request.Request(
        BASE + "/v1/audio/voice/list", headers={"Authorization": f"Bearer {_key()}"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        print(resp.read().decode("utf-8"))


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "gen-ref":
        cmd_gen_ref(sys.argv[2:] or ["anon", "soyo"])
    elif cmd == "upload-ref":
        cmd_upload_ref(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == "say":
        cmd_say(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "list":
        cmd_list()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
