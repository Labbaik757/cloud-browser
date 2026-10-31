# TEST-REPORT.md — Cloud Browser v2 (full control)

Date: 2026-10-30. Tester: automated scripts `test_v1.py` + `test_v2.py`
(driving the HTTP API exactly as the UI does) + manual curl checks. All
commands run with `~/workspace/fbvenv/bin/python` (Python 3.12.3, Playwright
+ Chromium 1248 from `~/.cache/ms-playwright/`).

## TOKEN AUTH — 2026-10-30 ~20:45 PKT (public link must not be open to anyone)

Afnan's correction: Muse uses the cloud browser by opening its public link
directly in her own browser and driving the page with her native
capabilities — **no more control-code features were added.** The server is
only the plumbing the tunnel exposes. What was missing: any auth at all.
Now added:

- **Choice: refuse to start without a token** (safer than auto-generating
  one — a generated token printed to a console can be missed or logged).
  Token comes ONLY from env `CLOUD_BROWSER_TOKEN`; never hardcoded, never
  written to any file by the server.
- **Every `/api/*` route checks it** — header `X-Cloud-Token`, or `?token=`
  query fallback; constant-time compare (`hmac.compare_digest`).
  Wrong/missing token = `401 {"error": "unauthorized"}` — no session data
  in the body, and the check happens BEFORE reading the POST body.
- **UI asks once** (Unlock box, password field), keeps the token in
  memory only — never localStorage, never in the URL — and sends it with
  every API call (including the screenshot fetch).
- Unlimited sessions unchanged: no timer, no auto-destroy. All v2 controls
  still work (regression-tested below).

Test commands:

```bash
~/workspace/fbvenv/bin/python -m py_compile server.py test_v1.py test_v2.py
~/workspace/fbvenv/bin/python server.py; echo "NO-TOKEN-EXIT:$?"  # expect 2
CLOUD_BROWSER_TOKEN=test-token-123 setsid ~/workspace/fbvenv/bin/python server.py > /tmp/cloud-browser-server.log 2>&1 < /dev/null &
curl -s http://127.0.0.1:8765/api/status                                          # 401 unauthorized
curl -s -H "X-Cloud-Token: test-token-123" http://127.0.0.1:8765/api/status     # 200 {"active": false}
curl -s "http://127.0.0.1:8765/api/status?token=test-token-123"               # 200 {"active": false}
curl -s "http://127.0.0.1:8765/api/status?token=wrong"                      # 401 unauthorized
CLOUD_BROWSER_TOKEN=test-token-123 ~/workspace/fbvenv/bin/python test_v2.py; echo "TEST-V2-EXIT:$?"
CLOUD_BROWSER_TOKEN=test-token-123 ~/workspace/fbvenv/bin/python test_v1.py; echo "TEST-V1-EXIT:$?"
```

Results:

- No-token start: refuses, **exit 2**, clear stderr error. PASS.
- UI serves 200; `/api/status` without token **401**; with token **200**;
  `?token=` right **200**, wrong **401**. PASS.
- UI contains token password input + Unlock button and sends
  `X-Cloud-Token` on API calls. PASS.
- **v2 suite: 37/37 passed, exit 0** — the 33 v2 controls plus 4 new auth
  checks (no-token 401, wrong-token 401, screenshot no-token 401,
  correct token 200).
- **v1 suite: 19/19 passed, exit 0** — the 16 v1 checks plus 3 new auth
  checks, including session ALIVE past 65s (elapsed=67, no auto-destroy).
- **Combined: 56/56 passed. No regressions.**
- Cleanup: test server stopped (`pkill`), port 8765 verified down
  (connection refused). No session data remains. Mediora untouched.
  Nothing deployed live; no Cloudflare/Render account created; no
  tunnel run here (this VM cannot do it meaningfully).

## PROFILES — multi-profile system (separate isolated logins), 2026-10-31

Afnan asked: can this have a multi-profile system? Yes — built into
`server.py` + `index.html`, no new dependencies:

