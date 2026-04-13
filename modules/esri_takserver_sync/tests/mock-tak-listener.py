#!/usr/bin/env python3
"""
Mock TAK Server TCP listener
Accepts connections on a configurable port, prints every CoT XML event received.
Use this to verify feature-layer-to-cot.py output without a real TAK Server.

Usage (plain TCP — matches tak_server.tls = false in config):
    python mock-tak-listener.py

Usage (TLS — matches tak_server.tls = true):
    python mock-tak-listener.py --tls --cert server-cert.pem --key server-key.pem

Generate a throwaway server cert for TLS testing:
    openssl req -x509 -newkey rsa:2048 -keyout server-key.pem -out server-cert.pem \
            -days 30 -nodes -subj "/CN=localhost"
"""

import argparse
import signal
import socket
import ssl
import sys
import threading
from datetime import datetime, timezone
import xml.etree.ElementTree as ET


# ── CoT pretty-printer ────────────────────────────────────────────────────────

def parse_cot(raw: str) -> dict | None:
    """Extract key fields from a CoT XML string. Returns None if unparseable."""
    try:
        root = ET.fromstring(raw.strip())
        point = root.find("point")
        detail = root.find("detail")
        contact = detail.find("contact") if detail is not None else None
        return {
            "uid":      root.attrib.get("uid", "?"),
            "type":     root.attrib.get("type", "?"),
            "time":     root.attrib.get("time", "?"),
            "stale":    root.attrib.get("stale", "?"),
            "lat":      point.attrib.get("lat", "?") if point is not None else "?",
            "lon":      point.attrib.get("lon", "?") if point is not None else "?",
            "hae":      point.attrib.get("hae", "0") if point is not None else "0",
            "callsign": contact.attrib.get("callsign", "?") if contact is not None else "?",
        }
    except ET.ParseError:
        return None


def print_cot(raw: str, addr: tuple):
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    parsed = parse_cot(raw)
    if parsed:
        print(
            f"[{now}] {addr[0]}:{addr[1]}  "
            f"uid={parsed['uid']}  type={parsed['type']}  "
            f"cs={parsed['callsign']}  "
            f"lat={parsed['lat']} lon={parsed['lon']} hae={parsed['hae']}"
        )
    else:
        # Not valid XML — print raw (truncated)
        preview = raw.strip().replace("\n", " ")[:120]
        print(f"[{now}] {addr[0]}:{addr[1]}  RAW: {preview}")


# ── Client handler ─────────────────────────────────────────────────────────────

def handle_client(conn: socket.socket, addr: tuple, verbose: bool):
    print(f"[+] Connected: {addr[0]}:{addr[1]}")
    buf = ""
    try:
        while True:
            chunk = conn.recv(4096).decode("utf-8", errors="replace")
            if not chunk:
                break
            buf += chunk
            # CoT events are newline-delimited in streaming TCP mode
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if line:
                    print_cot(line, addr)
                    if verbose:
                        print(f"    RAW: {line}\n")
    except (ConnectionResetError, ssl.SSLError):
        pass
    finally:
        conn.close()
        print(f"[-] Disconnected: {addr[0]}:{addr[1]}")


# ── Server ────────────────────────────────────────────────────────────────────

_running = True

def _shutdown(sig, frame):
    global _running
    print("\n[*] Shutting down…")
    _running = False
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)


def main():
    parser = argparse.ArgumentParser(description="Mock TAK Server TCP CoT listener")
    parser.add_argument("--host",    default="0.0.0.0",        help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port",    type=int, default=8089,   help="Listen port (default: 8089)")
    parser.add_argument("--tls",     action="store_true",      help="Enable TLS")
    parser.add_argument("--cert",    default="server-cert.pem",help="Server TLS cert (PEM)")
    parser.add_argument("--key",     default="server-key.pem", help="Server TLS key (PEM)")
    parser.add_argument("--verbose", action="store_true",      help="Also print raw XML")
    args = parser.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(10)
    srv.settimeout(1.0)

    if args.tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)
        ctx.verify_mode = ssl.CERT_NONE     # don't require client cert for mock testing
        srv = ctx.wrap_socket(srv, server_side=True)
        print(f"[*] Mock TAK Server listening on {args.host}:{args.port} (TLS)")
    else:
        print(f"[*] Mock TAK Server listening on {args.host}:{args.port} (plain TCP)")

    print("[*] Waiting for connections… (Ctrl-C to stop)\n")

    cot_count = 0
    while _running:
        try:
            conn, addr = srv.accept()
        except (socket.timeout, ssl.SSLError, OSError):
            continue

        t = threading.Thread(
            target=handle_client, args=(conn, addr, args.verbose), daemon=True
        )
        t.start()


if __name__ == "__main__":
    main()
