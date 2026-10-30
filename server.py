#!/usr/bin/env python3
"""
Cloud Browser prototype v2 — FULL CONTROL. Self-built, like Browser.lol /
NetworkChuck Cloud Browser.

v2 adds, over v1's screenshot + basic click/type/scroll:
- Direct keyboard: click the live view to focus it, then every keydown on it
  (letters, Backspace, Delete, Tab, Escape, arrows, Enter, Ctrl+A/C/V/X...)
  is forwarded to the remote page's focused element. The old type-box stays
  as a backup.
- Right-click (contextmenu, no browser menu) and double-click, forwarded.
- Back / Forward / Reload on the SAME session (no restart).
- Navigate in the same session: URL bar + Go on a live session does
  page.goto in that session (same sid); Start only creates a session when
  none is live.
- Hover: mousemove over the live view is forwarded (throttled in the UI),
  so hover menus / tooltips work.

The session runs UNLIMITED — no time limit at all — until the user clicks
Stop. No persistence, no cookies saved, no sign-up, no payment, no phone-home.

Stack: Python 3.12 stdlib http.server + Playwright (sync API, from fbvenv).
Playwright is NOT thread-safe across threads, so ALL Playwright calls run in
one dedicated worker thread, marshalled through a queue. HTTP handlers only
submit work to that thread and wait for the result.

Run:  CLOUD_BROWSER_TOKEN=<long-random-token> \
      ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/server.py
Then open http://127.0.0.1:8765/ in your own browser.

TOKEN AUTH (required before any public link): the server refuses to start
unless CLOUD_BROWSER_TOKEN is set in the environment. The token is never
hardcoded and never written to any file by this server. Every /api/* route
checks it (header X-Cloud-Token, or ?token= query). The UI asks for the
token once and keeps it in memory only. Wrong/missing token = 401 JSON,
no session data leaked. Without this, anyone with a public tunnel URL
could drive the remote browser.

Hosting: binds 0.0.0.0 and reads PORT from the environment (Render sets
PORT; CLOUD_BROWSER_PORT is also accepted as a fallback), so the same file
runs on Render without code changes.

HONEST LIMIT: the VM's Chromium has NO internet path (see AGENTS.md — direct
egress fails, even example.org fails in Chromium). So v2 is proven ONLY
against the local test pages served by this same server. Live internet
browsing is UNPROVEN on the VM and needs a host with internet (Afnan's PC).
"""
import hmac
import json
import mimetypes
import os
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Render sets PORT; CLOUD_BROWSER_PORT is the local override. Bind 0.0.0.0
# so the service is reachable outside the container (127.0.0.1 would only
# listen on localhost and Render's health check / public URL would fail).
# PORT EXPLICIT: when PORT/CLOUD_BROWSER_PORT is set in the environment
# (Render, or a manual override) that exact port is used, no fallback.
# When neither is set (laptop run), the server tries FALLBACK_PORTS in
# order and binds the first free one — Windows often forbids one port
# (WinError 10013, excluded port range) while the next one binds fine.
# The port actually bound is written to port.txt next to this file, so
# the launcher can point the tunnel at it.
PORT_EXPLICIT = "PORT" in os.environ or "CLOUD_BROWSER_PORT" in os.environ
PORT = int(os.environ.get("PORT", os.environ.get("CLOUD_BROWSER_PORT", "8765")))
FALLBACK_PORTS = [8765, 8766, 8767, 8080, 8000, 9000, 5000, 3000]
HOST = os.environ.get("CLOUD_BROWSER_HOST", "0.0.0.0")
VIEWPORT = {"width": 1280, "height": 720}
# No time limit: sessions run unlimited until explicit Stop (Afnan correction).

# TOKEN AUTH: shared secret, read ONLY from the environment. The server
# refuses to start if it is unset (see __main__) — refusing is safer than
# auto-generating one, because a generated token printed to a console can
# be missed or logged, and a public tunnel URL must never expose an
# unauthenticated browser. Never hardcode a token in this repo.
TOKEN = os.environ.get("CLOUD_BROWSER_TOKEN", "")


