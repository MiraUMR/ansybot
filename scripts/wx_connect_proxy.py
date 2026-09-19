#!/usr/bin/env python3
"""Minimal CONNECT proxy so WeChatPadPro's Go client can reach knowhub."""
import select
import socket
import threading
from socketserver import StreamRequestHandler, ThreadingTCPServer


class ConnectHandler(StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline().decode("iso-8859-1", "replace")
        parts = line.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            self.wfile.write(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
            return
        host, port = parts[1].rsplit(":", 1)
        while True:
            header = self.rfile.readline()
            if header in (b"\r\n", b"\n", b""):
                break
        try:
            dest = socket.create_connection((host, int(port)), timeout=20)
        except OSError:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            return
        self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        self.wfile.flush()
        sockets = [self.connection, dest]
        try:
            while True:
                readable, _, _ = select.select(sockets, [], [], 60)
                if not readable:
                    break
                for sock in readable:
                    other = dest if sock is self.connection else self.connection
                    data = sock.recv(65536)
                    if not data:
                        return
                    other.sendall(data)
        finally:
            dest.close()


if __name__ == "__main__":
    ThreadingTCPServer.allow_reuse_address = True
    server = ThreadingTCPServer(("0.0.0.0", 8888), ConnectHandler)
    server.serve_forever()
