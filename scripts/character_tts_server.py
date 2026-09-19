#!/usr/bin/env python3
"""Character TTS sidecar: edge-tts -> optional RVC -> wav.

Speakers and weights live in /data/tts (mounted from data/tts).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("character-tts")

TTS_ROOT = Path(os.environ.get("TTS_ROOT", "/data/tts"))
DEVICE = os.environ.get("TTS_DEVICE", "cpu:0")
HOST = os.environ.get("TTS_HOST", "0.0.0.0")
PORT = int(os.environ.get("TTS_PORT", "8020"))

_rvc = None
_rvc_lock = threading.Lock()
_current_speaker = ""
_speakers: Dict[str, Dict[str, Any]] = {}
_rvc_ok = False
_rvc_error = ""


def _load_speakers() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    folder = TTS_ROOT / "speakers"
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sid = str(data.get("id") or path.stem).strip()
        if sid:
            out[sid] = data
    return out


def _abs(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else (TTS_ROOT / p)


def _init_rvc() -> None:
    global _rvc, _rvc_ok, _rvc_error
    try:
        from rvc_python.infer import RVCInference

        models_dir = str(TTS_ROOT / "models")
        Path(models_dir).mkdir(parents=True, exist_ok=True)
        try:
            _rvc = RVCInference(models_dir=models_dir, device=DEVICE, version="v2")
        except TypeError:
            _rvc = RVCInference(models_dir=models_dir, device=DEVICE)
        _rvc_ok = True
        log.info("RVC ready device=%s models_dir=%s", DEVICE, models_dir)
    except Exception as exc:
        _rvc = None
        _rvc_ok = False
        _rvc_error = str(exc)
        log.warning("RVC unavailable, edge-tts only: %s", exc)


def _ensure_speaker(speaker: str) -> None:
    global _current_speaker
    if not _rvc:
        raise RuntimeError("rvc not loaded")
    cfg = _speakers[speaker]
    pth = _abs(str(cfg.get("model") or ""))
    if not pth.is_file():
        raise FileNotFoundError(f"missing model {pth}")
    index = _abs(str(cfg.get("index") or ""))
    index_path = str(index) if index.is_file() else ""
    version = str(cfg.get("version") or "v2")
    if _current_speaker == speaker:
        return
    _rvc.load_model(str(pth), version=version, index_path=index_path)
    _rvc.set_params(
        f0up_key=int(cfg.get("f0up_key") or 0),
        f0method="harvest",
        index_rate=0.5 if index_path else 0.0,
        protect=0.33,
    )
    _current_speaker = speaker
    log.info("loaded speaker=%s index=%s", speaker, bool(index_path))


async def _edge_to_mp3(text: str, cfg: Dict[str, Any], dest: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(
        text,
        str(cfg.get("edge_voice") or "zh-CN-XiaoxiaoNeural"),
        rate=str(cfg.get("edge_rate") or "+0%"),
        pitch=str(cfg.get("edge_pitch") or "+0Hz"),
    )
    await communicate.save(str(dest))


def _ffmpeg_wav(src: Path, dest: Path, sr: int = 40000) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-ac", "1", "-ar", str(sr),
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-400:] or "ffmpeg failed")


def synthesize(speaker: str, text: str) -> tuple[bytes, str, str]:
    """Return (wav_bytes, backend, content_type)."""
    cfg = _speakers.get(speaker)
    if not cfg:
        raise KeyError(f"unknown speaker {speaker}")
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text")

    with tempfile.TemporaryDirectory(prefix="tts-") as tmp:
        tmp_path = Path(tmp)
        mp3 = tmp_path / "in.mp3"
        wav_in = tmp_path / "in.wav"
        wav_out = tmp_path / "out.wav"
        asyncio.run(_edge_to_mp3(text, cfg, mp3))
        _ffmpeg_wav(mp3, wav_in)
        backend = "edge-tts"
        if _rvc_ok:
            with _rvc_lock:
                _ensure_speaker(speaker)
                _rvc.infer_file(str(wav_in), str(wav_out))
            backend = "edge-tts+rvc"
            data = wav_out.read_bytes()
        else:
            data = wav_in.read_bytes()
        return data, backend, "audio/wav"


def _write_sample(speaker: str) -> Optional[Path]:
    cfg = _speakers.get(speaker) or {}
    prompt_rel = str(cfg.get("prompt_file") or f"prompts/{speaker}.txt")
    prompt_path = _abs(prompt_rel)
    line = "嗯。"
    if prompt_path.is_file():
        for raw in prompt_path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                line = raw.strip()
                break
    audio, backend, _ = synthesize(speaker, line)
    out = TTS_ROOT / "samples" / f"{speaker}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    log.info("sample %s backend=%s bytes=%s line=%s", speaker, backend, len(audio), line)
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s " + fmt, self.address_string(), *args)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0].rstrip("/") == "/health":
            self._json(
                200,
                {
                    "ok": True,
                    "rvc": _rvc_ok,
                    "rvc_error": _rvc_error,
                    "speakers": sorted(_speakers),
                    "loaded": _current_speaker,
                    "device": DEVICE,
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return
        if path == "/sample":
            speaker = str(payload.get("character") or payload.get("speaker") or "").strip()
            if speaker not in _speakers:
                self._json(400, {"error": "unknown speaker", "speakers": sorted(_speakers)})
                return
            try:
                out = _write_sample(speaker)
            except Exception as exc:
                log.exception("sample failed")
                self._json(500, {"error": str(exc)})
                return
            self._json(200, {"ok": True, "path": str(out)})
            return
        if path != "/tts":
            self._json(404, {"error": "not found"})
            return
        speaker = str(payload.get("character") or payload.get("speaker") or "").strip()
        text = str(payload.get("text") or "")
        if speaker not in _speakers:
            self._json(400, {"error": "unknown speaker", "speakers": sorted(_speakers)})
            return
        try:
            audio, backend, ctype = synthesize(speaker, text)
        except Exception as exc:
            log.exception("tts failed")
            self._json(500, {"error": str(exc)})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("X-TTS-Backend", backend)
        self.send_header("X-TTS-Speaker", speaker)
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)


def main() -> None:
    global _speakers
    _speakers = _load_speakers()
    log.info("speakers=%s root=%s", sorted(_speakers), TTS_ROOT)
    _init_rvc()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("listening on %s:%s", HOST, PORT)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