- **Profiles:** id (slug of the name, e.g. `facebook-work`) + display
  name. `default` always exists, cannot be deleted. Registry in
  `profiles.json`, each profile's cookies + localStorage in
  `profiles/<id>.json` (Playwright `storage_state`).
- **One active context at a time** (Render free: 512 MB). Switching
  saves the old profile's state, closes its context, ends the session
  (status idle); the next Start opens the new profile's context with
  its saved state. The browser process itself stays alive across
  switches (fast restart); Stop still destroys everything, as before.
- **New endpoints** (same token auth as everything else):
  `GET /api/profiles`, `POST /api/profile/create|select|delete`,
  plus `POST /api/eval` (run a JS expression in the live page —
  test/debug helper the profile test uses for localStorage markers).
- **UI:** Profile dropdown + New (prompt for name, switches into it)
  + Delete (confirm; active-profile delete falls back to `default`),
  above the URL bar. Unlock box, URL bar and every v2 control
  untouched. A new session in the new profile starts on the test page.
- **Honest limit:** on Render free the disk is ephemeral — profiles
  reset when the service restarts or sleeps. On the laptop they persist
  in `profiles/`. State saves on switch/Stop, not on a killed server.
  `profiles/`, `profiles.json` and `port.txt` are now in
  `.dockerignore` (runtime state, never shipped in the image).

Test commands:

```bash
~/workspace/fbvenv/bin/python -m py_compile server.py test_profiles.py
CLOUD_BROWSER_TOKEN=test-token-123 setsid ~/workspace/fbvenv/bin/python server.py > /tmp/cloud-browser-server.log 2>&1 < /dev/null &
CLOUD_BROWSER_TOKEN=test-token-123 ~/workspace/fbvenv/bin/python test_profiles.py; echo "TEST-PROFILES-EXIT:$?"
CLOUD_BROWSER_TOKEN=test-token-123 ~/workspace/fbvenv/bin/python test_v2.py; echo "TEST-V2-EXIT:$?"
CLOUD_BROWSER_TOKEN=test-token-123 ~/workspace/fbvenv/bin/python test_v1.py; echo "TEST-V1-EXIT:$?"
```

Results — 2026-10-31, server started clean (no `profiles/` on disk):

- **Profiles suite: 36/36 passed, exit 0 (~5s).** Auth 401s on
  `/api/profiles`; UI has selector + New/Delete; `default` exists and
  is active first; create A (`test-alpha`) + B (`test-beta`); duplicate
  name gets `test-alpha-2`; empty name 400; unknown select/delete
  error; delete `default` errors. Isolation: marker `A` set in profile
  A is invisible in B (`None`), marker `B` invisible in A. Persistence:
  A → B → A returns marker `A`, B → A → B returns marker `B`.
  Switching ends the session both times (status inactive). Deleting
  the active profile (B) falls back to `default`; deleting A leaves
  only `default`. On-disk check after the run: `profiles/` empty,
  `profiles.json` holds only `default` (test profiles cleaned up).
- **v2 regression: 37/37 passed, exit 0** — identical to the 2026-10-30
  run (33 v2 controls + 4 auth checks). No regressions.
- **v1 regression: 19/19 passed, exit 0** — identical, including
  session ALIVE past 65s (elapsed=67, no auto-destroy) and Stop ending
  the session. No regressions.
- **Combined: 92/92 passed.** Cleanup: test server stopped by PID
  kill, port 8765 verified free; `profiles/`, `profiles.json` and
  `port.txt` removed so the folder ships clean. Mediora untouched.

## v2 — what changed (Afnan: "tumhain sirf screenshot dikhy ga — tum usay
control kar sako, everything")

v1 was watch-only plus basic click/type/scroll. v2 adds full control, all
through the same Playwright worker-thread queue (no Playwright calls from
the HTTP thread):
- Direct keyboard: keydown/keyup on the focused live view forwarded to the
  remote page (letters, Backspace, Delete, Tab, Escape, arrows, Enter,
  Ctrl+A/C/V/X combos). Old type-box kept as backup.
