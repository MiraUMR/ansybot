#!/usr/bin/env python3
"""Probe SiliconFlow TTS: which host/params actually return audio."""
import json
import os
import sys
import urllib.error
import urllib.request

KEY = os.environ["SF_KEY"]
HOSTS = ["https://api.siliconflow.cn", "https://api.siliconflow.com"]
MODEL = "FunAudioLLM/CosyVoice2-0.5B"


def call(host: str, payload: dict) -> str:
    req = urllib.request.Request(
        host + "/v1/audio/speech",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            return f"OK {resp.status} ctype={resp.headers.get('Content-Type')} bytes={len(data)}"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"
    except Exception as exc:
        return f"ERR {exc}"


cases = {
    "minimal": {"model": MODEL, "voice": f"{MODEL}:bella", "input": "测试一下声音。"},
    "with_format": {"model": MODEL, "voice": f"{MODEL}:bella", "input": "测试一下声音。", "response_format": "mp3"},
    "no_punct": {"model": MODEL, "voice": f"{MODEL}:bella", "input": "测试一下声音"},
    "anna": {"model": MODEL, "voice": f"{MODEL}:anna", "input": "测试一下声音。", "response_format": "mp3"},
    "wav": {"model": MODEL, "voice": f"{MODEL}:diana", "input": "测试一下声音。", "response_format": "wav"},
}

for host in HOSTS:
    for name, payload in cases.items():
        print(f"{host} [{name}] -> {call(host, payload)}")
        sys.stdout.flush()
