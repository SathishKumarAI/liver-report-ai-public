"""Single entry point.

    python run.py            full pipeline: render -> extract -> build
    python run.py build      rebuild the dashboard from existing extraction
    python run.py serve      serve the dashboard + local RAG chat on localhost
    python run.py check      PHI containment and coverage report

Refuses to run inside a git repo that is not ignoring data/ and dist/. That is
not paranoia: this pipeline writes patient data to disk, and the moment it does
so into a tracked directory the leak already exists.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from src import config as C  # noqa: E402


def guard_phi() -> None:
    inside = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True)
    if inside.returncode != 0:
        return                                   # not a repo; nothing to leak into
    for path in ("data", "dist"):
        r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", path],
                           capture_output=True)
        if r.returncode != 0:
            raise SystemExit(
                f"REFUSING TO RUN: {path}/ is not gitignored in this repo.\n"
                "This pipeline writes patient data there. Fix .gitignore first."
            )


def cmd_pipeline() -> int:
    from src import extract, render
    pdfs = sorted(C.RAW.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDF in {C.RAW}. Put the report there and re-run.")
    print(f"[1/3] rendering pages from {pdfs[0].name}")
    render.render_pages(pdfs[0], C.PAGES)
    print("[2/3] extracting observations (three OCR passes per page)")
    extract.run()
    print("[3/3] building dataset and dashboard")
    return cmd_build()


def cmd_build(strict: bool = False) -> int:
    from src import build
    return build.main(strict=strict)


def cmd_check() -> int:
    ok = True
    for path in ("data", "dist"):
        r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", path],
                           capture_output=True)
        state = "ignored" if r.returncode == 0 else "NOT IGNORED"
        print(f"  {path + '/':8} {state}")
        ok &= r.returncode == 0

    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                             capture_output=True, text=True).stdout.split("\n")
    leaks = [f for f in tracked if f.startswith(("data/", "dist/"))
             or f.lower().endswith((".pdf", ".jpg", ".jpeg", ".png"))]
    print(f"  tracked PHI files: {leaks if leaks else 'none'}")
    ok &= not leaks

    if C.LABS_JSON.exists():
        d = json.loads(C.LABS_JSON.read_text())
        vals = [o for o in d["observations"] if o.get("value") is not None]
        verified = [o for o in vals if o["provenance"].get("human_verified")]
        flagged = [o for o in vals if o.get("needs_review")]
        print(f"  observations     : {len(d['observations'])}")
        print(f"  charted values   : {len(vals)}")
        print(f"  human-verified   : {len(verified)}")
        print(f"  flagged by gates : {len(flagged)}")
    return 0 if ok else 1


def cmd_serve(port: int = 8080) -> int:
    """Serve the dashboard and proxy chat to a local Ollama.

    A local server rather than a file:// page, because the chat endpoint has to
    live somewhere. It binds 127.0.0.1 only -- this must not be reachable from
    the network.
    """
    import http.server
    import socketserver
    from src import rag

    if not C.DASHBOARD.exists():
        raise SystemExit("No dashboard yet. Run: python run.py")

    dataset = json.loads(C.LABS_JSON.read_text())

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html", "/dashboard.html"):
                body = C.DASHBOARD.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            # Evidence crops, so the Validation tab can show the pixels a value
            # came from without embedding ~6 MB of base64 into the page.
            if self.path.startswith("/data/crops/"):
                name = Path(self.path).name
                if name != Path(name).name or "/" in name or "\\" in name:
                    return self.send_error(400)
                target = C.CROPS / name
                if not target.exists():
                    return self.send_error(404)
                body = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/api/models":
                try:
                    payload = {"models": rag.list_models(), "model": rag.pick_model()}
                except Exception as exc:
                    payload = {"models": [], "error": str(exc)}
                return self._json(payload)
            self.send_error(404)

        def do_POST(self):
            if self.path != "/api/chat":
                return self.send_error(404)
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad JSON"}, 400)

            question = (req.get("question") or "").strip()
            if not question:
                return self._json({"error": "empty question"}, 400)
            try:
                return self._json(rag.answer(question, dataset, model=req.get("model")))
            except Exception as exc:
                # The dashboard shows this text verbatim, so it must be useful:
                # the usual cause is simply that Ollama is not running.
                return self._json({"error": f"{exc}"}, 503)

        def _json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass                                  # keep the console readable

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        print(f"Dashboard : http://127.0.0.1:{port}/")
        print("Chat      : local Ollama, nothing leaves this machine")
        print("Ctrl-C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


COMMANDS = {"build": cmd_build, "serve": cmd_serve, "check": cmd_check}

if __name__ == "__main__":
    guard_phi()
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg is None:
        raise SystemExit(cmd_pipeline())
    if arg not in COMMANDS:
        raise SystemExit(f"unknown command {arg!r}; one of {sorted(COMMANDS)} or no argument")
    if arg == "serve" and len(sys.argv) > 2:
        raise SystemExit(cmd_serve(int(sys.argv[2])))
    raise SystemExit(COMMANDS[arg]())
