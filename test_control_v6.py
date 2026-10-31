#!/usr/bin/env python3
"""End-to-end test for the Cloud Browser v6 control additions: cookie
login, file upload, select, drag, middle-click.

Drives the HTTP API exactly as the UI does and proves, on the local test
page (no internet needed):
  1. The new routes need the token (401 without / with a wrong token).
  2. Cookies / upload / select / drag need a live session (error when idle).
  3. POST /api/cookies with a raw "name=value; ..." string + domain sets
     the cookies; GET /api/cookies lists them; document.cookie shows the
     non-HttpOnly ones.
  4. POST /api/cookies with a list sets an HttpOnly cookie: it appears
     in GET /api/cookies with httpOnly true and does NOT appear in
     document.cookie (proves context.add_cookies handles HttpOnly).
  5. POST /api/upload mode "input" feeds a file to a visible AND a hidden
     file input (set_input_files works on hidden inputs).
  6. POST /api/upload mode "chooser" arms the one-time filechooser
     handler; clicking the page's upload trigger then hands the file to
     the dialog (GET /api/upload/status reports fired).
  7. POST /api/select picks a dropdown value by value.
  8. POST /api/drag produces a real mouse drag on the page.
  9. POST /api/click with button="middle" produces a middle-click.
  10. Validation: empty cookie list, missing domain, garbage cookie
      string, upload without a file, upload with a JSON body all error.

Usage:  CLOUD_BROWSER_TOKEN=test-token-123
        ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_control_v6.py
Expects the server already running on 127.0.0.1:8765 (or set BASE_URL)
with the same CLOUD_BROWSER_TOKEN. Prints PASS/FAIL per check; exit 0
only if all pass.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("CLOUD_BROWSER_TOKEN", "test-token-123")
PAGE = BASE + "/test-page.html"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)
    return ok


def req(method, path, body=None, token=TOKEN):
    """token=TOKEN send the env token (default). token=None send none.
    token="wrong" send a wrong one. Returns (status, parsed json)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Cloud-Token"] = token
    r = urllib.request.Request(BASE + path, data=data, method=method)
    for k, v in headers.items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw[:200].decode("utf-8", "replace")}


def req_multipart(path, filename, data, fields=None, token=TOKEN):
    """POST a multipart/form-data body with one file field ("file")."""
    boundary = "----cbtest%d" % int(time.time() * 1000)
    body = b""
    for k, v in (fields or {}).items():
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                 % (boundary, k, v)).encode()
    body += ("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
             "filename=\"%s\"\r\nContent-Type: text/plain\r\n\r\n"
             % (boundary, filename)).encode()
    body += data + b"\r\n--%s--\r\n" % boundary.encode()
    r = urllib.request.Request(BASE + path, data=body, method="POST")
    r.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    if token:
        r.add_header("X-Cloud-Token", token)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw[:200].decode("utf-8", "replace")}


def req_multipart_nofile(path, fields=None, token=TOKEN):
    """POST multipart with text fields only (no file field)."""
    boundary = "----cbtest%d" % int(time.time() * 1000)
    body = b""
    for k, v in (fields or {}).items():
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                 % (boundary, k, v)).encode()
    body += b"--%s--\r\n" % boundary.encode()
    r = urllib.request.Request(BASE + path, data=body, method="POST")
    r.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    if token:
        r.add_header("X-Cloud-Token", token)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw[:200].decode("utf-8", "replace")}


def ev(js):
    """Run JS in the live page via /api/eval; return the result value."""
    code, body = req("POST", "/api/eval", {"js": js})
    if code != 200:
        raise RuntimeError("eval failed: %s %s" % (code, body))
    return body.get("result")


def rect(el_id):
    """Bounding rect of an element (scrolls it into view first)."""
    return ev("() => { const el = document.getElementById('%s');"
              " el.scrollIntoView({block: 'center'});"
              " const r = el.getBoundingClientRect();"
              " return {x: r.x, y: r.y, w: r.width, h: r.height}; }" % el_id)


