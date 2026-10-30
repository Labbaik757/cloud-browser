#!/usr/bin/env python3
"""End-to-end test for Cloud Browser v2 — FULL CONTROL.

Drives the HTTP API exactly as the v2 UI does and proves every new control
on the local test pages (no internet needed):
  1. Direct keyboard: keydown/keyup typing lands in the input, Backspace,
     ArrowLeft, Tab (focus moves), Ctrl+A (select-all + replace), Escape.
  2. Back / Forward / Reload on the SAME session (no restart, same sid).
  3. Navigate in the same session via /api/start and /api/navigate
     (same sid, no new session).
  4. Right-click and double-click register on their targets.
  5. Hover registers on the hover box.
  6. Session stays alive; Stop is still the only way it ends.

Usage:  CLOUD_BROWSER_TOKEN=<token> \
        ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_v2.py
Expects the server already running on 127.0.0.1:8765 (or set BASE_URL)
with the same CLOUD_BROWSER_TOKEN. Prints PASS/FAIL per check; exit 0
only if all pass. The token is sent as X-Cloud-Token on every request.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("CLOUD_BROWSER_TOKEN", "")
PAGE1 = BASE + "/test-page.html"
PAGE2 = BASE + "/test-page2.html"
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


def box_center(info, name):
    b = (info.get("boxes") or {}).get(name) or {}
    if not b:
        return None
    return {"x": b["x"] + b["w"] / 2, "y": b["y"] + b["h"] / 2,
            "disp_w": 1280, "disp_h": 720}


def key(k, **mods):
    """One full key press via the direct-keyboard API (keydown + keyup)."""
    body = {"key": k}
    body.update(mods)
    jpost("/api/keydown", body)
    time.sleep(0.05)
    jpost("/api/keyup", body)
    time.sleep(0.05)


def type_direct(text):
    for ch in text:
        key(ch)


def main():
    if not TOKEN:
        print("FAIL need CLOUD_BROWSER_TOKEN set (same token as the server)")
        return 1
    # -1. TOKEN AUTH: no token -> 401, wrong token -> 401, right token -> 200.
    code, raw = req("GET", "/api/status", token=False)
    check("API without token is 401", code == 401, "(%d)" % code)
    code, raw = req("GET", "/api/status", token="wrong-token")
    check("API with wrong token is 401", code == 401, "(%d)" % code)
    code, raw = req("GET", "/api/screenshot", token=False)
    check("screenshot without token is 401", code == 401, "(%d)" % code)
    code, st = jget("/api/status")
    check("API with correct token works",
          code == 200 and st.get("active") is False, str(st))

    # 0. Negative checks: nav controls with NO session must fail cleanly.
    code, r = jpost("/api/navigate", {"url": PAGE1})
    check("navigate with no session errors", code in (400, 500) or "error" in r,
          str(r)[:120])
    code, r = jpost("/api/back", {})
    check("back with no session errors", code in (400, 500) or "error" in r,
          str(r)[:120])

    # 1. UI + test pages serve; v2 controls present; still no timer.
    code, raw = req("GET", "/")
    check("UI serves at /", code == 200 and b"Start Session" in raw, "(%d)" % code)
    check("UI has Back/Forward/Reload/Go",
          b'id="back"' in raw and b'id="forward"' in raw
          and b'id="reload"' in raw and b'id="go"' in raw)
    check("UI has no countdown/timer", b"Time left" not in raw and b"60s" not in raw
          and b"countdown" not in raw.lower())
    code, raw = req("GET", "/test-page2.html")
    check("test page 2 serves", code == 200 and b"Test Page 2" in raw)

    # 2. Start session on page 1.
    code, s = jpost("/api/start", {"url": PAGE1})
    check("start session", code == 200 and s.get("sid"), str(s)[:160])
    sid = s.get("sid")
    check("fresh start is not a navigation", s.get("navigated") is False)

    # 3. DIRECT KEYBOARD: click the input, type "Bob" key by key.
    code, info = jget("/api/info")
    c = box_center(info, "name")
    check("input box reported", c is not None, str(c))
    if c:
        jpost("/api/click", c)
        time.sleep(0.3)
    type_direct("Bob")
    time.sleep(0.3)
    code, info = jget("/api/info")
    check("direct typing lands in input", info.get("name_value") == "Bob",
          repr(info.get("name_value")))

    # 4. Backspace deletes one char; ArrowLeft + type inserts mid-word.
    key("Backspace")
    time.sleep(0.2)
    code, info = jget("/api/info")
    check("Backspace deletes", info.get("name_value") == "Bo",
          repr(info.get("name_value")))
    key("ArrowLeft")
    time.sleep(0.2)
    type_direct("X")
    time.sleep(0.2)
    code, info = jget("/api/info")
    check("ArrowLeft + type inserts mid-word", info.get("name_value") == "BXo",
          repr(info.get("name_value")))

    # 5. Ctrl+A selects all, typing replaces it. Escape is a no-op, no crash.
    jpost("/api/keydown", {"key": "Control"})
    time.sleep(0.05)
    jpost("/api/keydown", {"key": "a", "ctrl": True})
    time.sleep(0.05)
    jpost("/api/keyup", {"key": "a", "ctrl": True})
    time.sleep(0.05)
    jpost("/api/keyup", {"key": "Control"})
    time.sleep(0.1)
    type_direct("Z")
    time.sleep(0.2)
    code, info = jget("/api/info")
    check("Ctrl+A + type replaces all", info.get("name_value") == "Z",
          repr(info.get("name_value")))
    key("Escape")
    code, st = jget("/api/status")
    check("Escape: session still alive", st.get("active") is True, str(st))

    # 6. Tab moves focus from the input to the next control (the button).
    key("Tab")
    time.sleep(0.2)
    code, info = jget("/api/info")
    check("Tab moves focus to button", info.get("active_element") == "hello-btn",
          repr(info.get("active_element")))

    # 7. NAVIGATE IN SESSION: /api/start on a live session keeps the sid.
    code, s2 = jpost("/api/start", {"url": PAGE2})
    check("start on live session keeps sid",
          code == 200 and s2.get("sid") == sid and s2.get("navigated") is True,
          str(s2)[:160])
    code, info = jget("/api/info")
    check("navigated to page 2", info.get("title") == "Cloud Browser Test Page 2"
          and info.get("url", "").endswith("/test-page2.html"),
          info.get("title", "") + " " + info.get("url", ""))
    code, s3 = jpost("/api/navigate", {"url": PAGE1})
    check("navigate endpoint keeps sid",
          code == 200 and s3.get("sid") == sid, str(s3)[:160])
    code, info = jget("/api/info")
    check("navigated back to page 1", info.get("title") == "Cloud Browser Test Page"
          and info.get("url", "").endswith("/test-page.html"),
          info.get("title", ""))

    # 8. BACK / FORWARD on the same session (same sid throughout).
    jpost("/api/navigate", {"url": PAGE2})
    time.sleep(0.3)
    code, b = jpost("/api/back", {})
    time.sleep(0.3)
    code, info = jget("/api/info")
    check("Back returns to page 1",
          info.get("url", "").endswith("/test-page.html"),
          info.get("url", "") + " " + str(b)[:120])
    code, f = jpost("/api/forward", {})
    time.sleep(0.3)
    code, info = jget("/api/info")
    check("Forward returns to page 2",
          info.get("url", "").endswith("/test-page2.html"),
          info.get("url", "") + " " + str(f)[:120])
    code, st = jget("/api/status")
    check("sid unchanged through Back/Forward", st.get("sid") == sid,
          "sid=%s" % st.get("sid"))

    # 9. RELOAD resets the page state (button status + input value).
    jpost("/api/navigate", {"url": PAGE1})
    time.sleep(0.3)
    code, info = jget("/api/info")
    c = box_center(info, "hello-btn")
    if c:
        jpost("/api/click", c)
        time.sleep(0.4)
    code, info = jget("/api/info")
    check("button clicked before reload",
          (info.get("status_text") or "").startswith("Button clicked!"),
          repr(info.get("status_text")))
    code, r = jpost("/api/reload", {})
    time.sleep(0.5)
    code, info = jget("/api/info")
    check("Reload resets page state",
          info.get("status_text") == "Not clicked yet."
          and (info.get("name_value") in (None, "")),
          repr(info.get("status_text")) + " / " + repr(info.get("name_value")))

    # 10. HOVER: moving the mouse over the hover box changes its text.
    code, info = jget("/api/info")
    c = box_center(info, "hover-box")
    check("hover box reported", c is not None, str(c))
    if c:
        jpost("/api/hover", c)
        time.sleep(0.4)
    code, info = jget("/api/info")
    check("hover registers", info.get("hover_status") == "Hovered!",
          repr(info.get("hover_status")))

    # 11. RIGHT-CLICK registers on its target.
    code, info = jget("/api/info")
    c = box_center(info, "ctx-box")
    check("right-click box reported", c is not None, str(c))
    if c:
        jpost("/api/rightclick", c)
        time.sleep(0.4)
    code, info = jget("/api/info")
    check("right-click registers", info.get("ctx_status") == "Right-clicked!",
          repr(info.get("ctx_status")))

    # 12. DOUBLE-CLICK registers on its target.
    code, info = jget("/api/info")
    c = box_center(info, "dbl-box")
    check("double-click box reported", c is not None, str(c))
    if c:
        jpost("/api/dblclick", c)
        time.sleep(0.4)
    code, info = jget("/api/info")
    check("double-click registers", info.get("dbl_status") == "Double-clicked!",
          repr(info.get("dbl_status")))

    # 13. Session still alive; Stop is still the only way it ends.
    code, st = jget("/api/status")
    check("session alive after all v2 controls", st.get("active") is True,
          str(st))
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
