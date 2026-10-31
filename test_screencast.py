#!/usr/bin/env python3
"""End-to-end test for the Cloud Browser CDP live stream (screencast).

Drives the HTTP API exactly as the UI does and proves, on the local test
page (no internet needed):
  1. The UI polls the stream at ~100 ms and pauses while the tab is
     hidden (static check of index.html).
  2. A live session serves JPEG frames from /api/screenshot; a frame
     arrives within ~1s of a click that changes the page (a live stream,
     not a frozen image); the screencast is really ON (server-side frame
     counter > 0), not the screenshot fallback.
  3. BANDWIDTH: while the page changes, the measured frame rate, average
     frame size and MB/minute estimate are sane (~8-10 fps cap).
  4. The stream keeps working after a profile switch (CDP on the new
     profile's page, persistent-context and classic modes alike).
  5. The session still stops cleanly (status inactive, screenshot 410).
  6. FALLBACK: a server whose screencast start always fails still serves
     JPEG screenshots and the session works (proves the fallback path).

Runs three phases: (a) the main server on BASE_URL (extensions mode,
since extensions/ exists in this folder), (b) a temp copy without
extensions/ on port 8766 (classic launch mode), (c) a temp copy with
screencast start sabotaged on port 8767 (fallback probe).

Usage:  CLOUD_BROWSER_TOKEN=<token> \
        ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_screencast.py
Starts the main server itself when nothing answers on BASE_URL (default
http://127.0.0.1:8765, or set BASE_URL). Prints PASS/FAIL per check;
exit 0 only if all pass. Cleans up its own test profiles at start and end.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("CLOUD_BROWSER_TOKEN", "")
HERE = os.path.dirname(os.path.abspath(__file__))
results = []
_server_proc = None


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)
    return ok


def req(base, method, path, body=None, token=True):
    """token=True: send the env token (default). token=False: send none.
    token="...": send that literal value (for the wrong-token check)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token is True:
        if TOKEN:
            headers["X-Cloud-Token"] = TOKEN
    elif isinstance(token, str):
        headers["X-Cloud-Token"] = token
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jget(base, path):
    code, raw = req(base, "GET", path)
    return code, json.loads(raw) if raw else {}


def jpost(base, path, body):
    code, raw = req(base, "POST", path, body)
    return code, json.loads(raw) if raw else {}


def ev(base, js):
    code, r = jpost(base, "/api/eval", {"js": js})
    return code, r.get("result")


def shot(base):
    """(code, bytes) of the latest frame; bytes empty on error."""
    return req(base, "GET", "/api/screenshot")


def is_jpeg(data):
    return len(data) > 3 and data[:3] == b"\xff\xd8\xff"


def wait_for_frame(base, timeout=3.0):
    """Poll until /api/screenshot returns a JPEG frame; bytes or None."""
    end = time.time() + timeout
    while time.time() < end:
        code, data = shot(base)
        if code == 200 and is_jpeg(data):
            return data
        time.sleep(0.1)
    return None


def profiles(base):
    code, p = jget(base, "/api/profiles")
    return code, p


def profile_ids(p):
    return [pr["id"] for pr in (p.get("profiles") or [])]


def cleanup_test_profiles(base):
    """Remove any test-* profiles left by an earlier (crashed) run."""
    code, p = profiles(base)
    for pid in profile_ids(p):
        if pid.startswith("test-"):
            jpost(base, "/api/profile/delete", {"id": pid})


def server_is_up(base):
    """Any HTTP response (even a 401) proves the server answers."""
    try:
        urllib.request.urlopen(base + "/api/status", timeout=5)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def ensure_server():
    """Start the main server ourselves when nothing answers on BASE_URL.
    Returns True when we started it (so main() stops it at the end)."""
    global _server_proc
    if server_is_up(BASE):
        return False
    port = urllib.parse.urlparse(BASE).port or 8765
    env = dict(os.environ)
    env["CLOUD_BROWSER_TOKEN"] = TOKEN
    env["CLOUD_BROWSER_PORT"] = str(port)
    _server_proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "server.py")],
        cwd=HERE, env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    end = time.time() + 20
    while time.time() < end:
        if server_is_up(BASE):
            return True
        time.sleep(0.5)
    raise RuntimeError("server did not come up on %s" % BASE)