- Right-click (contextmenu, no local browser menu) and double-click.
- Back / Forward / Reload on the SAME session (no restart, same sid).
- Navigate in the same session: URL bar + Go on a live session does
  page.goto in that session (same sid); Start creates only when none live.
- Hover: mousemove forwarded (throttled in the UI, 60 ms / 8 px).
- Unlimited time kept: NO timer, NO auto-destroy — hard rule unchanged.

## v2 test commands

```bash
~/workspace/fbvenv/bin/python -m py_compile server.py test_v1.py test_v2.py
setsid ~/workspace/fbvenv/bin/python server.py > /tmp/cloud-browser-server.log 2>&1 < /dev/null &
curl -s -o /dev/null -w "GET / -> %{http_code}\n" http://127.0.0.1:8765/
~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_v2.py; echo "TEST-V2-EXIT:$?"
~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_v1.py; echo "TEST-V1-EXIT:$?"
```

## v2 results — full run, 33/33 passed (exit 0)

```
PASS navigate with no session errors {'error': 'no active session'}
PASS back with no session errors {'error': 'no active session'}
PASS UI serves at / (200)
PASS UI has Back/Forward/Reload/Go
PASS UI has no countdown/timer
PASS test page 2 serves
PASS start session {'sid': 'sess-1793373888', 'url': 'http://127.0.0.1:8765/test-page.html', 'title': 'Cloud Browser Test Page', 'navigated': False}
PASS fresh start is not a navigation
PASS input box reported {'x': 489.90625, 'y': 161.4375, 'disp_w': 1280, 'disp_h': 720}
PASS direct typing lands in input 'Bob'
PASS Backspace deletes 'Bo'
PASS ArrowLeft + type inserts mid-word 'BXo'
PASS Ctrl+A + type replaces all 'Z'
PASS Escape: session still alive {'active': True, 'sid': 'sess-1793373888', 'url': 'http://127.0.0.1:8765/test-page.html', 'title': 'Cloud Browser Test Page', 'elapsed': 3}
PASS Tab moves focus to button 'hello-btn'
PASS start on live session keeps sid {'sid': 'sess-1793373888', 'url': 'http://127.0.0.1:8765/test-page2.html', 'title': 'Cloud Browser Test Page 2', 'navigated': True}
PASS navigated to page 2 Cloud Browser Test Page 2 http://127.0.0.1:8765/test-page2.html
PASS navigate endpoint keeps sid {'sid': 'sess-1793373888', 'url': 'http://127.0.0.1:8765/test-page.html', 'title': 'Cloud Browser Test Page'}
PASS navigated back to page 1 Cloud Browser Test Page
PASS Back returns to page 1 http://127.0.0.1:8765/test-page.html {'ok': True, 'url': 'http://127.0.0.1:8765/test-page.html', 'title': 'Cloud Browser Test Page'}
PASS Forward returns to page 2 http://127.0.0.1:8765/test-page2.html {'ok': True, 'url': 'http://127.0.0.1:8765/test-page2.html', 'title': 'Cloud Browser Test Page 2'}
PASS sid unchanged through Back/Forward sid=sess-1793373888
PASS button clicked before reload 'Button clicked! Hello from the cloud browser.'
PASS Reload resets page state 'Not clicked yet.' / ''
PASS hover box reported {'x': 411.0, 'y': 432.4375, 'disp_w': 1280, 'disp_h': 720}
PASS hover registers 'Hovered!'
PASS right-click box reported {'x': 411.0, 'y': 558.4375, 'disp_w': 1280, 'disp_h': 720}
PASS right-click registers 'Right-clicked!'
PASS double-click box reported {'x': 411.0, 'y': 684.4375, 'disp_w': 1280, 'disp_h': 720}
PASS double-click registers 'Double-clicked!'
PASS session alive after all v2 controls {'active': True, 'sid': 'sess-1793373888', 'url': 'http://127.0.0.1:8765/test-page.html', 'title': 'Cloud Browser Test Page', 'elapsed': 7}
PASS Stop ends session {'active': False}
PASS screenshot gone after Stop (410)

33/33 passed
```