# ---------------------------------------------------------------------------
# Playwright worker thread — owns ALL Playwright objects.
# ---------------------------------------------------------------------------
class BrowserWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.sid = None
        self.started_at = None
        self.url = None
        # Keys currently held down via keyboard.down() (worker thread only),
        # so key_up() never releases a key that was never pressed down, and
        # combo presses (Ctrl+A etc., done as a single press()) are tracked
        # separately and not double-released.
        self._down_keys = set()

    # -- queue plumbing ------------------------------------------------------
    def call(self, fn, timeout=30):
        """Run fn() on the worker thread, return its result (or raise)."""
        done = threading.Event()
        box = {}

        def job():
            try:
                box["result"] = fn()
            except Exception as e:  # noqa: BLE001 — surface to caller
                box["error"] = e
            done.set()

        self.q.put(job)
        if not done.wait(timeout):
            raise TimeoutError("playwright worker timed out")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def run(self):
        while True:
            job = self.q.get()
            try:
                job()
            except Exception:
                pass  # job() already captures its own errors

    # -- session lifecycle (all run on the worker thread) --------------------
    def _stop_locked(self):
        for obj, name in ((self.page, "page"), (self.context, "context"),
                          (self.browser, "browser"), (self.playwright, "playwright")):
            try:
                if obj is not None:
                    obj.close() if name != "playwright" else obj.stop()
            except Exception:
                pass
        self.page = self.context = self.browser = self.playwright = None
        self.sid = None
        self.started_at = None
        self.url = None
        self._down_keys = set()

    def start_session(self, url):
        from playwright.sync_api import sync_playwright
        # v2: if a session is ALREADY live, Start navigates THAT session to
        # the new URL (same sid, same browser) instead of destroying it.
        if self.page is not None and self.sid is not None:
            try:
                self.page.goto(url, timeout=15000, wait_until="domcontentloaded")
            except Exception:
                # Navigation failed: keep the live session on its old page.
                raise
            self.url = url
            return {"sid": self.sid, "url": url, "title": self.page.title(),
                    "navigated": True}
        self._stop_locked()
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        # Fresh context every session: no storage, no cookies carried over.
        self.context = self.browser.new_context(
            viewport=VIEWPORT, ignore_https_errors=True)
        self.page = self.context.new_page()
        try:
            self.page.goto(url, timeout=15000, wait_until="domcontentloaded")
        except Exception:
            self._stop_locked()  # failed nav (e.g. no internet) = no session
            raise
        self.sid = "sess-%d" % int(time.time())
        self.started_at = time.time()
        self.url = url
        return {"sid": self.sid, "url": url, "title": self.page.title(),
                "navigated": False}

    def navigate(self, url):
        """Go to a URL in the CURRENT live session (error if none live)."""
        if self.page is None or self.sid is None:
            raise RuntimeError("no active session")
        self.page.goto(url, timeout=15000, wait_until="domcontentloaded")
        self.url = url
        return {"sid": self.sid, "url": url, "title": self.page.title()}

    def go_back(self):
        if self.page is None:
            raise RuntimeError("no active session")
        try:
            resp = self.page.go_back(timeout=5000, wait_until="domcontentloaded")
            ok = resp is not None
        except Exception:
            ok = False
        self.url = self.page.url
        return {"ok": ok, "url": self.url, "title": self.page.title()}

    def go_forward(self):
        if self.page is None:
            raise RuntimeError("no active session")
        try:
            resp = self.page.go_forward(timeout=5000, wait_until="domcontentloaded")
            ok = resp is not None
        except Exception:
            ok = False
        self.url = self.page.url
        return {"ok": ok, "url": self.url, "title": self.page.title()}

    def reload(self):
        if self.page is None:
            raise RuntimeError("no active session")
        self.page.reload(timeout=15000, wait_until="domcontentloaded")
        self.url = self.page.url
        return {"ok": True, "url": self.url, "title": self.page.title()}

    def _scale(self, x, y, disp_w, disp_h):
        """Scale displayed-image coords -> real 1280x720 viewport coords."""
        return (x * VIEWPORT["width"] / max(1, disp_w),
                y * VIEWPORT["height"] / max(1, disp_h))

    def stop(self):
        was = self.sid is not None
        self._stop_locked()
        return {"stopped": was}

    def status(self):
        if self.sid is None:
            return {"active": False}
        try:
            title = self.page.title() if self.page else ""
        except Exception:
            title = ""
        return {"active": True, "sid": self.sid, "url": self.url,
                "title": title,
                "elapsed": int(time.time() - self.started_at)}

    def screenshot(self):
        if self.page is None:
            raise RuntimeError("no active session")
        return self.page.screenshot(type="png")

    def click(self, x, y, disp_w, disp_h):
        if self.page is None:
            raise RuntimeError("no active session")
        rx, ry = self._scale(x, y, disp_w, disp_h)
        self.page.mouse.click(rx, ry)
        return {"clicked": [round(rx, 1), round(ry, 1)]}

    def right_click(self, x, y, disp_w, disp_h):
        if self.page is None:
            raise RuntimeError("no active session")
        rx, ry = self._scale(x, y, disp_w, disp_h)
        self.page.mouse.click(rx, ry, button="right")
        return {"right_clicked": [round(rx, 1), round(ry, 1)]}

    def double_click(self, x, y, disp_w, disp_h):
        if self.page is None:
            raise RuntimeError("no active session")
        rx, ry = self._scale(x, y, disp_w, disp_h)
        self.page.mouse.dblclick(rx, ry)
        return {"double_clicked": [round(rx, 1), round(ry, 1)]}

    def hover(self, x, y, disp_w, disp_h):
        if self.page is None:
            raise RuntimeError("no active session")
        rx, ry = self._scale(x, y, disp_w, disp_h)
        self.page.mouse.move(rx, ry)
        return {"hovered": [round(rx, 1), round(ry, 1)]}

    # -- direct keyboard -----------------------------------------------------
    # Playwright key names: "a", "Backspace", "Delete", "Tab", "Escape",
    # "ArrowLeft", "Enter", "Space", "Control", "Shift", "Alt", "Meta", ...
    # Browser KeyboardEvent.key gives " " for Space; map it to "Space".
    @staticmethod
    def _map_key(key):
        if key == " ":
            return "Space"
        return key

    def key_down(self, key, ctrl=False, meta=False, shift=False, alt=False):
        if self.page is None:
            raise RuntimeError("no active session")
        k = self._map_key(str(key))
        # Ctrl/Meta + single char (e.g. Ctrl+A): one press() of the combo.
        # This handles select-all / copy / paste / cut as a single action.
        if (ctrl or meta) and len(k) == 1:
            combo = "%s+%s" % ("Meta" if meta else "Control", k)
            self.page.keyboard.press(combo)
            return {"pressed": combo, "via": "combo-press"}
        # Modifier-only keys and ordinary keys: hold down until key_up().
        if k not in self._down_keys:
            self.page.keyboard.down(k)
            self._down_keys.add(k)
        return {"down": k}

    def key_up(self, key, ctrl=False, meta=False, shift=False, alt=False):
        if self.page is None:
            raise RuntimeError("no active session")
        k = self._map_key(str(key))
        # Combo presses and keys never held down: nothing to release.
        if k in self._down_keys:
            self.page.keyboard.up(k)
            self._down_keys.discard(k)
            return {"up": k}
        return {"up": k, "skipped": True}

    def type_text(self, text):
        if self.page is None:
            raise RuntimeError("no active session")
        self.page.keyboard.type(text)
        return {"typed": text}

    def press_key(self, key):
        if self.page is None:
            raise RuntimeError("no active session")
        self.page.keyboard.press(key)
        return {"pressed": key}

    def scroll(self, dy):
        if self.page is None:
            raise RuntimeError("no active session")
        self.page.mouse.wheel(0, dy)
        return {"scrolled": dy}

    def info(self):
        if self.page is None:
            raise RuntimeError("no active session")
        js = """() => {
          const q = s => { const el = document.querySelector(s);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {x: r.x, y: r.y, w: r.width, h: r.height,
                    text: (el.innerText || el.value || '').slice(0, 200)}; };
          const val = id => { const el = document.getElementById(id);
            if (!el) return null;
            return ('value' in el) ? el.value : (el.innerText || ''); };
          const ae = document.activeElement;
          return {title: document.title, url: location.href,
            body_text: (document.body.innerText || '').slice(0, 500),
            history_length: window.history.length,
            active_element: ae ? (ae.id || ae.tagName) : null,
            name_value: val('name'),
            status_text: val('status'),
            hover_status: val('hover-status'),
            ctx_status: val('ctx-status'),
            dbl_status: val('dbl-status'),
            page2_status: val('page2-status'),
            boxes: {'hello-btn': q('#hello-btn'), 'name': q('#name'),
                    'more-link': q('#more-link'),
                    'hover-box': q('#hover-box'),
                    'ctx-box': q('#ctx-box'), 'dbl-box': q('#dbl-box'),
                    'page2-link': q('#page2-link'),
                    'page2-btn': q('#page2-btn')}};
        }"""
        data = self.page.evaluate(js)
        data["active"] = True
        data["elapsed"] = int(time.time() - self.started_at)
        return data


