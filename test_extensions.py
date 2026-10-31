#!/usr/bin/env python3
"""End-to-end test for the Cloud Browser extension system.

Drives the HTTP API exactly as the UI does and proves, on the local test
page (no internet needed):
  1. The test extension (extensions/cb-test/) loads into the remote
     browser: its content script sets data-cb-ext="loaded" on every page
     and adds a "CloudBrowser Ext ON" badge.
  2. The marker survives a page reload in the same session.
  3. The marker is still present after switching to another profile and
     back — extensions are browser-level, so they must survive profile
     switches (each profile runs in its own persistent context).

Usage:  CLOUD_BROWSER_TOKEN=<token> \
        ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_extensions.py
Starts the server itself when nothing answers on BASE_URL (default
http://127.0.0.1:8765, or set BASE_URL); if a server is already running
there it uses it (and leaves it running). Prints PASS/FAIL per check;
exit 0 only if all pass. Cleans up its own test profiles at start and end.
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("CLOUD_BROWSER_TOKEN", "")
PAGE = BASE + "/test-page.html"
HERE = os.path.dirname(os.path.abspath(__file__))
results = []
_server_proc = None


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)
    return ok


def req(method, path, body=None, token=True):
    """token=True: send the env token (default). token=False: send none.
    token="...": send that literal value (for the wrong-token check)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token is True:
        if TOKEN:
            headers["X-Cloud-Token"] = TOKEN
    elif isinstance(token, str):
        headers["X-Cloud-Token"] = token
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jget(path):
    code, raw = req("GET", path)
    return code, json.loads(raw) if raw else {}


def jpost(path, body):
    code, raw = req("POST", path, body)
    return code, json.loads(raw) if raw else {}


def profiles():
    code, p = jget("/api/profiles")
    return code, p


def profile_ids(p):
    return [pr["id"] for pr in (p.get("profiles") or [])]


def ev(js):
    """Run JS in the live page via /api/eval; return the result value."""
    code, r = jpost("/api/eval", {"js": js})
    return code, r.get("result")


def get_marker():
    code, r = ev("() => document.documentElement.getAttribute('data-cb-ext')")
    return r


def get_badge_text():
    code, r = ev("() => { var b = document.getElementById('cb-ext-badge');"
                 " return b ? b.textContent : null; }")
    return r


def wait_for_marker(timeout=10.0):
    """Poll for the extension marker; content scripts run just after the
    page loads, so give the extension a moment."""
    end = time.time() + timeout
    while time.time() < end:
        if get_marker() == "loaded":
            return True
        time.sleep(0.5)
    return False


def start():
    code, s = jpost("/api/start", {"url": PAGE})
    time.sleep(0.5)
    return code, s


def stop():
    jpost("/api/stop", {})
    time.sleep(0.3)


def cleanup_test_profiles():
    """Remove any test-* profiles left by an earlier (crashed) run."""
    code, p = profiles()
    for pid in profile_ids(p):
        if pid.startswith("test-"):
            jpost("/api/profile/delete", {"id": pid})


def server_is_up():
    """Any HTTP response (even a 401) proves the server answers."""
    try:
        urllib.request.urlopen(BASE + "/api/status", timeout=5)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def ensure_server():
    """Start the server ourselves when nothing answers on BASE_URL.
    Returns True when we started it (so main() stops it at the end)."""
    global _server_proc
    if server_is_up():
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
        if server_is_up():
            return True
        time.sleep(0.5)
    raise RuntimeError("server did not come up on %s" % BASE)


def main():
    if not TOKEN:
        print("FAIL need CLOUD_BROWSER_TOKEN set (same token as the server)")
        return 1
    started_here = ensure_server()
    try:
        return run_checks()
    finally:
        if started_here and _server_proc is not None:
            _server_proc.terminate()
            try:
                _server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _server_proc.kill()


def run_checks():
    # 0. UI serves (sanity) and any stale session is stopped, so the
    # browser relaunches fresh WITH the current extensions/ contents.
    code, raw = req("GET", "/")
    check("UI loads", code == 200, "(%d)" % code)
    stop()
    cleanup_test_profiles()

    # 1. Start a session on the local test page.
    code, s = start()
    check("start session", code == 200 and s.get("sid"), str(s)[:120])

    # 2. The extension marker is present on the page.
    check("extension marker data-cb-ext=loaded", wait_for_marker(),
          repr(get_marker()))

    # 3. The badge element exists and reads "CloudBrowser Ext ON".
    badge = get_badge_text()
    check("badge exists with right text",
          badge is not None and "CloudBrowser Ext ON" in badge, repr(badge))

    # 4. The marker survives a page reload in the same session.
    code, r = jpost("/api/reload", {})
    check("reload ok", code == 200 and r.get("ok") is True, str(r)[:120])
    check("marker survives reload", wait_for_marker(),
          repr(get_marker()))

    # 5. Switch to another profile: session ends, marker still loads there.
    code, b = jpost("/api/profile/create", {"name": "Test Ext B"})
    check("create profile B", code == 200 and b.get("id") == "test-ext-b",
          str(b))
    code, r = jpost("/api/profile/select", {"id": "test-ext-b"})
    check("select profile B", code == 200 and r.get("active") == "test-ext-b",
          str(r))
    code, st = jget("/api/status")
    check("switching ends the session", st.get("active") is False, str(st))
    code, s = start()
    check("start session in B", code == 200 and s.get("sid"), str(s)[:120])
    check("marker present in profile B", wait_for_marker(),
          repr(get_marker()))
    badge = get_badge_text()
    check("badge present in profile B",
          badge is not None and "CloudBrowser Ext ON" in badge, repr(badge))

    # 6. Switch back to default: the marker is there too.
    code, r = jpost("/api/profile/select", {"id": "default"})
    check("select default again", code == 200 and r.get("active") == "default",
          str(r))
    code, s = start()
    check("start session in default again", code == 200 and s.get("sid"),
          str(s)[:120])
    check("marker present in default again", wait_for_marker(),
          repr(get_marker()))

    # 7. Cleanup: delete the test profile, stop the session.
    stop()
    code, r = jpost("/api/profile/delete", {"id": "test-ext-b"})
    check("delete profile B", code == 200 and r.get("ok") is True, str(r))
    code, p = profiles()
    check("only default remains", profile_ids(p) == ["default"],
          str(profile_ids(p)))

    cleanup_test_profiles()
    stop()

    failed = [n for n, ok in results if not ok]
    print("\n%d/%d passed%s" % (len(results) - len(failed), len(results),
                                (" — FAILED: " + ", ".join(failed)) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