## v1 regression — full run, 16/16 passed (exit 0)

Re-ran `test_v1.py` against the v2 server immediately after the v2 run:
identical to the v1 run — click, type-box, scroll, screenshot stream, and
session ALIVE past 65s (elapsed=67, active=True), Stop ends it. No v1
regressions. Combined total: **49/49 passed**.

## Bugs found and fixed during v2 testing

None in the v2 code itself — the v2 suite passed 33/33 on its first run.
One test-script fix: an early "sid unchanged" check was vacuous
(`or True`); replaced with a real check against `/api/status`'s sid
before running. One tooling note (not a code bug): `pkill -f
"cloud-browser/server.py"` killed my own shell, because the pattern
matched my own command line — restarted the server without pkill.

## v1 results (kept below for the record)

## Correction applied before testing

Afnan's correction superseded the original 60-second timer: **UNLIMITED TIME,
NO TIME LIMIT AT ALL.** The countdown, the auto-destroy watchdog and every
"60s" reference were removed from `server.py` and `index.html` before the
test run below. `grep -rn "60|remaining|countdown"` over both files returns
nothing (only the screenshot-polling interval variable remains, which is not
a countdown).

## Test commands

```bash
~/workspace/fbvenv/bin/python -m py_compile server.py test_v1.py
setsid ~/workspace/fbvenv/bin/python server.py > /tmp/cloud-browser-server.log 2>&1 < /dev/null &
curl -s -o /dev/null -w "GET / -> %{http_code}\n" http://127.0.0.1:8765/
~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_v1.py; echo "TEST-EXIT:$?"
```

## Results — full run, 16/16 passed (exit 0)

```
PASS UI serves at / (200)
PASS UI has no countdown/timer
PASS test page serves
PASS start session {'sid': 'sess-1793369420', 'url': 'http://127.0.0.1:8765/test-page.html', 'title': 'Cloud Browser Test Page'}
PASS start has no time limit field
PASS remote page loaded — Cloud Browser Test Page
PASS button not yet clicked
PASS screenshot is PNG (42241 bytes)
PASS button box reported {'x': 240, 'y': 202.4375, 'w': 97.34375, 'h': 38, 'text': 'Click me'}
PASS click button changes page — 'Button clicked! Hello from the cloud browser.'
PASS screenshot changes after click
PASS type into input — 'Afnan'
PASS scroll changes screenshot
PASS session ALIVE past 65s (no auto-destroy) — elapsed=67 active=True
PASS Stop ends session — {'active': False}
PASS screenshot gone after Stop (410)

16/16 passed
```

Per-feature verdict:

| Feature | Result |
|---|---|
| UI serves, no countdown/timer anywhere | PASS |
| Start session (fresh disposable Chromium) | PASS |
| Live screenshot stream (PNG, polling) | PASS |
| Click forwarding (button click changes page + screenshot) | PASS |
| Type forwarding (input value becomes "Afnan") | PASS |
| Scroll forwarding (screenshot changes after scroll) | PASS |
| **Unlimited time: alive at elapsed=67s, no auto-destroy** | **PASS** |
| Stop destroys session (status inactive, screenshot 410) | PASS |

## Bugs found and fixed during testing

1. **`BrowserWorker.start()` shadowed `Thread.start()`** — the worker thread
   never started (`TypeError: start() missing 1 required positional argument:
   'url'`). Fixed by renaming the session method to `start_session()`.
2. **`/api/status` called `page.title()` from the HTTP thread** — Playwright
   greenlet error `Cannot switch to a different thread`, the request died
   with `RemoteDisconnected`. Fixed by routing status through the worker
   queue (`WORKER.call(WORKER.status)`) and guarding `title()` with try/except.
   After the fix the full 16/16 run passed.
3. **Failed `goto` leaked browser objects** — a failed start (e.g. no
   internet) left Chromium running. Fixed: `goto` failure now calls
   `_stop_locked()` before re-raising. Verified with a smoke re-test
   (start → status active → screenshot 200 → stop → inactive).