def main():
    # -- 0. token checks on the new routes ---------------------------------
    for method, path, body in [
            ("GET", "/api/cookies", None),
            ("GET", "/api/upload/status", None),
            ("POST", "/api/cookies", {"cookie_string": "a=b", "domain": "x"}),
            ("POST", "/api/select", {"selector": "#x", "value": "a"}),
            ("POST", "/api/drag", {"x1": 0, "y1": 0, "x2": 1, "y2": 1})]:
        code, _ = req(method, path, body, token=None)
        check("401 %s %s without token" % (method, path), code == 401, str(code))
    code, _ = req("POST", "/api/cookies",
                 {"cookie_string": "a=b", "domain": "x"}, token="wrong-token")
    check("401 POST /api/cookies with wrong token", code == 401, str(code))
    code, _ = req_multipart("/api/upload", "f.txt", b"x", token=None)
    check("401 POST /api/upload without token", code == 401, str(code))

    # -- 1. new routes need a live session ----------------------------------
    code, body = req("GET", "/api/cookies")
    check("GET /api/cookies errors with no session",
          code != 200 and "no active session" in str(body.get("error", "")), str(body))
    code, body = req("POST", "/api/cookies",
                    {"cookie_string": "a=b", "domain": "127.0.0.1"})
    check("POST /api/cookies errors with no session",
          code != 200 and "no active session" in str(body.get("error", "")), str(body))
    code, body = req_multipart("/api/upload", "f.txt", b"x")
    check("POST /api/upload errors with no session",
          code != 200 and "no active session" in str(body.get("error", "")), str(body))
    code, body = req("POST", "/api/select", {"selector": "#test-select", "value": "b"})
    check("POST /api/select errors with no session",
          code != 200 and "no active session" in str(body.get("error", "")), str(body))
    code, body = req("POST", "/api/drag", {"x1": 0, "y1": 0, "x2": 1, "y2": 1})
    check("POST /api/drag errors with no session",
          code != 200 and "no active session" in str(body.get("error", "")), str(body))

    # -- 2. start a session on the test page --------------------------------
    code, body = req("POST", "/api/start", {"url": PAGE})
    check("start session on test page", code == 200 and body.get("sid"), str(body))
    if code != 200:
        return finish()
    code, body = req("GET", "/api/status")
    check("status active after start", body.get("active") is True, str(body))

    # -- 3. cookies: raw string form ----------------------------------------
    code, body = req("POST", "/api/cookies",
                    {"cookie_string": "cb_one=hello123; cb_two=xyz",
                     "domain": "127.0.0.1"})
    check("POST /api/cookies raw string sets 2",
          code == 200 and body.get("set") == 2
          and body.get("names") == ["cb_one", "cb_two"], str(body))
    code, body = req("GET", "/api/cookies?domain=127.0.0.1")
    names = [c["name"] for c in body.get("cookies", [])]
    check("GET /api/cookies lists cb_one + cb_two",
          code == 200 and "cb_one" in names and "cb_two" in names, str(names))
    cookie_hdr = ev("() => document.cookie")
    check("document.cookie shows cb_one (non-HttpOnly)",
          "cb_one=hello123" in str(cookie_hdr), str(cookie_hdr))

    # -- 4. cookies: list form with an HttpOnly cookie ----------------------
    code, body = req("POST", "/api/cookies",
                    {"cookies": [{"name": "cb_http", "value": "secret1",
                                  "domain": "127.0.0.1", "httpOnly": True}]})
    check("POST /api/cookies list form sets HttpOnly cookie",
          code == 200 and body.get("set") == 1, str(body))
    code, body = req("GET", "/api/cookies?domain=127.0.0.1")
    by_name = {c["name"]: c for c in body.get("cookies", [])}
    check("GET /api/cookies shows cb_http httpOnly=true",
          by_name.get("cb_http", {}).get("httpOnly") is True, str(by_name.get("cb_http")))
    cookie_hdr = ev("() => document.cookie")
    check("document.cookie does NOT show cb_http (HttpOnly proof)",
          "cb_http" not in str(cookie_hdr), str(cookie_hdr))

    # -- 5. cookies: validation ---------------------------------------------
    code, body = req("POST", "/api/cookies", {"cookies": []})
    check("empty cookies list errors", code != 200, str(body))
    code, body = req("POST", "/api/cookies",
                    {"cookies": [{"name": "x", "value": "y"}]})
    check("cookie without url/domain errors", code != 200, str(body))
    code, body = req("POST", "/api/cookies",
                    {"cookie_string": ";;;", "domain": "127.0.0.1"})
    check("garbage cookie string errors", code != 200, str(body))
    code, body = req("POST", "/api/cookies", {"domain": "127.0.0.1"})
    check("cookies with neither list nor string errors", code == 400, str(body))

    # -- 6. upload: input mode, visible + hidden ----------------------------
    code, body = req_multipart("/api/upload", "cb-test.txt", b"hello upload",
                               {"selector": "#upload-input", "mode": "input"})
    check("upload to visible input ok",
          code == 200 and body.get("ok") is True, str(body))
    st = ev("() => document.getElementById('upload-status').textContent")
    check("visible input got the file", "cb-test.txt" in str(st), str(st))
    code, body = req_multipart("/api/upload", "cb-hidden.txt", b"hidden",
                               {"selector": "#upload-hidden", "mode": "input"})
    check("upload to hidden input ok",
          code == 200 and body.get("ok") is True, str(body))
    st = ev("() => document.getElementById('upload-hidden-status').textContent")
    check("hidden input got the file", "cb-hidden.txt" in str(st), str(st))

    # -- 7. upload: chooser-arm mode -----------------------------------------
    code, body = req_multipart("/api/upload", "cb-chooser.txt", b"chooser",
                               {"mode": "chooser"})
    check("chooser arm ok",
          code == 200 and body.get("armed") is True, str(body))
    ev("() => document.getElementById('upload-trigger').click()")
    fired = False
    for _ in range(10):
        time.sleep(1)
        code, st_body = req("GET", "/api/upload/status")
        if st_body.get("fired"):
            fired = True
            break
    check("chooser fired after trigger click", fired, str(st_body))
    st = ev("() => document.getElementById('upload-status').textContent")
    check("chooser handed the file to the page",
          "cb-chooser.txt" in str(st), str(st))

    # -- 8. upload: validation ----------------------------------------------
    code, body = req_multipart_nofile("/api/upload", {"mode": "input"})
    check("upload without a file errors", code == 400, str(body))
    code, body = req("POST", "/api/upload", {"file": "x"})
    check("upload with a JSON body errors", code == 400, str(body))

    # -- 9. select ------------------------------------------------------------
    code, body = req("POST", "/api/select",
                    {"selector": "#test-select", "value": "b"})
    check("select value b", code == 200 and body.get("selected") == ["b"], str(body))
    val = ev("() => document.getElementById('test-select').value")
    check("select really changed the page", val == "b", str(val))
    st = ev("() => document.getElementById('select-status').textContent")
    check("select status updated", "Selected: b" in str(st), str(st))

    # -- 10. drag --------------------------------------------------------------
    r = rect("drag-box")
    code, body = req("POST", "/api/drag",
                    {"x1": r["x"] + 20, "y1": r["y"] + r["h"] / 2,
                     "x2": r["x"] + r["w"] - 20, "y2": r["y"] + r["h"] / 2,
                     "disp_w": 1280, "disp_h": 720})
    check("drag ok", code == 200 and "dragged" in body, str(body))
    st = ev("() => document.getElementById('drag-status').textContent")
    check("page saw a real drag",
          str(st).startswith("dragged") and "moves=" in str(st)
          and int(str(st).split("moves=")[1]) > 0, str(st))

    # -- 11. middle-click -------------------------------------------------------
    r = rect("mid-box")
    code, body = req("POST", "/api/click",
                    {"x": r["x"] + r["w"] / 2, "y": r["y"] + r["h"] / 2,
                     "disp_w": 1280, "disp_h": 720, "button": "middle"})
    check("middle-click ok",
          code == 200 and body.get("button") == "middle", str(body))
    st = ev("() => document.getElementById('mid-status').textContent")
    check("page saw the middle-click", "middle-clicked!" in str(st), str(st))

    # -- 12. stop ---------------------------------------------------------------
    code, body = req("POST", "/api/stop", {})
    check("stop ok", code == 200, str(body))
    code, body = req("GET", "/api/status")
    check("status idle after stop", body.get("active") is False, str(body))
    return finish()


def finish():
    failed = [n for n, ok in results if not ok]
    print("\n%d/%d passed" % (len(results) - len(failed), len(results)), flush=True)
    if failed:
        print("FAILED: %s" % ", ".join(failed), flush=True)
        return 1
    print("ALL PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