WORKER = BrowserWorker()
WORKER.start()


# ---------------------------------------------------------------------------
# HTTP server (stdlib only)
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep logs short
        print("[http] %s %s" % (self.command, self.path), flush=True)

    # -- helpers -------------------------------------------------------------
    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self):
        """Token check for every /api/* route. Header X-Cloud-Token wins;
        ?token= query is the fallback (needed by plain <img>/link fetches).
        Constant-time compare; an empty server token never matches."""
        if not TOKEN:
            return False
        u = urlparse(self.path)
        q = parse_qs(u.query)
        supplied = (self.headers.get("X-Cloud-Token")
                    or (q.get("token") or [None])[0] or "")
        return hmac.compare_digest(supplied, TOKEN)

    def _require_auth(self):
        """Send 401 JSON and return False when the token is missing/wrong.
        Nothing about any session is revealed in the 401 body."""
        if self._auth_ok():
            return True
        self._send_json({"error": "unauthorized"}, code=401)
        return False

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n) or b"{}")

    def _serve_file(self, name):
        path = os.path.join(BASE_DIR, name)
        if not os.path.isfile(path):
            self.send_error(404, "not found")
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        data = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- routes ---------------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self._serve_file("index.html")
        elif u.path == "/test-page.html":
            self._serve_file("test-page.html")
        elif u.path == "/test-page2.html":
            self._serve_file("test-page2.html")
        elif u.path.startswith("/api/"):
            if not self._require_auth():
                return
            if u.path == "/api/status":
                # Must go through the worker queue: Playwright objects may only
                # be touched on the worker thread (direct calls crash greenlets).
                self._send_json(WORKER.call(WORKER.status))
            elif u.path == "/api/screenshot":
                try:
                    png = WORKER.call(WORKER.screenshot, timeout=15)
                except Exception as e:
                    self._send_json({"error": str(e)}, code=410)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.end_headers()
                self.wfile.write(png)
            elif u.path == "/api/info":
                try:
                    self._send_json(WORKER.call(WORKER.info, timeout=15))
                except Exception as e:
                    self._send_json({"error": str(e)}, code=410)
            else:
                self.send_error(404, "not found")
        else:
            self.send_error(404, "not found")

    def do_POST(self):
        u = urlparse(self.path)
        if not u.path.startswith("/api/"):
            self.send_error(404, "not found")
            return
        # Auth BEFORE reading the body: unauthenticated requests are refused
        # without touching any session state.
        if not self._require_auth():
            return
        try:
            body = self._read_json()
        except Exception as e:
            self._send_json({"error": "bad json: %s" % e}, code=400)
            return
        try:
            if u.path == "/api/start":
                url = (body.get("url") or "").strip()
                if not url:
                    self._send_json({"error": "url required"}, code=400)
                    return
                if not (url.startswith(("http://", "https://", "file://"))):
                    self._send_json({"error": "url must start with http://, https:// or file://"}, code=400)
                    return
                self._send_json(WORKER.call(lambda: WORKER.start_session(url), timeout=30))
            elif u.path == "/api/navigate":
                # Go to a URL in the CURRENT live session (no restart).
                url = (body.get("url") or "").strip()
                if not url:
                    self._send_json({"error": "url required"}, code=400)
                    return
                if not (url.startswith(("http://", "https://", "file://"))):
                    self._send_json({"error": "url must start with http://, https:// or file://"}, code=400)
                    return
                self._send_json(WORKER.call(lambda: WORKER.navigate(url), timeout=30))
            elif u.path == "/api/back":
                self._send_json(WORKER.call(WORKER.go_back, timeout=15))
            elif u.path == "/api/forward":
                self._send_json(WORKER.call(WORKER.go_forward, timeout=15))
            elif u.path == "/api/reload":
                self._send_json(WORKER.call(WORKER.reload, timeout=30))
            elif u.path == "/api/stop":
                self._send_json(WORKER.call(WORKER.stop))
            elif u.path == "/api/click":
                self._send_json(WORKER.call(lambda: WORKER.click(
                    float(body["x"]), float(body["y"]),
                    float(body.get("disp_w") or VIEWPORT["width"]),
                    float(body.get("disp_h") or VIEWPORT["height"])), timeout=15))
            elif u.path == "/api/rightclick":
                self._send_json(WORKER.call(lambda: WORKER.right_click(
                    float(body["x"]), float(body["y"]),
                    float(body.get("disp_w") or VIEWPORT["width"]),
                    float(body.get("disp_h") or VIEWPORT["height"])), timeout=15))
            elif u.path == "/api/dblclick":
                self._send_json(WORKER.call(lambda: WORKER.double_click(
                    float(body["x"]), float(body["y"]),
                    float(body.get("disp_w") or VIEWPORT["width"]),
                    float(body.get("disp_h") or VIEWPORT["height"])), timeout=15))
            elif u.path == "/api/hover":
                self._send_json(WORKER.call(lambda: WORKER.hover(
                    float(body["x"]), float(body["y"]),
                    float(body.get("disp_w") or VIEWPORT["width"]),
                    float(body.get("disp_h") or VIEWPORT["height"])), timeout=15))
            elif u.path == "/api/type":
                self._send_json(WORKER.call(
                    lambda: WORKER.type_text(str(body.get("text", ""))), timeout=15))
            elif u.path == "/api/key":
                self._send_json(WORKER.call(
                    lambda: WORKER.press_key(str(body.get("key", "Enter"))), timeout=15))
            elif u.path == "/api/keydown":
                self._send_json(WORKER.call(lambda: WORKER.key_down(
                    str(body.get("key", "")),
                    bool(body.get("ctrl")), bool(body.get("meta")),
                    bool(body.get("shift")), bool(body.get("alt"))), timeout=15))
            elif u.path == "/api/keyup":
                self._send_json(WORKER.call(lambda: WORKER.key_up(
                    str(body.get("key", "")),
                    bool(body.get("ctrl")), bool(body.get("meta")),
                    bool(body.get("shift")), bool(body.get("alt"))), timeout=15))
            elif u.path == "/api/scroll":
                self._send_json(WORKER.call(
                    lambda: WORKER.scroll(float(body.get("dy", 300))), timeout=15))
            else:
                self.send_error(404, "not found")
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": str(e)}, code=500)


