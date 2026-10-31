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

v6 adds, over v5's profiles + extensions + screencast:
- Cookie login: POST /api/cookies injects cookies into the live context
  with Playwright context.add_cookies() — HttpOnly cookies (c_user, xs,
  fr) included — either as a list of cookie objects or as one raw
  "name=value; name=value" string + a domain. GET /api/cookies lists
  the live context's cookies (behind the same token auth). The UI has a
  paste-a-cookie-string + domain + Inject section.
- File upload: POST /api/upload (multipart) feeds a file to the remote
  page — mode "input" sets it on a file input via set_input_files
  (selector, default input[type=file], works on hidden inputs too);
  mode "chooser" arms a one-time filechooser handler that feeds the
  file to the next native file dialog the page opens. GET
  /api/upload/status reports armed/fired. The UI has a file picker +
  both buttons.
- Parity: /api/select (dropdown by value/label/index), /api/drag
  (mouse drag between two view points), and /api/click takes a button
  (left/middle/right). Still NOT controllable: the browser's own UI
  (tabs, DevTools), multi-tab sessions, shared clipboard, touch, audio.

The session runs UNLIMITED — no time limit at all — until the user clicks
Stop. No sign-up, no payment, no phone-home. Profiles give separate
isolated logins: each profile's cookies + localStorage persist in
profiles/<id>.json (Playwright storage_state) and are reloaded when that
profile becomes active; one profile is active at a time (see README).

Live video: the UI shows a CDP screencast (Page.startScreencast, JPEG,
every damage frame forwarded; the UI polls ~10 fps) instead of one
screenshot per poll — see _start_screencast_locked. If the screencast
fails or stalls, /api/screenshot falls back to a one-off page.screenshot,
so the session never freezes.

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
import base64
import hmac
import json
import mimetypes
import os
import queue
import re
import shutil
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

# Chromium launch flags shared by both launch paths. The last three keep
# the compositor and timers unthrottled: a headless page counts as
# occluded/hidden, and Chrome throttles its BeginFrames and timers to
# ~1 Hz without them. They do NOT make the screencast flow on their own
# (measured 2026-10-31: still 0.7 fps with everyNthFrame=1 after adding
# them) — the compositor poke in _poke_screencast is what drives frames.
# They stay as belt-and-braces for timers and real pages.
CHROMIUM_ARGS = ["--no-sandbox", "--disable-dev-shm-usage",
                 "--disable-backgrounding-occluded-windows",
                 "--disable-renderer-backgrounding",
                 "--disable-background-timer-throttling",
                 # LOW-MEMORY (Render free = 512 MB; the service OOM-restarted
                 # 2026-10-31 after a live Facebook session): no GPU process
                 # and no SwiftShader software rasterizer (both allocate
                 # memory headless Chromium never uses), and cap each
                 # renderer's V8 heap at 256 MB so one greedy page cannot
                 # eat the whole box. Deliberately NOT --disable-extensions
                 # (would break extensions mode) and NOT --single-process /
                 # --no-zygote (the desktop variant segfaulted on
                 # --single-process; the zygote shares memory via fork).
                 "--disable-gpu", "--disable-software-rasterizer",
                 "--js-flags=--max-old-space-size=256"]

# PROFILES: separate isolated logins (cookies + localStorage). Each profile
# is an id (slug of its name) + a display name. The registry (id -> name,
# plus which profile is active) lives in profiles.json next to this file;
# each profile's browser state lives in profiles/<id>.json as a Playwright
# storage_state file. Only ONE context/page is ever alive (Render free has
# 512 MB) — switching saves the old profile's state, closes its context,
# and opens the new profile's context with its saved state, if any.
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
REGISTRY_PATH = os.path.join(BASE_DIR, "profiles.json")
DEFAULT_PROFILE = "default"

# UPLOADS: files posted to /api/upload are saved here (server-side, so
# set_input_files / the filechooser handler can feed them to the remote
# page). Ephemeral on Render, like profiles. 20 MB cap per file; files
# older than 1 hour are deleted opportunistically on each upload.
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
UPLOAD_MAX_BYTES = 20 * 1024 * 1024
UPLOAD_TTL_SECONDS = 3600

# EXTENSIONS: unpacked MV3 extensions to load into the remote browser.
# Each subfolder of extensions/ containing a manifest.json is loaded at
# browser launch via --load-extension. Extensions only run in a NORMAL
# (non-incognito) browser context: Playwright's chromium.launch() runs
# the headless-shell build and its new_context() pages are incognito, so
# extensions never load there — verified 2026-10-31 (marker stayed None
# in every launch() variant, loaded in launch_persistent_context). The
# working path is a persistent context on the FULL Chromium build
# (channel="chromium", new headless) — see _ensure_browser_locked. With
# no extensions installed the launch is exactly as before.
EXTENSIONS_DIR = os.path.join(BASE_DIR, "extensions")