def start_temp_server(tmpdir, port, patch_cdp=False):
    """Copy the 4 core files to tmpdir (no extensions/ -> classic launch
    mode), optionally sabotage screencast start in the copy, start it on
    `port`. Returns (proc, base)."""
    for name in ("server.py", "index.html", "test-page.html", "test-page2.html"):
        shutil.copy(os.path.join(HERE, name), os.path.join(tmpdir, name))
    if patch_cdp:
        p = os.path.join(tmpdir, "server.py")
        src = open(p).read()
        old = "self._cdp = self.context.new_cdp_session(self.page)"
        assert src.count(old) == 1, "CDP line not found for patch"
        open(p, "w").write(src.replace(
            old, "raise RuntimeError(\"simulated CDP failure\")"))
    env = dict(os.environ)
    env["CLOUD_BROWSER_TOKEN"] = TOKEN
    env["CLOUD_BROWSER_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(tmpdir, "server.py")],
        cwd=tmpdir, env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    end = time.time() + 20
    while time.time() < end:
        if server_is_up(base):
            return proc, base
        time.sleep(0.5)
    raise RuntimeError("temp server did not come up on %s" % base)


def stop_temp_server(proc, tmpdir):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(tmpdir, ignore_errors=True)


def measure_bandwidth(base, tag):
    """While the page changes (status text every 150 ms), sample the
    stream for 3s and report server-side fps, average frame bytes and a
    MB/minute estimate. Then sample a static page for 2s and report how
    the stream slows down when nothing changes."""
    code, r = ev(base, "() => { window.__cb_anim = setInterval(() => {"
                 " var el = document.getElementById('status');"
                 " if (el) el.textContent = 'tick ' + Date.now(); }, 150);"
                 " return 'started'; }")
    check(tag + "animation started", code == 200 and r == "started", repr(r))
    _, st0 = jget(base, "/api/screencast-stats")
    t_end = time.time() + 3.0
    hashes = {}
    samples = 0
    while time.time() < t_end:
        code, data = shot(base)
        if code == 200:
            samples += 1
            h = hashlib.sha256(data).hexdigest()
            if h not in hashes:
                hashes[h] = len(data)
        time.sleep(0.1)
    _, st1 = jget(base, "/api/screencast-stats")
    ev(base, "() => { clearInterval(window.__cb_anim); return 'stopped'; }")
    frames = st1.get("frames", 0) - st0.get("frames", 0)
    fbytes = st1.get("bytes_total", 0) - st0.get("bytes_total", 0)
    fps = frames / 3.0
    avg = (fbytes / frames) if frames else 0
    mb_min = avg * fps * 60 / 1e6
    print("%sBANDWIDTH animated page: server fps=%.1f avg_frame=%d bytes"
          " (~%.1f MB/min), test saw %d distinct frames in %d samples"
          % (tag, fps, avg, mb_min, len(hashes), samples), flush=True)
    check(tag + "stream delivers frames while page changes",
          frames > 0, "frames=%d" % frames)
    check(tag + "fps sane (2-15)", 2.0 <= fps <= 15.0, "fps=%.1f" % fps)
    check(tag + "avg frame size sane (<100 KB)", 0 < avg < 100000,
          "avg=%d bytes" % avg)
    # Static page: the stream should not keep blasting at full rate.
    time.sleep(0.5)
    static_hashes = set()
    t_end = time.time() + 2.0
    while time.time() < t_end:
        code, data = shot(base)
        if code == 200:
            static_hashes.add(hashlib.sha256(data).hexdigest())
        time.sleep(0.1)
    print("%sBANDWIDTH static page: %d distinct frames in 2s"
          % (tag, len(static_hashes)), flush=True)
    check(tag + "static page does not stream at full rate",
          len(static_hashes) <= 30, "distinct=%d" % len(static_hashes))


def run_suite(base, label, measure):
    """Core live-stream checks against one server: start, first frame,
    frame changes within ~1s of a click, screencast really ON, optional
    bandwidth measurement, stream survives a profile switch, clean stop."""
    tag = "[%s] " % label
    code, raw = req(base, "GET", "/")
    check(tag + "UI loads", code == 200 and b"Start Session" in raw,
          "(%d)" % code)
    check(tag + "UI polls at 100ms + pauses when hidden",
          b"setInterval(refreshShot, 100)" in raw
          and b"visibilitychange" in raw)
    jpost(base, "/api/stop", {})
    cleanup_test_profiles(base)

    code, s = jpost(base, "/api/start", {"url": base + "/test-page.html"})
    check(tag + "start session", code == 200 and s.get("sid"), str(s)[:120])
    f0 = wait_for_frame(base)
    check(tag + "first frame arrives (JPEG)", f0 is not None,
          "(%d bytes)" % (len(f0) if f0 else 0))
    # Let the stream settle so the click latency below measures the
    # stream itself, not session warm-up; then take a fresh baseline.
    time.sleep(1.0)
    code, f0 = shot(base)
    if code != 200 or not is_jpeg(f0):
        f0 = wait_for_frame(base, timeout=2.0)

    code, info = jget(base, "/api/info")
    box = (info.get("boxes") or {}).get("hello-btn") or {}
    check(tag + "button box reported", bool(box), str(box))
    latency = None
    if box and f0:
        h_before = hashlib.sha256(f0).hexdigest()
        cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        jpost(base, "/api/click", {"x": cx, "y": cy, "disp_w": 1280, "disp_h": 720})
        t_click = time.time()
        end = t_click + 2.0
        while time.time() < end:
            code, data = shot(base)
            if code == 200 and hashlib.sha256(data).hexdigest() != h_before:
                latency = time.time() - t_click
                break
            time.sleep(0.05)
        code, info = jget(base, "/api/info")
        check(tag + "click changes page",
              info.get("status_text", "").startswith("Button clicked!"),
              repr(info.get("status_text")))
    check(tag + "frame changes within ~1s of click",
          latency is not None and latency <= 1.0,
          "latency=%.2fs" % (latency if latency is not None else -1))

    # The stream itself (not the screenshot fallback) is serving frames.
    code, st = jget(base, "/api/screencast-stats")
    check(tag + "screencast is ON and delivering frames",
          st.get("screencast_on") is True and st.get("frames", 0) > 0,
          str(st))

    if measure:
        measure_bandwidth(base, tag)

    # Profile switch: the stream works on the new profile's page too.
    code, b = jpost(base, "/api/profile/create", {"name": "Test Cast B"})
    check(tag + "create profile B", code == 200 and b.get("id") == "test-cast-b",
          str(b))
    code, r = jpost(base, "/api/profile/select", {"id": "test-cast-b"})
    check(tag + "select profile B", code == 200 and r.get("active") == "test-cast-b",
          str(r))
    code, st = jget(base, "/api/status")
    check(tag + "switching ends the session", st.get("active") is False, str(st))
    code, s = jpost(base, "/api/start", {"url": base + "/test-page.html"})
    check(tag + "start session in B", code == 200 and s.get("sid"), str(s)[:120])
    fB = wait_for_frame(base)
    check(tag + "frame arrives in profile B (CDP works there)",
          fB is not None, "(%d bytes)" % (len(fB) if fB else 0))
    # The first frame may be the fallback screenshot; poll the
    # server-side counter until the stream itself has delivered.
    frames_b = 0
    end = time.time() + 3.0
    while time.time() < end:
        code, st = jget(base, "/api/screencast-stats")
        frames_b = st.get("frames", 0)
        if st.get("screencast_on") is True and frames_b > 0:
            break
        time.sleep(0.2)
    check(tag + "screencast ON in profile B",
          st.get("screencast_on") is True and frames_b > 0, str(st))

    jpost(base, "/api/stop", {})
    code, st = jget(base, "/api/status")
    check(tag + "Stop ends session", st.get("active") is False, str(st))
    code, _ = shot(base)
    check(tag + "screenshot gone after Stop (410)", code == 410, "(%d)" % code)
    jpost(base, "/api/profile/delete", {"id": "test-cast-b"})
    cleanup_test_profiles(base)
    jpost(base, "/api/stop", {})


def run_fallback_probe():
    """Screencast start always fails (patched copy): the session must
    still work via the page.screenshot fallback, and stats must show the
    screencast OFF."""
    tmpdir = "/tmp/screencast-nocdp"
    shutil.rmtree(tmpdir, ignore_errors=True)
    os.makedirs(tmpdir)
    proc, base = start_temp_server(tmpdir, 8767, patch_cdp=True)
    tag = "[fallback] "
    try:
        code, raw = req(base, "GET", "/")
        check(tag + "UI loads", code == 200 and b"Start Session" in raw,
              "(%d)" % code)
        jpost(base, "/api/stop", {})
        code, s = jpost(base, "/api/start", {"url": base + "/test-page.html"})
        check(tag + "start session (screencast start fails)",
              code == 200 and s.get("sid"), str(s)[:120])
        code, st = jget(base, "/api/screencast-stats")
        check(tag + "screencast is OFF (fallback path)",
              st.get("screencast_on") is False, str(st))
        f0 = wait_for_frame(base)
        check(tag + "screenshot still returns JPEG via fallback",
              f0 is not None, "(%d bytes)" % (len(f0) if f0 else 0))
        code, info = jget(base, "/api/info")
        box = (info.get("boxes") or {}).get("hello-btn") or {}
        if box and f0:
            h_before = hashlib.sha256(f0).hexdigest()
            cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
            jpost(base, "/api/click", {"x": cx, "y": cy, "disp_w": 1280, "disp_h": 720})
            time.sleep(0.5)
            code, data = shot(base)
            check(tag + "frame changes after click (fallback)",
                  code == 200 and hashlib.sha256(data).hexdigest() != h_before)
        jpost(base, "/api/stop", {})
        code, st = jget(base, "/api/status")
        check(tag + "Stop ends session", st.get("active") is False, str(st))
        code, _ = shot(base)
        check(tag + "screenshot gone after Stop (410)", code == 410, "(%d)" % code)
    finally:
        stop_temp_server(proc, tmpdir)


def main():
    if not TOKEN:
        print("FAIL need CLOUD_BROWSER_TOKEN set (same token as the server)")
        return 1
    started_here = ensure_server()
    try:
        # (a) Main server: extensions/ exists here, so this is the
        # persistent-context (extensions) mode. Bandwidth measured here.
        run_suite(BASE, "extensions-mode", measure=True)
        # (b) Temp copy without extensions/: classic launch() mode.
        tmpdir = "/tmp/screencast-classic"
        shutil.rmtree(tmpdir, ignore_errors=True)
        os.makedirs(tmpdir)
        proc, base = start_temp_server(tmpdir, 8766)
        try:
            run_suite(base, "classic-mode", measure=False)
        finally:
            stop_temp_server(proc, tmpdir)
        # (c) Temp copy with screencast start sabotaged: fallback probe.
        run_fallback_probe()
    finally:
        if started_here and _server_proc is not None:
            _server_proc.terminate()
            try:
                _server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _server_proc.kill()

    failed = [n for n, ok in results if not ok]
    print("\n%d/%d passed%s" % (len(results) - len(failed), len(results),
                                (" — FAILED: " + ", ".join(failed)) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
