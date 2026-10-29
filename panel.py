#!/usr/bin/env python3
"""Local web panel: run the crawler/import steps from the browser, one button each.

  python3 panel.py              # opens http://127.0.0.1:8765
  python3 panel.py --port 9000 --no-browser

Login (OTP) happens in the panel; the access/refresh tokens stay in this process's memory, are refreshed
before each step and handed to the scripts as ABZAR_TOKEN — the browser never sees them.
Only the steps listed in panel_steps.py can run (by id). Listens on 127.0.0.1 only, and every request must
carry the per-run key embedded in the page and a localhost Host header (no cross-site / DNS-rebinding use).
"""
import argparse
import base64
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from import_categories import DEFAULT_BASE
from panel_steps import GROUPS, STEPS

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "panel.html"
BASES = [DEFAULT_BASE, "http://localhost:4000"]
KEY = secrets.token_urlsafe(24)


def jwt_exp(token):
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"]
    except (IndexError, ValueError, KeyError):
        return 0


class Session:
    def __init__(self):
        self.lock = threading.Lock()
        self.base = DEFAULT_BASE
        self.clear()

    def clear(self):
        self.access = self.refresh = None
        self.user = None

    def api(self, path, body):
        """POST JSON to the API; returns (status, parsed body)."""
        req = urllib.request.Request(
            f"{self.base}/api/v1{path}", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return 0, {"message": f"سرور در دسترس نیست ({getattr(e, 'reason', e)})"}

    def store(self, data):
        self.access, self.refresh = data["accessToken"], data["refreshToken"]
        if data.get("user"):
            self.user = {k: data["user"].get(k) for k in ("fullName", "mobile", "role")}

    def token(self):
        """A valid access token, refreshed if it expires within a minute; None when logged out."""
        with self.lock:
            if not self.access:
                return None
            if jwt_exp(self.access) - time.time() > 60:
                return self.access
            status, data = self.api("/auth/refresh", {"refreshToken": self.refresh})
            if status == 200 and data.get("accessToken"):
                self.store(data)
                return self.access
            self.clear()
            return None

    def view(self):
        return {"base": self.base, "bases": BASES, "loggedIn": bool(self.access), "user": self.user,
                "expiresAt": jwt_exp(self.access) if self.access else None}


SESSION = Session()
RUN = {"proc": None, "id": None}
RUN_LOCK = threading.Lock()


def command(step):
    args = list(step["args"])
    if step.get("token") and SESSION.base != DEFAULT_BASE:
        args += ["--base", SESSION.base]
    return args


def steps_view():
    return [{**{k: g[k] for k in ("id", "title", "desc")},
             "steps": [{"id": s["id"], "title": s["title"], "desc": s["desc"],
                        "token": bool(s.get("token")), "danger": bool(s.get("danger")),
                        "optional": bool(s.get("optional")), "cmd": "python3 " + " ".join(command(s))}
                       for s in g["steps"]]} for g in GROUPS]


def message(data, fallback):
    msg = data.get("message")
    return " ".join(msg) if isinstance(msg, list) else (msg or fallback)


class Handler(BaseHTTPRequestHandler):
    server_version = "panel"

    def log_message(self, *_):  # no request log (bodies may carry the OTP code)
        pass

    def allowed(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.allowed():
            return self.send_error(403)
        if self.path != "/":
            return self.send_error(404)
        data = PAGE.read_text(encoding="utf-8").replace("__PANEL_KEY__", KEY).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self.allowed() or not secrets.compare_digest(self.headers.get("X-Panel-Key", ""), KEY):
            return self.send_error(403)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send_json(400, {"message": "بدنه‌ی نامعتبر"})
        route = {
            "/api/state": self.state, "/api/base": self.set_base, "/api/otp/request": self.otp_request,
            "/api/otp/verify": self.otp_verify, "/api/logout": self.logout, "/api/run": self.run,
            "/api/stop": self.stop,
        }.get(self.path)
        if not route:
            return self.send_error(404)
        route(body)

    def state(self, _):
        SESSION.token()  # drop a session whose refresh token died
        self.send_json(200, {"session": SESSION.view(), "groups": steps_view(), "running": RUN["id"]})

    def set_base(self, body):
        if body.get("base") not in BASES:
            return self.send_json(400, {"message": "سرور نامعتبر"})
        if RUN["id"]:
            return self.send_json(409, {"message": "یک مرحله در حال اجراست"})
        with SESSION.lock:
            if SESSION.base != body["base"]:
                SESSION.base = body["base"]
                SESSION.clear()  # a token only works on the server that issued it
        self.state(None)

    def otp_request(self, body):
        status, data = SESSION.api("/auth/otp/request", {"mobile": str(body.get("mobile", "")).strip()})
        if status != 200:
            return self.send_json(400, {"message": message(data, f"خطا {status}")})
        self.send_json(200, {"resendAfter": data.get("resendAfter"), "devCode": data.get("devCode")})

    def otp_verify(self, body):
        status, data = SESSION.api("/auth/otp/verify", {"mobile": str(body.get("mobile", "")).strip(),
                                                        "code": str(body.get("code", "")).strip()})
        if status != 200 or not data.get("accessToken"):
            return self.send_json(400, {"message": message(data, f"خطا {status}")})
        if (data.get("user") or {}).get("role") in (None, "", "customer"):
            return self.send_json(403, {"message": "این حساب دسترسی ادمین ندارد"})
        with SESSION.lock:
            SESSION.store(data)
        self.send_json(200, {"session": SESSION.view()})

    def logout(self, _):
        token = SESSION.token()
        if token:
            req = urllib.request.Request(f"{SESSION.base}/api/v1/auth/logout", method="POST",
                                         headers={"Authorization": f"Bearer {token}"})
            try:
                urllib.request.urlopen(req, timeout=15).close()
            except (urllib.error.URLError, OSError):
                pass
        with SESSION.lock:
            SESSION.clear()
        self.send_json(200, {"session": SESSION.view()})

    def stop(self, _):
        proc = RUN["proc"]
        if proc and proc.poll() is None:
            proc.terminate()
        self.send_json(200, {})

    def run(self, body):
        step = STEPS.get(body.get("id"))
        if not step:
            return self.send_json(404, {"message": "مرحله‌ی ناشناخته"})
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        env.pop("ABZAR_TOKEN", None)
        if step.get("token"):
            token = SESSION.token()
            if not token:
                return self.send_json(401, {"message": "اول وارد شوید (یا نشست منقضی شده)"})
            env["ABZAR_TOKEN"] = token
        if not RUN_LOCK.acquire(blocking=False):
            title = STEPS.get(RUN["id"] or "", {}).get("title", "دیگری")
            return self.send_json(409, {"message": f"مرحله‌ی «{title}» در حال اجراست"})
        try:
            args = command(step)
            proc = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            RUN.update(proc=proc, id=step["id"])
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.emit({"t": "start", "cmd": "python3 " + " ".join(args)})
            try:
                for raw in proc.stdout:
                    self.emit({"t": "out", "line": raw.decode("utf-8", "replace").rstrip("\n")})
            except (BrokenPipeError, ConnectionResetError):
                proc.terminate()  # page closed mid-run
            code = proc.wait()
            self.emit({"t": "exit", "code": code})
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            RUN.update(proc=None, id=None)
            RUN_LOCK.release()

    def emit(self, obj):
        self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
        self.wfile.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"panel: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        proc = RUN["proc"]
        if proc and proc.poll() is None:
            proc.terminate()


if __name__ == "__main__":
    main()