if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: CLOUD_BROWSER_TOKEN is not set — refusing to start.",
              file=sys.stderr)
        print("Set it first, e.g.:", file=sys.stderr)
        print("  CLOUD_BROWSER_TOKEN=<long-random-token> python server.py",
              file=sys.stderr)
        print("The token is the only lock on the browser: a public tunnel",
              file=sys.stderr)
        print("URL must never expose an unauthenticated remote browser.",
              file=sys.stderr)
        sys.exit(2)
    if PORT_EXPLICIT:
        ports = [PORT]
    else:
        ports = FALLBACK_PORTS
    server = None
    for port in ports:
        try:
            server = ThreadingHTTPServer((HOST, port), Handler)
            PORT = port
            break
        except OSError as e:
            print("Port %d unavailable (%s) - trying next." % (port, e), flush=True)
    if server is None:
        print("ERROR: no free port in %s - all refused." % (ports,), file=sys.stderr)
        sys.exit(3)
    try:
        with open(os.path.join(BASE_DIR, "port.txt"), "w") as f:
            f.write(str(PORT))
    except OSError:
        pass
    print("Cloud Browser v2 — http://%s:%d/  (test page: /test-page.html)" % (HOST, PORT), flush=True)
    print("Full control, unlimited sessions until Stop, no persistence, no sign-up.", flush=True)
    print("Token auth ON: every /api/* call needs X-Cloud-Token.", flush=True)
    server.serve_forever()