def find_extensions():
    """Absolute paths of unpacked extensions to load: each subfolder of
    extensions/ holding a manifest.json. [] when the folder is missing
    or empty. Sorted, so the launch order is stable.

    Extensions are OPT-IN since 2026-10-31 (Render free = 512 MB):
    loading any extension forces launch_persistent_context on the FULL
    Chromium build, and a single Facebook session in that mode OOM-killed
    the instance 6 times in one evening (23:29–23:49 PKT) — including
    once on the new low-memory flags. With no extensions the server uses
    chromium.launch() (headless-shell build), which is far lighter and
    is what the rename job needs. Set CLOUD_BROWSER_EXTENSIONS=1 to
    re-enable extension mode."""
    if os.environ.get("CLOUD_BROWSER_EXTENSIONS", "").strip().lower() not in (
            "1", "true", "yes", "on"):
        return []
    try:
        names = sorted(os.listdir(EXTENSIONS_DIR))
    except OSError:
        return []
    found = []
    for name in names:
        d = os.path.join(EXTENSIONS_DIR, name)
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "manifest.json")):
            found.append(d)
    return found

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
        # EXTENSIONS mode only: the persistent context the session page
        # lives in (None in the classic launch() mode).
        self.persistent_context = None
        self.context = None
        self.page = None
        self.sid = None
        self.started_at = None
        self.url = None
        # PROFILES: id -> display name, plus which profile is active.
        # The registry is loaded from profiles.json at startup (or starts
        # with just "default"); storage_state files live in profiles/.
        self.profiles = {DEFAULT_PROFILE: "Default"}
        self.active_profile = DEFAULT_PROFILE
        self._load_registry()
        # Keys currently held down via keyboard.down() (worker thread only),
        # so key_up() never releases a key that was never pressed down, and
        # combo presses (Ctrl+A etc., done as a single press()) are tracked
        # separately and not double-released.
        self._down_keys = set()
        # FILE UPLOAD (chooser-arm mode): the path of the armed file and
        # whether it has been handed to a file dialog yet, plus the last
        # failure. The armed handler is registered once per arm via
        # page.once("filechooser").
        self._upload_armed = False
        self._upload_path = None
        self._upload_file = None
        self._upload_fired = False
        self._upload_error = None
        self._upload_armed_at = 0.0
        # SCREENCAST (CDP live stream): the latest JPEG frame from
        # Page.screencastFrame, plus ack bookkeeping. The event handler
        # runs on Playwright's driver thread, NOT the worker thread — it
        # only stores bytes under _frame_lock and enqueues the ack job;
        # every Playwright call stays on the worker thread.
        self._cdp = None
        self._screencast_on = False
        self._frame_lock = threading.Lock()
        self._frame = None            # latest JPEG bytes
        self._frame_ts = 0.0          # when the latest frame arrived
        self._frame_seq = 0           # frames received, current session
        self._frame_bytes_total = 0
        self._pending_ack = None      # screencastFrame sessionId awaiting ack
        self._last_fallback_ts = 0.0  # last rate-limited fallback shot
        self._last_poke_ts = 0.0       # last compositor poke (rate limit)

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
            try:
                job = self.q.get(timeout=0.1)
            except queue.Empty:
                self._poke_screencast()
                continue
            try:
                job()
            except Exception:
                pass  # job() already captures its own errors
            # Poke on a time basis, not just when idle: a client polling
            # /api/screenshot every 50 ms would otherwise starve the
            # poke (q.get never times out) and the stream would stall
            # — measured 2026-10-31, click latency 1.03 s until the
            # poke also ran after each job.
            self._poke_screencast()

    def _poke_screencast(self):
        """Kick the compositor so the screencast produces its next frame.
        Headless Chromium does not composite on damage alone: measured
        2026-10-31, an animation changing the DOM every 150 ms produced
        ZERO frames in 10 s with no other traffic, and ~1 frame per
        page.evaluate when the test polled (bring_to_front and the
        --disable-backgrounding-* flags did not help). A tiny DOM read
        every ~100 ms, only while a session is live and the screencast
        is on, keeps the stream flowing at ~10 fps while the page
        changes. Time-gated (at most 1 poke per 100 ms) and called both
        when the queue is idle and after each job, so a fast-polling
        client cannot starve it. Runs on the worker thread, so it never
        delays real work by more than the evaluate itself; a static
        page has no damage to flush, so it produces no extra frames
        there."""
        now = time.time()
        if now - self._last_poke_ts < 0.1:
            return
        self._last_poke_ts = now
        if self.page is None or not self._screencast_on:
            return
        try:
            self.page.evaluate("() => document.title")
        except Exception:
            pass

    # -- session lifecycle (all run on the worker thread) --------------------
    # -- profiles ------------------------------------------------------------
    # All profile methods run on the worker thread (they touch Playwright
    # state and the registry). Only ONE context/page is ever alive.
    def _load_registry(self):
        try:
            with open(REGISTRY_PATH) as f:
                data = json.load(f)
            profiles = {str(k): str(v) for k, v in
                        (data.get("profiles") or {}).items() if k and v}
            active = data.get("active") or DEFAULT_PROFILE
            if DEFAULT_PROFILE not in profiles:
                profiles = {DEFAULT_PROFILE: "Default", **profiles}
            if active not in profiles:
                active = DEFAULT_PROFILE
            self.profiles = profiles
            self.active_profile = active
        except Exception:
            pass  # missing/corrupt registry — start with just "default"

    def _save_registry(self):
        try:
            with open(REGISTRY_PATH, "w") as f:
                json.dump({"active": self.active_profile,
                           "profiles": self.profiles}, f)
        except Exception:
            pass  # registry is a convenience; a failed save must not break use

    @staticmethod
    def _slug(name):
        slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
        return slug or "profile"

    def list_profiles(self):
        return {"profiles": [{"id": pid, "name": self.profiles[pid]}
                             for pid in self.profiles],
                "active": self.active_profile}

    def create_profile(self, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name required")
        name = name.strip()[:64]
        base = self._slug(name)
        pid, n = base, 2
        while pid in self.profiles:
            pid = "%s-%d" % (base, n)
            n += 1
        self.profiles[pid] = name
        self._save_registry()
        return {"id": pid, "name": name}

    def select_profile(self, pid):
        if pid not in self.profiles:
            raise RuntimeError("unknown profile: %s" % pid)
        if pid == self.active_profile:
            return {"ok": True, "active": pid, "switched": False,
                    "session_ended": False}
        was_live = self.sid is not None
        self._close_context_locked()  # saves the old profile's state first
        self.active_profile = pid
        self._save_registry()
        return {"ok": True, "active": pid, "switched": True,
                "session_ended": was_live}

    def delete_profile(self, pid):
        if pid not in self.profiles:
            raise RuntimeError("unknown profile: %s" % pid)
        if pid == DEFAULT_PROFILE:
            raise RuntimeError("the default profile cannot be deleted")
        was_active = pid == self.active_profile
        was_live = was_active and self.sid is not None
        if was_active:
            # Discard the deleted profile's state: close WITHOUT saving,
            # then drop its state file.
            self._close_context_locked(save=False)
            self.active_profile = DEFAULT_PROFILE
        del self.profiles[pid]
        try:
            os.remove(os.path.join(PROFILES_DIR, pid + ".json"))
        except OSError:
            pass
        # EXTENSIONS mode stores a profile's state in its own
        # user-data-dir (profiles/<id>/), not a .json file — remove it too.
        shutil.rmtree(os.path.join(PROFILES_DIR, pid), ignore_errors=True)
        self._save_registry()
        return {"ok": True, "active": self.active_profile,
                "session_ended": was_live}

    def _state_path(self):
        return os.path.join(PROFILES_DIR, self.active_profile + ".json")

    def _save_state_locked(self):
        """Persist the active profile's cookies + localStorage to its
        profiles/<id>.json storage_state file. No context = nothing to
        save. A failed save never breaks stop/switch. In EXTENSIONS mode
        the state already lives in the profile's user-data-dir (Chrome
        saves it there itself), so there is nothing to save here."""
        if self.context is None or self.persistent_context is not None:
            return
        try:
            os.makedirs(PROFILES_DIR, exist_ok=True)
            self.context.storage_state(path=self._state_path())
        except Exception:
            pass

    def _close_context_locked(self, save=True):
        """Close page + context only (browser stays alive for a fast
        restart). Saves the active profile's state first, unless the
        profile is being deleted. In EXTENSIONS mode the context IS the
        persistent context, so closing it also closes the browser — the
        next start relaunches it for the (possibly new) active profile."""
        if save:
            self._save_state_locked()
        # Stop the screencast BEFORE the page/context closes (the CDP
        # session dies with them); a later start re-creates it.
        self._stop_screencast_locked()
        try:
            if self.page is not None:
                self.page.close()
        except Exception:
            pass
        try:
            if self.context is not None:
                self.context.close()
        except Exception:
            pass
        if self.persistent_context is not None:
            self.persistent_context = None
            self.browser = None
        self.page = self.context = None
        self.sid = None
        self.started_at = None
        self.url = None
        self._down_keys = set()

    def _ensure_browser_locked(self):
        from playwright.sync_api import sync_playwright
        if self.browser is not None:
            return
        if self.playwright is None:
            self.playwright = sync_playwright().start()
        ext_dirs = find_extensions()
        if not ext_dirs:
            # No extensions: launch exactly as before.
            self.browser = self.playwright.chromium.launch(
                headless=True,
                args=CHROMIUM_ARGS,
            )
            self.persistent_context = None
            return
        # Extensions installed: load them into a persistent context on
        # the FULL Chromium build (channel="chromium", new headless).
        # chromium.launch() uses the headless-shell build and its
        # new_context() pages are incognito, so extensions never run
        # there — verified 2026-10-31. Each profile gets its own
        # user-data-dir under profiles/, so its logins persist there
        # natively (the .json storage_state files are not used in this
        # mode, and a profile that already has one starts fresh — see
        # README "Extensions").
        print("Extensions found: %s" % ", ".join(ext_dirs), flush=True)
        ext_arg = ",".join(ext_dirs)
        user_data_dir = os.path.join(PROFILES_DIR, self.active_profile)
        os.makedirs(user_data_dir, exist_ok=True)
        self.persistent_context = self.playwright.chromium.launch_persistent_context(
            user_data_dir, headless=True, channel="chromium",
            args=CHROMIUM_ARGS + [
                "--disable-extensions-except=" + ext_arg,
                "--load-extension=" + ext_arg],
            ignore_default_args=["--disable-extensions"],
            viewport=VIEWPORT, ignore_https_errors=True)
        self.browser = self.persistent_context.browser

    def _new_profile_context(self):
        """Fresh context for the ACTIVE profile, pre-loaded with its
        saved storage_state when the file exists. A corrupt/empty state
        file falls back to a clean context instead of failing the start.
        In EXTENSIONS mode the session page lives in the persistent
        context itself (extensions only run there)."""
        if self.persistent_context is not None:
            return self.persistent_context
        try:
            if os.path.isfile(self._state_path()):
                return self.browser.new_context(
                    viewport=VIEWPORT, ignore_https_errors=True,
                    storage_state=self._state_path())
        except Exception:
            pass
        return self.browser.new_context(
            viewport=VIEWPORT, ignore_https_errors=True)

    # -- CDP screencast (live video stream) ---------------------------------
    # /api/screenshot used to take a fresh page.screenshot per poll (~2 fps
    # still images). Now the worker runs a CDP screencast on the live page
    # (Page.startScreencast, JPEG q65, 1280 wide) and /api/screenshot
    # serves the newest frame from the cache — the UI feels like live video
    # instead of stills. everyNthFrame=1 (forward EVERY damage frame):
    # skipping any would delay a lone click/typing until the next repaint
    # — measured 2026-10-31, everyNthFrame=6 gave 0.7 fps on a page
    # changing every 150 ms. Headless Chromium does NOT composite on
    # damage alone (0 frames in 10 s with an animation running), so the
    # worker also pokes the compositor with a tiny DOM read every ~100 ms
    # (see _poke_screencast) — that is what makes frames flow. The UI
    # polls at ~10 Hz, which caps what the user sees; the server-side
    # rate follows page activity. When the screencast is off, stalled,
    # or has not delivered a frame yet, screenshot() falls back to a
    # rate-limited page.screenshot (JPEG), so the UI never freezes and a
    # failed screencast never kills the session.
    def _on_screencast_frame(self, payload):
        """CDP Page.screencastFrame handler. Runs on Playwright's driver
        thread — pure Python only: decode + store the frame, remember its
        sessionId for ack, enqueue the ack job on the worker queue.
        NEVER call Playwright APIs here (they belong to the worker
        thread and would deadlock)."""
        try:
            data = base64.b64decode(payload.get("data") or "")
            sid = payload.get("sessionId")
        except Exception:
            return
        if not data:
            return
        with self._frame_lock:
            self._frame = data
            self._frame_ts = time.time()
            self._frame_seq += 1
            self._frame_bytes_total += len(data)
            self._pending_ack = sid
        try:
            self.q.put(self._ack_job)
        except Exception:
            pass

    def _ack_job(self):
        """Ack the latest unacked screencast frame (worker thread only).
        Chromium sends the next frame only after an ack, so this keeps
        the stream flowing. Only the latest sessionId is acked; older
        unacked frames are superseded by the newer one."""
        with self._frame_lock:
            sid = self._pending_ack
            self._pending_ack = None
            cdp = self._cdp
        if not sid or cdp is None:
            return
        try:
            cdp.send("Page.screencastFrameAck", {"sessionId": sid})
        except Exception:
            pass

    def _start_screencast_locked(self):
        """Start CDP screencast on the live page (worker thread).
        Best-effort: any failure logs and leaves screencast OFF —
        screenshot() then falls back to page.screenshot, so the session
        still works. Works on the persistent-context page too (CDP is a
        page-target feature, not an extension)."""
        self._stop_screencast_locked()
        if self.page is None:
            return
        try:
            self._cdp = self.context.new_cdp_session(self.page)
            # Event name is the FULL CDP method: "Page.screencastFrame"
            # (CDPSession emits params["method"]). Subscribing to bare
            # "screencastFrame" never fires — verified 2026-10-31: the
            # stream stayed at 0 frames with that name.
            self._cdp.on("Page.screencastFrame", self._on_screencast_frame)
            self._cdp.send("Page.startScreencast", {
                "format": "jpeg", "quality": 65,
                "maxWidth": 1280, "everyNthFrame": 1})
            self._screencast_on = True
        except Exception as e:
            print("[screencast] start failed, falling back to screenshots: %s" % e, flush=True)
            self._cdp = None
            self._screencast_on = False

    def _stop_screencast_locked(self):
        """Stop screencast and drop the CDP session (worker thread).
        Called before the page/context closes, and before a restart."""
        cdp = self._cdp
        self._cdp = None
        self._screencast_on = False
        with self._frame_lock:
            self._pending_ack = None
            self._frame = None
            self._frame_ts = 0.0
        if cdp is not None:
            try:
                cdp.send("Page.stopScreencast")
            except Exception:
                pass

    def screencast_stats(self):
        """Frames received + bytes, for bandwidth measurement (test /
        debug helper, behind the same token auth)."""
        with self._frame_lock:
            return {"screencast_on": self._screencast_on,
                    "frames": self._frame_seq,
                    "bytes_total": self._frame_bytes_total}

    def evaluate(self, js):
        """Run a JS expression in the live page (test/debug helper,
        behind the same token auth). Returns {"result": ...}."""
        if self.page is None:
            raise RuntimeError("no active session")
        return {"result": self.page.evaluate(js)}

    def _stop_locked(self):
        self._close_context_locked()  # saves the active profile's state
        for obj, name in ((self.browser, "browser"),
                          (self.playwright, "playwright")):
            try:
                if obj is not None:
                    obj.close() if name != "playwright" else obj.stop()
            except Exception:
                pass
        self.browser = self.playwright = None

    def start_session(self, url):
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
        self._close_context_locked()  # no live session; clean slate
        try:
            self._ensure_browser_locked()
            self.context = self._new_profile_context()
        except Exception:
            # Browser died while idle (or launch failed) — rebuild once.
            self._stop_locked()
            self._ensure_browser_locked()
            self.context = self._new_profile_context()
        self.page = self.context.new_page()
        try:
            self.page.goto(url, timeout=15000, wait_until="domcontentloaded")
        except Exception:
            self._stop_locked()  # failed nav (e.g. no internet) = no session
            raise
        self.sid = "sess-%d" % int(time.time())
        self.started_at = time.time()
        self.url = url
        # Headless pages are not the foreground tab, and the compositor
        # then only produces frames on demand — the screencast starves
        # (measured 2026-10-31: 3 frames in 10 s with an animation
        # running, no polls). bring_to_front makes this the active tab
        # so the compositor produces frames on its own.
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        # Live video stream from here on: CDP screencast on the new page.
        # A failed start only falls back to per-poll screenshots.
        # Counters are per-session (screencast_stats reports this session).
        self._frame_seq = 0
        self._frame_bytes_total = 0
        self._start_screencast_locked()
        return {"sid": self.sid, "url": url, "title": self.page.title(),
                "navigated": False}

    def navigate(self, url):
        """Go to a URL in the CURRENT live session (error if none live)."""
        if self.page is None or self.sid is None:
            raise RuntimeError("no active session")
        self.page.goto(url, timeout=15000, wait_until="domcontentloaded")
        try:
            self.page.bring_to_front()
        except Exception:
            pass
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
        """Latest frame as JPEG bytes. While the CDP screencast is live,
        this is the newest screencast frame (no page.screenshot call —
        that is the whole point of the stream). When the screencast is
        off, stalled (no frame for 2s), or has not delivered a frame
        yet, fall back to a page.screenshot (JPEG) so the UI never
        freezes. Raises when no session is live (HTTP 410)."""
        if self.page is None:
            raise RuntimeError("no active session")
        if self._screencast_on:
            with self._frame_lock:
                frame = self._frame
                ts = self._frame_ts
                age = time.time() - ts if ts else 1e9
                last_fb = self._last_fallback_ts
            if frame is not None and age < 2.0:
                return frame
            # Screencast on but no fresh frame. NEVER take a blocking
            # page.screenshot on every poll: each shot saturates the
            # worker queue and starves the acks the screencast needs
            # to deliver its next frame — measured 2026-10-31, the
            # stream ran at ~0.7 fps while every poll took a shot.
            # At most one fallback shot per 2 s; between shots return
            # the cached frame (stale but correct if the page is
            # static), and the UI still refreshes at ~0.5 fps even
            # if the stream has genuinely died.
            if frame is not None and time.time() - last_fb < 2.0:
                return frame
            self._last_fallback_ts = time.time()
            shot = self.page.screenshot(type="jpeg", quality=65)
            with self._frame_lock:
                if self._frame_ts <= ts:
                    self._frame = shot
                    self._frame_ts = time.time()
            return shot
        return self.page.screenshot(type="jpeg", quality=65)

    def click(self, x, y, disp_w, disp_h, button="left"):
        if self.page is None:
            raise RuntimeError("no active session")
        if button not in ("left", "middle", "right"):
            raise ValueError("button must be left, middle or right")
        rx, ry = self._scale(x, y, disp_w, disp_h)
        self.page.mouse.click(rx, ry, button=button)
        return {"clicked": [round(rx, 1), round(ry, 1)], "button": button}

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

    # -- cookies -------------------------------------------------------------
    # POST /api/cookies injects cookies into the LIVE context with
    # context.add_cookies() — the only correct way to set HttpOnly
    # cookies (c_user, xs, fr): document.cookie cannot set them, and
    # the 2026-10-31 live test proved datr/sb/fr do not stick that way.
    # Two forms: a list of cookie objects (name, value, url or
    # domain+path, optional expires/httpOnly/secure/sameSite), or one
    # raw "name=value; name=value" string + a domain for all of them
    # (the format of the accounts files). Injected cookies persist in
    # the profile's storage_state when the session is stopped/switched,
    # so a login made this way survives a profile switch (classic mode).
    _COOKIE_ATTRS = {"expires", "max-age", "domain", "path",
                     "secure", "httponly", "samesite"}

    def get_cookies(self, domain=None):
        if self.context is None:
            raise RuntimeError("no active session")
        cookies = self.context.cookies()
        if domain:
            domain = str(domain)
            cookies = [c for c in cookies
                       if domain in (c.get("domain") or "")]
        return {"cookies": cookies, "count": len(cookies)}

    def set_cookies(self, cookies):
        if self.context is None:
            raise RuntimeError("no active session")
        if not isinstance(cookies, list) or not cookies:
            raise ValueError("cookies must be a non-empty list")
        normalized = []
        for c in cookies:
            if not isinstance(c, dict) or not c.get("name") \
                    or c.get("value") is None:
                raise ValueError("each cookie needs name and value")
            item = {"name": str(c["name"]), "value": str(c["value"])}
            if c.get("url"):
                item["url"] = str(c["url"])
            else:
                domain = str(c.get("domain") or "")
                if not domain:
                    raise ValueError("each cookie needs url or domain")
                item["domain"] = domain
                item["path"] = str(c.get("path") or "/")
            if c.get("expires") is not None:
                item["expires"] = float(c["expires"])
            if c.get("httpOnly") is not None:
                item["httpOnly"] = bool(c["httpOnly"])
            if c.get("secure") is not None:
                item["secure"] = bool(c["secure"])
            if c.get("sameSite") is not None:
                ss = str(c["sameSite"])
                if ss not in ("Strict", "Lax", "None"):
                    raise ValueError("sameSite must be Strict, Lax or None")
                item["sameSite"] = ss
            normalized.append(item)
        self.context.add_cookies(normalized)
        return {"set": len(normalized),
                "names": [c["name"] for c in normalized]}

    def set_cookies_from_string(self, cookie_string, domain):
        if self.context is None:
            raise RuntimeError("no active session")
        if not isinstance(cookie_string, str) or not cookie_string.strip():
            raise ValueError("cookie_string required")
        domain = (domain or "").strip().lstrip(".")
        if not domain:
            raise ValueError("domain required")
        cookies = []
        for part in cookie_string.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            # Skip Set-Cookie attributes if someone pastes that form.
            if not name or name.lower() in self._COOKIE_ATTRS:
                continue
            cookies.append({"name": name, "value": value,
                            "domain": "." + domain, "path": "/"})
        if not cookies:
            raise ValueError("no cookies parsed from cookie_string")
        self.context.add_cookies(cookies)
        return {"set": len(cookies),
                "names": [c["name"] for c in cookies],
                "domain": "." + domain}

    # -- file upload ---------------------------------------------------------
    # POST /api/upload feeds a server-saved file to the remote page.
    # Mode "input" (default): set_input_files on a file input
    # (selector, default input[type=file]) — no dialog involved, and it
    # works even when the input is hidden (verified 2026-10-31).
    # Mode "chooser": arms a one-time filechooser handler; the next
    # native file dialog the page opens gets the file (the Facebook
    # "Add photo" flow). The handler runs on the driver thread, so it
    # only records + enqueues the job — every Playwright call stays on
    # the worker thread (same rule as the screencast handler).
    def upload_to_input(self, path, selector):
        if self.page is None:
            raise RuntimeError("no active session")
        sel = (selector or "input[type=file]").strip() or "input[type=file]"
        self.page.locator(sel).first.set_input_files(path)
        return {"ok": True, "selector": sel}

    def _on_filechooser(self, chooser):
        """One-time filechooser handler (driver thread): only record +
        enqueue — never call Playwright APIs here."""
        try:
            self.q.put(lambda: self._apply_chooser_file(chooser))
        except Exception:
            pass

    def _apply_chooser_file(self, chooser):
        """Worker-thread job: hand the armed file to the dialog that
        just opened. A stale handler (re-armed with another file since)
        is ignored; a failure is recorded for /api/upload/status."""
        path = self._upload_path
        if not self._upload_armed or not path:
            return {"fired": False, "ignored": True}
        try:
            chooser.set_files(path)
        except Exception as e:
            self._upload_armed = False
            self._upload_error = str(e)
            return {"fired": False, "error": str(e)}
        self._upload_fired = True
        self._upload_armed = False
        self._upload_error = None
        return {"fired": True, "file": self._upload_file}

    def arm_filechooser(self, path, filename):
        if self.page is None:
            raise RuntimeError("no active session")
        self._upload_path = path
        self._upload_file = filename
        self._upload_armed = True
        self._upload_fired = False
        self._upload_error = None
        self._upload_armed_at = time.time()
        try:
            self.page.once("filechooser", self._on_filechooser)
        except Exception as e:
            self._upload_armed = False
            raise RuntimeError("could not arm filechooser: %s" % e)
        return {"armed": True, "file": filename}

    def upload_status(self):
        return {"armed": self._upload_armed,
                "fired": self._upload_fired,
                "file": self._upload_file,
                "error": self._upload_error,
                "armed_for_s": (round(time.time() - self._upload_armed_at, 1)
                                if self._upload_armed_at else 0)}

    # -- parity: select + drag ----------------------------------------------
    def select_option(self, selector, value=None, label=None, index=None):
        if self.page is None:
            raise RuntimeError("no active session")
        kwargs = {}
        if value is not None:
            kwargs["value"] = value
        if label is not None:
            kwargs["label"] = label
        if index is not None:
            kwargs["index"] = int(index)
        if not kwargs:
            raise ValueError("select needs value, label or index")
        sel = (selector or "").strip()
        if not sel:
            raise ValueError("selector required")
        result = self.page.locator(sel).first.select_option(**kwargs)
        return {"selected": result}

    def drag(self, x1, y1, x2, y2, disp_w, disp_h):
        if self.page is None:
            raise RuntimeError("no active session")
        rx1, ry1 = self._scale(x1, y1, disp_w, disp_h)
        rx2, ry2 = self._scale(x2, y2, disp_w, disp_h)
        self.page.mouse.move(rx1, ry1)
        self.page.mouse.down()
        self.page.mouse.move(rx2, ry2, steps=10)
        self.page.mouse.up()
        return {"dragged": [[round(rx1, 1), round(ry1, 1)],
                            [round(rx2, 1), round(ry2, 1)]]}

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


def _parse_multipart(raw, boundary):
    """Minimal multipart/form-data parser (one file field + text fields).
    Returns (fields: {name: str}, files: {name: (filename, bytes)}).
    Stdlib-only: cgi is deprecated/removed, so parse by hand."""
    fields, files = {}, {}
    sep = b"--" + boundary
    for chunk in raw.split(sep):
        if not chunk or chunk in (b"--", b"--\r\n", b"\r\n"):
            continue
        if b"\r\n\r\n" not in chunk:
            continue
        head, body = chunk.split(b"\r\n\r\n", 1)
        if body.endswith(b"\r\n"):
            body = body[:-2]
        headers = {}
        for line in head.decode("utf-8", "replace").split("\r\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        disp = headers.get("content-disposition", "")
        m = re.search(r'name="([^"]*)"', disp)
        if not m:
            continue
        name = m.group(1)
        fm = re.search(r'filename="([^"]*)"', disp)
        if fm is not None:
            files[name] = (fm.group(1), body)
        else:
            fields[name] = body.decode("utf-8", "replace")
    return fields, files


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

    def _handle_upload(self):
        """POST /api/upload — multipart/form-data with one file field
        ("file") plus optional text fields: selector, mode
        ("input" | "chooser"). Auth already checked by do_POST.
        Saves the file under uploads/ (sanitized basename, 20 MB cap),
        then either sets it on a file input right away or arms the
        one-time filechooser handler. Returns JSON; never echoes the
        file bytes back."""
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in ctype:
            self._send_json({"error": "multipart/form-data required"}, code=400)
            return
        m = re.search(r"boundary=([^;]+)", ctype)
        if not m:
            self._send_json({"error": "missing multipart boundary"}, code=400)
            return
        boundary = m.group(1).strip().strip('"').encode()
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > UPLOAD_MAX_BYTES + 65536:
            self._send_json({"error": "bad Content-Length"}, code=400)
            return
        raw = self.rfile.read(n)
        fields, files = _parse_multipart(raw, boundary)
        if "file" not in files:
            self._send_json({"error": "file field required"}, code=400)
            return
        filename, data = files["file"]
        if len(data) > UPLOAD_MAX_BYTES:
            self._send_json({"error": "file too large (max 20 MB)"}, code=400)
            return
        safe = re.sub(r"[^A-Za-z0-9_.\-]+", "_",
                      os.path.basename(filename) or "upload")
        if not safe or safe in (".", ".."):
            safe = "upload"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        # Opportunistic cleanup of stale uploads (>1h old).
        now = time.time()
        try:
            for old in os.listdir(UPLOAD_DIR):
                p = os.path.join(UPLOAD_DIR, old)
                try:
                    if os.path.isfile(p) and \
                            now - os.path.getmtime(p) > UPLOAD_TTL_SECONDS:
                        os.remove(p)
                except OSError:
                    pass
        except OSError:
            pass
        path = os.path.join(UPLOAD_DIR, "%d_%s" % (int(now), safe))
        with open(path, "wb") as f:
            f.write(data)
        mode = (fields.get("mode") or "input").strip().lower()
        try:
            if mode == "chooser":
                result = WORKER.call(
                    lambda: WORKER.arm_filechooser(path, safe), timeout=15)
                result["size"] = len(data)
                self._send_json(result)
            else:
                selector = fields.get("selector") or "input[type=file]"
                result = WORKER.call(
                    lambda: WORKER.upload_to_input(path, selector), timeout=30)
                result["file"] = safe
                result["size"] = len(data)
                self._send_json(result)
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": str(e)}, code=500)

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
                    img = WORKER.call(WORKER.screenshot, timeout=15)
                except Exception as e:
                    self._send_json({"error": str(e)}, code=410)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(img)))
                self.end_headers()
                self.wfile.write(img)
            elif u.path == "/api/screencast-stats":
                self._send_json(WORKER.call(WORKER.screencast_stats))
            elif u.path == "/api/info":
                try:
                    self._send_json(WORKER.call(WORKER.info, timeout=15))
                except Exception as e:
                    self._send_json({"error": str(e)}, code=410)
            elif u.path == "/api/profiles":
                self._send_json(WORKER.call(WORKER.list_profiles))
            elif u.path == "/api/cookies":
                try:
                    domain = (parse_qs(u.query).get("domain") or [None])[0]
                    self._send_json(WORKER.call(
                        lambda: WORKER.get_cookies(domain)))
                except Exception as e:
                    self._send_json({"error": str(e)}, code=410)
            elif u.path == "/api/upload/status":
                self._send_json(WORKER.call(WORKER.upload_status))
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
        # /api/upload is multipart, not JSON — handle it separately.
        if u.path == "/api/upload":
            self._handle_upload()
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
            elif u.path == "/api/profile/create":
                name = body.get("name")
                if not isinstance(name, str) or not name.strip():
                    self._send_json({"error": "name required"}, code=400)
                    return
                self._send_json(WORKER.call(
                    lambda: WORKER.create_profile(name)))
            elif u.path == "/api/profile/select":
                self._send_json(WORKER.call(
                    lambda: WORKER.select_profile(str(body.get("id") or ""))))
            elif u.path == "/api/profile/delete":
                self._send_json(WORKER.call(
                    lambda: WORKER.delete_profile(str(body.get("id") or ""))))
            elif u.path == "/api/eval":
                js = body.get("js")
                if not isinstance(js, str) or not js.strip():
                    self._send_json({"error": "js required"}, code=400)
                    return
                self._send_json(WORKER.call(
                    lambda: WORKER.evaluate(js), timeout=15))
            elif u.path == "/api/click":
                self._send_json(WORKER.call(lambda: WORKER.click(
                    float(body["x"]), float(body["y"]),
                    float(body.get("disp_w") or VIEWPORT["width"]),
                    float(body.get("disp_h") or VIEWPORT["height"]),
                    str(body.get("button") or "left")), timeout=15))
            elif u.path == "/api/cookies":
                if isinstance(body.get("cookies"), list):
                    self._send_json(WORKER.call(
                        lambda: WORKER.set_cookies(body["cookies"]), timeout=15))
                elif isinstance(body.get("cookie_string"), str):
                    self._send_json(WORKER.call(
                        lambda: WORKER.set_cookies_from_string(
                            body["cookie_string"],
                            body.get("domain") or ""), timeout=15))
                else:
                    self._send_json(
                        {"error": "cookies list or cookie_string + domain required"},
                        code=400)
            elif u.path == "/api/select":
                self._send_json(WORKER.call(lambda: WORKER.select_option(
                    str(body.get("selector") or ""),
                    body.get("value"), body.get("label"),
                    body.get("index")), timeout=15))
            elif u.path == "/api/drag":
                self._send_json(WORKER.call(lambda: WORKER.drag(
                    float(body["x1"]), float(body["y1"]),
                    float(body["x2"]), float(body["y2"]),
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
    print("Cloud Browser v6 — http://%s:%d/  (test page: /test-page.html)" % (HOST, PORT), flush=True)
    print("Full control, unlimited sessions until Stop, profiles keep separate logins, cookies + file upload, no sign-up.", flush=True)
    print("Token auth ON: every /api/* call needs X-Cloud-Token.", flush=True)
    server.serve_forever()
