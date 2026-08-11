"""Drive the dashboard's filters with real DOM events and report what happened.

Interaction cannot be verified by reading the code. This loads the built page in
headless Chrome over the DevTools protocol, dispatches genuine clicks, and reads
the resulting DOM state back.

    python tools/test_interaction.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9223


def _ws_send(ws, msg_id: int, method: str, params: dict | None = None):
    import struct
    payload = json.dumps({"id": msg_id, "method": method, "params": params or {}}).encode()
    header = bytearray([0x81])
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    mask = b"\x00\x00\x00\x00"
    ws.sendall(bytes(header) + mask + payload)


def _ws_recv(ws) -> dict | None:
    import struct
    hdr = ws.recv(2)
    if len(hdr) < 2:
        return None
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", ws.recv(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", ws.recv(8))[0]
    data = b""
    while len(data) < length:
        chunk = ws.recv(length - len(data))
        if not chunk:
            break
        data += chunk
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


def main() -> int:
    page = C.DASHBOARD
    if not page.exists():
        print(f"no dashboard at {page}")
        return 1

    profile = Path(__file__).resolve().parent.parent / "data" / "_chrome_probe"
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--disable-background-networking", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={profile}", page.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        target = None
        for _ in range(40):
            time.sleep(0.5)
            try:
                raw = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2).read()
                for t in json.loads(raw):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        target = t
                        break
                if target:
                    break
            except Exception:
                continue
        if not target:
            print("could not attach to Chrome")
            return 1

        import base64
        import os
        import socket
        from urllib.parse import urlparse

        u = urlparse(target["webSocketDebuggerUrl"])
        sock = socket.create_connection((u.hostname, u.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((
            f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += sock.recv(4096)

        msg_id = [0]

        def evaluate(expr: str):
            msg_id[0] += 1
            mine = msg_id[0]
            _ws_send(sock, mine, "Runtime.evaluate",
                     {"expression": expr, "returnByValue": True, "awaitPromise": True})
            for _ in range(200):
                m = _ws_recv(sock)
                if m and m.get("id") == mine:
                    return (m.get("result", {}).get("result", {}) or {}).get("value")
            return None

        time.sleep(1.5)
        checks, failures = [], []

        def check(label, got, want_fn, detail=""):
            ok = want_fn(got)
            checks.append((label, ok, got, detail))
            if not ok:
                failures.append(label)

        check("filter bar rendered",
              evaluate("!!document.querySelector('.filterbar')"), lambda v: v is True)
        check("day chips present",
              evaluate("document.querySelectorAll('.day-chip').length"), lambda v: (v or 0) >= 5)
        check("elements tagged with data-analyte",
              evaluate("document.querySelectorAll('[data-analyte]').length"),
              lambda v: (v or 0) >= 10)

        # Click day 1 and count what dims.
        evaluate("document.querySelector('.day-chip').click()")
        time.sleep(0.3)
        check("day click sets aria-pressed",
              evaluate("document.querySelector('.day-chip').getAttribute('aria-pressed')"),
              lambda v: v == "true")
        check("day click dims non-matching elements",
              evaluate("document.querySelectorAll('.dimmed').length"), lambda v: (v or 0) > 0)
        check("clear button appears",
              evaluate("!document.getElementById('f-clear').hidden"), lambda v: v is True)
        check("filter count announced",
              evaluate("document.getElementById('f-count').textContent"),
              lambda v: bool(v and "filter" in v))
        check("state written to the url",
              evaluate("location.hash"), lambda v: bool(v and "d=" in v))

        # Escape clears.
        evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        time.sleep(0.3)
        check("escape clears filters",
              evaluate("document.querySelectorAll('.dimmed').length"), lambda v: (v or 0) == 0)

        # Analyte click.
        evaluate("(document.querySelector('[data-analyte]')||{}).click&&"
                 "document.querySelector('[data-analyte]').click()")
        time.sleep(0.3)
        check("analyte click marks a selection",
              evaluate("document.querySelectorAll('.picked').length"), lambda v: (v or 0) >= 1)

        evaluate("document.getElementById('f-clear').click()")
        time.sleep(0.2)

        # Abnormal-only switch.
        evaluate("var c=document.getElementById('f-abnormal');c.checked=true;"
                 "c.dispatchEvent(new Event('change',{bubbles:true}))")
        time.sleep(0.3)
        check("abnormal-only filter dims normal values",
              evaluate("document.querySelectorAll('.dimmed').length"), lambda v: (v or 0) > 0)

        check("reference ranges present in the flowsheet",
              evaluate("document.querySelectorAll('td.refcol').length"),
              lambda v: (v or 0) >= 20)
        check("range gauges rendered",
              evaluate("document.querySelectorAll('svg.gauge').length"),
              lambda v: (v or 0) >= 5)

        width = 20
        for label, ok, got, _ in checks:
            print(f"  {'PASS' if ok else 'FAIL'}  {label:44} {str(got)[:width]}")
        print(f"\n{len(checks) - len(failures)}/{len(checks)} interaction checks passed")
        return 1 if failures else 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
