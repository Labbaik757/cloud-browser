#!/usr/bin/env python3
"""End-to-end test for Cloud Browser v1 — drives the HTTP API exactly as the
UI does (start -> screenshot -> click -> type -> scroll -> status), plus the
unlimited-time proof: session must still be alive after 65s, and end ONLY
on explicit Stop.

Usage:  CLOUD_BROWSER_TOKEN=<token> \
        ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_v1.py
Expects the server already running on 127.0.0.1:8765 (or set BASE_URL)
with the same CLOUD_BROWSER_TOKEN. Prints PASS/FAIL per check; exit 0
only if all pass. The token is sent as X-Cloud-Token on every request.
"""
import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("CLOUD_BROWSER_TOKEN", "")
TEST_URL = BASE + "/test-page.html"
results = []


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


def main():
    if not TOKEN:
        print("FAIL need CLOUD_BROWSER_TOKEN set (same token as the server)")
        return 1
    # 0. TOKEN AUTH: no token -> 401, wrong token -> 401, right token -> 200.
    code, raw = req("GET", "/api/status", token=False)
    check("API without token is 401", code == 401, "(%d)" % code)
    code, raw = req("GET", "/api/status", token="wrong-token")
    check("API with wrong token is 401", code == 401, "(%d)" % code)
    code, st = jget("/api/status")
    check("API with correct token works",
          code == 200 and st.get("active") is False, str(st))

    # 1. UI + test page serve
    code, raw = req("GET", "/")
    check("UI serves at /", code == 200 and b"Start Session" in raw,
          "(%d)" % code)
    check("UI has no countdown/timer", b"Time left" not in raw and b"60s" not in raw
          and b"countdown" not in raw.lower())
    code, raw = req("GET", "/test-page.html")
    check("test page serves", code == 200 and b"Cloud Browser Test Page" in raw)

    # 2. Start session (the UI flow)
    code, s = jpost("/api/start", {"url": TEST_URL})
    check("start session", code == 200 and s.get("sid"),
          str(s)[:160])
    check("start has no time limit field",
          "remaining" not in s and "SESSION_SECONDS" not in str(s))
    sid = s.get("sid")

    # 3. Page loaded in the remote browser
    code, info = jget("/api/info")
    check("remote page loaded", code == 200 and
          "Cloud Browser Test Page" in info.get("body_text", ""),
          info.get("title", ""))
    check("button not yet clicked", info.get("status_text") == "Not clicked yet.")

    # 4. Screenshot stream (live CDP screencast — JPEG frames)
    code, shot1 = req("GET", "/api/screenshot")
    check("screenshot is JPEG", code == 200 and shot1[:3] == b"\xff\xd8\xff",
          "(%d bytes)" % len(shot1))
    h1 = hashlib.sha256(shot1).hexdigest()

    # 5. Click the button (coords from the server-reported bounding box)
    box = (info.get("boxes") or {}).get("hello-btn") or {}
    check("button box reported", bool(box), str(box))
    if box:
        cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        code, c = jpost("/api/click", {"x": cx, "y": cy, "disp_w": 1280, "disp_h": 720})
        time.sleep(0.5)
        code, info = jget("/api/info")
        check("click button changes page",
              info.get("status_text", "").startswith("Button clicked!"),
              repr(info.get("status_text")))
    code, shot2 = req("GET", "/api/screenshot")
    check("screenshot changes after click",
          hashlib.sha256(shot2).hexdigest() != h1)

    # 6. Click input + type
    box = (info.get("boxes") or {}).get("name") or {}
    if box:
        cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        jpost("/api/click", {"x": cx, "y": cy, "disp_w": 1280, "disp_h": 720})
        time.sleep(0.3)
    code, t = jpost("/api/type", {"text": "Afnan"})
    time.sleep(0.3)
    code, info = jget("/api/info")
    check("type into input", info.get("name_value") == "Afnan",
          repr(info.get("name_value")))

    # 7. Scroll
    code, shot3 = req("GET", "/api/screenshot")
    jpost("/api/scroll", {"dy": 800})
    time.sleep(0.8)
    code, shot4 = req("GET", "/api/screenshot")
    check("scroll changes screenshot",
          hashlib.sha256(shot4).hexdigest() != hashlib.sha256(shot3).hexdigest())

    # 8. UNLIMITED TIME — session must stay alive past 60s
    t0 = time.time()
    alive_at_65 = False
    while time.time() - t0 < 70:
        code, st = jget("/api/status")
        elapsed = st.get("elapsed", 0)
        if elapsed >= 65 and st.get("active"):
            alive_at_65 = True
            break
        time.sleep(5)
    check("session ALIVE past 65s (no auto-destroy)",
          alive_at_65, "elapsed=%s active=%s" % (
              st.get("elapsed"), st.get("active")))

    # 9. Explicit Stop is the ONLY way it ends
    code, r = jpost("/api/stop", {})
    code, st = jget("/api/status")
    check("Stop ends session", st.get("active") is False, str(st))
    code, _ = req("GET", "/api/screenshot")
    check("screenshot gone after Stop", code == 410, "(%d)" % code)

    failed = [n for n, ok in results if not ok]
    print("\n%d/%d passed%s" % (len(results) - len(failed), len(results),
                                (" — FAILED: " + ", ".join(failed)) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
