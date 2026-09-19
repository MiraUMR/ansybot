#!/usr/bin/env python3
"""Forward a unix socket (and optional docker-bridge TCP) to 127.0.0.1:8021."""
from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

PORT = 8021
DEST = ("127.0.0.1", PORT)
SOCK_PATH = os.environ.get("GPTSOVITS_SOCK") or "/data/tts/gptsovits.sock"
ENABLE_TCP = (os.environ.get("GPTSOVITS_GW_TCP") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def list_bind_ips() -> list[str]:
    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            ip = info[4][0]
            if ip.startswith(("172.", "10.", "192.168.")) and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    for guess in ("172.19.0.1", "172.18.0.1", "172.17.0.1"):
        if guess not in ips:
            ips.append(guess)
    return ips


def pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def handle(client: socket.socket) -> None:
    try:
        upstream = socket.create_connection(DEST, timeout=10)
    except OSError:
        client.close()
        return
    threading.Thread(target=pump, args=(client, upstream), daemon=True).start()
    pump(upstream, client)
    client.close()
    upstream.close()


def serve_tcp(bind_ip: str) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind_ip, PORT))
    sock.listen(128)
    print(f"gptsovits-gw listening {bind_ip}:{PORT} -> {DEST[0]}:{DEST[1]}", flush=True)
    while True:
        client, _ = sock.accept()
        threading.Thread(target=handle, args=(client,), daemon=True).start()


def serve_unix(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(path)
    os.chmod(path, 0o666)
    sock.listen(128)
    print(f"gptsovits-gw listening unix:{path} -> {DEST[0]}:{DEST[1]}", flush=True)
    while True:
        client, _ = sock.accept()
        threading.Thread(target=handle, args=(client,), daemon=True).start()


def main() -> None:
    started = 0
    unix_sock: socket.socket | None = None
    try:
        path = SOCK_PATH
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        unix_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_sock.bind(path)
        os.chmod(path, 0o666)
        unix_sock.listen(128)
        print(f"gptsovits-gw listening unix:{path} -> {DEST[0]}:{DEST[1]}", flush=True)

        def accept_unix() -> None:
            while True:
                client, _ = unix_sock.accept()
                threading.Thread(target=handle, args=(client,), daemon=True).start()

        threading.Thread(target=accept_unix, daemon=True).start()
        started += 1
    except OSError as exc:
        print(f"unix skip {SOCK_PATH}: {exc}", flush=True)
    if ENABLE_TCP:
        for ip in list_bind_ips():
            try:
                threading.Thread(target=serve_tcp, args=(ip,), daemon=True).start()
                started += 1
            except OSError as exc:
                print(f"tcp skip {ip}: {exc}", flush=True)
    if not started:
        raise SystemExit("no listeners")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
