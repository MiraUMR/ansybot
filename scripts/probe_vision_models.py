#!/usr/bin/env python3
"""Probe DashScope VL model IDs without printing secrets."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

def _png32() -> str:
    import base64
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    w = h = 32
    raw = b""
    for y in range(h):
        raw += b"\x00"
        for x in range(w):
            raw += bytes((220, 40, 40, 255) if (x // 8 + y // 8) % 2 else (40, 80, 200, 255))
    return base64.b64encode(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    ).decode()


TINY_PNG = _png32()


def load_backends(path: str = "/opt/kirara-ai/data/config.yaml"):
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out = []
    for b in data.get("llms", {}).get("api_backends", []) or []:
        cfg = b.get("config") or {}
        key = (cfg.get("api_key") or "").strip()
        base = (cfg.get("api_base") or "").rstrip("/")
        models = []
        for m in b.get("models") or []:
            if isinstance(m, str):
                models.append(m)
            elif isinstance(m, dict):
                models.append(str(m.get("id") or m.get("name") or ""))
        out.append(
            {
                "name": b.get("name"),
                "enable": b.get("enable", True),
                "adapter": b.get("adapter"),
                "base": base,
                "key": key,
                "models": models,
            }
        )
    return out


def http_json(url: str, key: str, payload=None, timeout=40):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload else "GET")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()[:500]
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def vision_post(base: str, key: str, model: str):
    url = f"{base}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{TINY_PNG}"}},
                    {"type": "text", "text": "图里是什么，四个字以内"},
                ],
            }
        ],
        "max_tokens": 64,
        "enable_thinking": False,
        "thinking_budget": 16,
    }
    status, data = http_json(url, key, payload)
    if isinstance(data, dict):
        msg = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        err = data.get("error") or {}
        if err:
            return f"HTTP {status} err={err.get('code') or err.get('message')}"
        return f"HTTP {status} ok content={msg[:40]!r}"
    return f"HTTP {status} {str(data)[:220]}"


def main():
    backends = load_backends()
    if not backends:
        raise SystemExit("no llm backends")
    for b in backends:
        print(
            "backend",
            b["name"],
            "enable",
            b["enable"],
            "adapter",
            b["adapter"],
            "base",
            b["base"],
            "key_len",
            len(b["key"] or ""),
            "registered",
            len(b["models"]),
        )
        vl_reg = [m for m in b["models"] if any(x in m.lower() for x in ("-vl", "vl-", "vision"))]
        print(" registered_all", b["models"])
        print(" registered_vl", vl_reg[:30], "count", len(vl_reg))
        if not b["enable"] or not b["key"] or not b["base"]:
            continue
        if b["name"] != "阿里":
            print(" skip probe", b["name"])
            continue
        status, data = http_json(f"{b['base']}/models", b["key"])
        listed = []
        if isinstance(data, dict):
            listed = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict)]
            print(" listed_total", len(listed))
            print(" listed_all", listed)
            vl_list = [
                m
                for m in listed
                if any(x in (m or "").lower() for x in ("-vl", "vl-", "vision", "qvq", "4v", "omni"))
            ]
            print(" listed_vl", vl_list[:50], "count", len(vl_list))
        else:
            print(" list_models", status, str(data)[:300])

        if b["name"] == "ds":
            print(" skip probe ds")
            continue
        probes = list(listed or [])
        for extra in vl_reg:
            raw = extra.split("/", 1)[-1]
            if raw not in probes:
                probes.append(raw)
        print(" ==== probe", b["name"], "====")
        for model in probes:
            print(" ", model, vision_post(b["base"], b["key"], model))


if __name__ == "__main__":
    main()
