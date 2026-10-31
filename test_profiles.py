#!/usr/bin/env python3
"""End-to-end test for the Cloud Browser multi-profile system.

Drives the HTTP API exactly as the UI does and proves, on the local test
page (no internet needed):
  1. A "default" profile always exists and is active at first.
  2. Creating profiles (slug ids, duplicate names get -2, empty name 400).
  3. ISOLATION: a localStorage marker set in profile A is invisible in
     profile B, and vice versa.
  4. PERSISTENCE: switching A -> B -> A brings back A's own marker.
  5. Switching ends the live session (status goes idle).
  6. Deleting the active profile falls back to "default"; "default"
     cannot be deleted; unknown ids error.
  7. Profile routes need the token (401 without / with a wrong token).

State is saved via Playwright storage_state (profiles/<id>.json) when a
session is stopped or the profile is switched away, and reloaded when
the profile becomes active. The test uses /api/eval (token-authenticated)
to set/read a localStorage marker in the remote page.

Usage:  CLOUD_BROWSER_TOKEN=<token> \
        ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_profiles.py
Expects the server already running on 127.0.0.1:8765 (or set BASE_URL)
with the same CLOUD_BROWSER_TOKEN. Prints PASS/FAIL per check; exit 0
only if all pass. Cleans up its own test profiles at start and end.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("CLOUD_BROWSER_TOKEN", "")
PAGE = BASE + "/test-page.html"
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


def profiles():
    code, p = jget("/api/profiles")
    return code, p


def profile_ids(p):
    return [pr["id"] for pr in (p.get("profiles") or [])]


def ev(js):
    """Run JS in the live page via /api/eval; return the result value."""
    code, r = jpost("/api/eval", {"js": js})
    return code, r.get("result")


def set_marker(value):
    code, r = ev("() => { localStorage.setItem('profile-marker', %s);"
                 " return 'ok'; }" % json.dumps(value))
    return code == 200 and r == "ok"


def get_marker():
    code, r = ev("() => localStorage.getItem('profile-marker')")
    return r


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


def main():
    if not TOKEN:
        print("FAIL need CLOUD_BROWSER_TOKEN set (same token as the server)")
        return 1
    # 0. TOKEN AUTH on the profile routes.
    code, raw = req("GET", "/api/profiles", token=False)
    check("profiles without token is 401", code == 401, "(%d)" % code)
    code, raw = req("GET", "/api/profiles", token="wrong-token")
    check("profiles with wrong token is 401", code == 401, "(%d)" % code)

    # 1. UI serves with the profile controls.
    code, raw = req("GET", "/")
    check("UI has profile selector", code == 200 and b'id="profile-select"' in raw)
    check("UI has New/Delete profile buttons",
          b'id="profile-new"' in raw and b'id="profile-delete"' in raw)

    # 2. Eval needs a session (negative check before any session exists).
    code, r = jpost("/api/eval", {"js": "() => 1"})
    check("eval with no session errors", code in (400, 500) or "error" in r,
          str(r)[:120])

    cleanup_test_profiles()

    # 3. The default profile always exists and is active first.
    code, p = profiles()
    check("default profile exists", code == 200 and "default" in profile_ids(p),
          str(p)[:200])
    check("default is active first", p.get("active") == "default",
          str(p.get("active")))

    # 4. Create two profiles; slugs come from the names.
    code, a = jpost("/api/profile/create", {"name": "Test Alpha"})
    check("create profile A", code == 200 and a.get("id") == "test-alpha",
          str(a))
    code, b = jpost("/api/profile/create", {"name": "Test Beta"})
    check("create profile B", code == 200 and b.get("id") == "test-beta",
          str(b))
    code, p = profiles()
    check("list shows all three profiles",
          profile_ids(p) == ["default", "test-alpha", "test-beta"],
          str(profile_ids(p)))

    # 5. Duplicate name gets a -2 slug; empty name is a 400.
    code, dup = jpost("/api/profile/create", {"name": "Test Alpha"})
    check("duplicate name gets -2 slug",
          code == 200 and dup.get("id") == "test-alpha-2", str(dup))
    code, r = jpost("/api/profile/delete", {"id": "test-alpha-2"})
    check("cleanup of duplicate profile", code == 200 and r.get("ok") is True,
          str(r))
    code, r = jpost("/api/profile/create", {"name": "   "})
    check("create with empty name errors",
          code == 400 or "error" in r, "(%d) %s" % (code, str(r)[:120]))

    # 6. Unknown ids error; default cannot be deleted.
    code, r = jpost("/api/profile/select", {"id": "no-such-profile"})
    check("select unknown profile errors", "error" in r, str(r)[:120])
    code, r = jpost("/api/profile/delete", {"id": "default"})
    check("delete default errors", "error" in r, str(r)[:120])
    code, r = jpost("/api/profile/delete", {"id": "no-such-profile"})
    check("delete unknown profile errors", "error" in r, str(r)[:120])

    # 7. Profile A: start a session, set marker 'A'.
    code, r = jpost("/api/profile/select", {"id": "test-alpha"})
    check("select profile A", code == 200 and r.get("active") == "test-alpha",
          str(r))
    code, s = start()
    check("start session in A", code == 200 and s.get("sid"), str(s)[:120])
    check("set marker A", set_marker("A"))
    check("marker A reads back", get_marker() == "A", repr(get_marker()))

    # 8. Switch to B: session ends (idle), B sees NO marker (isolation).
    code, r = jpost("/api/profile/select", {"id": "test-beta"})
    check("select profile B", code == 200 and r.get("active") == "test-beta"
          and r.get("switched") is True, str(r))
    code, st = jget("/api/status")
    check("switching ends the session", st.get("active") is False, str(st))
    code, s = start()
    check("start session in B", code == 200 and s.get("sid"), str(s)[:120])
    check("B has no A marker (isolation)", get_marker() is None,
          repr(get_marker()))
    check("set marker B", set_marker("B"))
    check("marker B reads back", get_marker() == "B", repr(get_marker()))

    # 9. Switch back to A: A's marker is back, B's is not there.
    code, r = jpost("/api/profile/select", {"id": "test-alpha"})
    check("select profile A again", code == 200 and r.get("active") == "test-alpha",
          str(r))
    code, st = jget("/api/status")
    check("switching ends session again", st.get("active") is False, str(st))
    code, s = start()
    check("start session in A again", code == 200 and s.get("sid"),
          str(s)[:120])
    check("A marker persisted across switches", get_marker() == "A",
          repr(get_marker()))

    # 10. And back to B once more: B's marker persisted too.
    jpost("/api/profile/select", {"id": "test-beta"})
    code, s = start()
    check("start session in B again", code == 200 and s.get("sid"),
          str(s)[:120])
    check("B marker persisted across switches", get_marker() == "B",
          repr(get_marker()))

    # 11. Delete the ACTIVE profile (B): falls back to default.
    stop()
    code, r = jpost("/api/profile/delete", {"id": "test-beta"})
    check("delete active profile falls back to default",
          code == 200 and r.get("ok") is True and r.get("active") == "default",
          str(r))
    code, p = profiles()
    check("B gone from the list", "test-beta" not in profile_ids(p),
          str(profile_ids(p)))

    # 12. Delete A (not active); only default remains.
    code, r = jpost("/api/profile/delete", {"id": "test-alpha"})
    check("delete profile A", code == 200 and r.get("ok") is True, str(r))
    code, p = profiles()
    check("only default remains",
          profile_ids(p) == ["default"] and p.get("active") == "default",
          str(p))

    cleanup_test_profiles()
    stop()

    failed = [n for n, ok in results if not ok]
    print("\n%d/%d passed%s" % (len(results) - len(failed), len(results),
                                (" — FAILED: " + ", ".join(failed)) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