## Honest limits (verified, not assumed)

- **Live internet does NOT work on this VM — proven by test:**
  ```bash
  curl -s -X POST http://127.0.0.1:8765/api/start \
    -H 'Content-Type: application/json' -d '{"url":"https://example.org"}'
  # {"error": "Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED at https://example.org/"}
  ```
  This matches AGENTS.md (VM Chromium has no internet path). v1 is proven
  ONLY against the local test page. Real-site browsing needs a host with
  internet (Afnan's PC) — that is untested here.
- Single session at a time; starting a new session destroys the old one.
- Screenshot polling (~2 fps), not video streaming. Fixed 1280×720 viewport.
- No sign-up / payment / persistence by design — nothing was created,
  downloaded or installed outside the existing venv.

### v2 — what is STILL not controllable (plainly stated)

- **File upload dialogs:** no file-chooser handling — a page's "Choose file"
  button opens a native file dialog inside headless Chromium that the UI
  cannot see or complete. Not implemented, not tested.
- **Drag-and-drop / drag-select:** no mouse-down + move + mouse-up drag
  sequence — only single clicks, double-clicks and right-clicks. Text
  selection by dragging does not work; use click + Shift+arrows or
  Ctrl+A instead (both tested).
- **Native browser UI:** no access to Chromium's own UI (address bar,
  tabs, extensions, DevTools, downloads bar) — only the web page inside
  the viewport. Multiple tabs are not supported (one page per session).
- **Clipboard:** Ctrl+C/V/X are forwarded as key events, so copy/paste
  *within* the remote page works, but there is no shared clipboard
  between the local machine and the remote browser.
- **Touch / pinch / multi-touch gestures:** not implemented.
- **Audio:** headless Chromium has no audio output streamed to the UI.
- **Middle-click / scroll-click (autoscroll):** not forwarded.
- **F12 / local browser shortcuts:** F12 is reserved for the local
  browser's DevTools and is not forwarded; other Ctrl+letter combos are
  forwarded to the remote page (so Ctrl+R reloads the REMOTE page, not
  the UI page).
- **Hover is throttled** (60 ms / 8 px in the UI) — very fast mouse
  movement can skip intermediate hover states; slow hovers work fine.

## Re-test after Render hosting fix — 2026-10-30 ~19:20 PKT

Change: `server.py` now binds `0.0.0.0` (was `127.0.0.1` only) and reads
`PORT` from the environment (Render sets it; `CLOUD_BROWSER_PORT` still
accepted as fallback). No timer was added — unlimited sessions unchanged.

Verification:
- `python -m py_compile server.py test_v1.py` — OK.
- Full `test_v1.py` re-run against the changed server: **16/16 passed,
  exit 0** — identical to the v1 run, including session ALIVE at
  elapsed=67s (no auto-destroy) and Stop ending the session.
- `PORT=8899` env check: server printed `http://0.0.0.0:8899/`, served
  `GET / -> 200` on 8899, port free after kill.
- Docker: **NOT available on this VM** (`docker: command not found`), so
  the Docker build is UNPROVEN — it has not run anywhere. The Dockerfile
  uses the official Playwright `v1.64.1-jammy` image precisely so the
  first Render build has the best chance of passing, but that is a claim
  about the image choice, not a passed build.
- `render.yaml` structural check passed (all required keys present);
  no YAML parser was available on the VM to fully parse it.

## Cleanup

Test server stopped after the run (`pkill -f "[s]erver.py"`); port 8765
verified free. No session, browser or cookie data remains.

Re-test server stopped by PID kill; port 8765 verified free
(connection refused) and port 8899 likewise after the PORT check.

## v2 cleanup — 2026-10-30 ~20:30 PKT

v2 test server (PID 21291) stopped by PID kill after both suites passed;
port 8765 verified down (connection refused). No session, browser or
cookie data remains. `__pycache__` in the project folder is Python
bytecode only. Mediora untouched.
