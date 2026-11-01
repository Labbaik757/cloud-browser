# TEST-REPORT.md — Cloud Browser v6 (full control + cookie login + file upload)

Date: 2026-10-30. Tester: automated scripts `test_v1.py` + `test_v2.py`
(driving the HTTP API exactly as the UI does) + manual curl checks. All
commands run with `~/workspace/fbvenv/bin/python` (Python 3.12.3, Playwright
+ Chromium 1248 from `~/.cache/ms-playwright/`).

## SCREENCAST — live video stream instead of screenshot polling, 2026-10-31

Afnan: the browser does not feel like real Chrome because the UI shows
still screenshots at ~2 fps. Built into `server.py`: the worker opens a
CDP session on the live page (`context.new_cdp_session(page)`) and calls
`Page.startScreencast` (JPEG, quality 65, maxWidth 1280,
everyNthFrame=1). `Page.screencastFrame` events are acked with
`Page.screencastFrameAck` and the latest frame is cached; `GET
/api/screenshot` serves that cached frame (same URL, same token auth,
same JPEG response shape). The UI polls every 100 ms (was ~500 ms) and
pauses polling while the tab is hidden (`document.hidden`). New
`GET /api/screencast-stats` reports `{screencast_on, frames,
bytes_total}`. `test_v1.py` updated: the screenshot assertion is now
JPEG (`\xff\xd8\xff`), not PNG.

**Three real bugs found by measuring, not by guessing:**
- **Wrong CDP event name.** Subscribing to bare `screencastFrame`
  never fires — Playwright's `CDPSession` emits the full method name,
  `Page.screencastFrame` (read from its `_cdp_session.py`). The stream
  stayed at 0 frames until this was fixed.
- **everyNthFrame=6 is too slow on a damage-driven page.** The
  compositor only produces frames on damage, so skipping 5 of 6 gave
  0.7 fps on a page changing every 150 ms. everyNthFrame=1 (forward
  every damage frame) — the UI's 100 ms poll caps what the user sees.
- **Headless Chromium does not composite on damage alone.** With an
  animation changing the DOM every 150 ms, the stream delivered ZERO
  frames in 10 s with no other traffic — `bring_to_front` and the
  `--disable-backgrounding-occluded-windows` /
  `--disable-renderer-backgrounding` /
  `--disable-background-timer-throttling` flags did not help. What
  produces frames is a `page.evaluate`: ~1 frame per evaluate. So the
  worker pokes the compositor with a tiny DOM read
  (`document.title`) every ~100 ms, only while a session is live and
  the screencast is on. The poke is time-gated (at most 1 per 100 ms)
  and runs both when the job queue is idle and after each job — a
  client polling `/api/screenshot` every 50 ms starved the idle-only
  poke and click latency was 1.03 s until the after-job poke was
  added (now 0.11–0.16 s).
- **Fallback screenshots can starve the acks.** The first design took
  a blocking `page.screenshot` on every poll while the frame was stale;
  each shot saturates the worker queue and delays the acks the
  screencast needs to deliver its next frame (stream ran at ~0.7 fps
  while every poll took a shot). The fallback is now rate-limited to
  one shot per 2 s; between shots the cached frame is returned.

**Results — 2026-10-31, screencast suite: 44/44 passed, exit 0
(~17 s).** Three sub-suites in one file (token from env):
- **Extensions mode (the folder as shipped, `extensions/` present):
  21/21.** UI loads; UI polls at 100 ms + pauses when hidden;
  start session; first frame arrives (JPEG); button box; click changes
  the page; **frame changes within ~1 s of the click — latency
  0.16 s**; screencast ON with frames flowing; animation started;
  **bandwidth while the page changed every 150 ms: server fps 6.7,
  average frame 42,338 bytes, ~16.9 MB/min, 20 distinct frames in 29
  samples**; static page: only 2 distinct frames in 2 s (the poke
  does not flood a static page); create + switch to profile B (session
  ends); frame arrives in B and screencast ON with frames flowing
  (CDP works in the persistent-context page too); Stop ends the
  session; screenshot 410 after Stop.
- **Classic mode (temp copy without `extensions/`, port 8766):
  15/15.** Same core checks; click latency 0.11 s; screencast ON with
  frames flowing; profile B works there too.
- **Fallback probe (temp copy with `new_cdp_session` patched to
  raise, port 8767): 8/8.** Screencast OFF, session still starts,
  screenshot returns JPEG via the fallback, frame changes after a
  click, Stop ends cleanly.
- **Regressions, all with the screencast code live: v1 19/19, v2
  37/37, profiles 36/36, extensions 17/17 — 109/109 passed.**
- **Combined: 153/153 passed** (44 screencast + 109 regression).
  Cleanup: test servers stopped; test profiles cleaned up;
  `profiles/`, `profiles.json`, `port.txt` removed so the folder
  ships clean.

**Limits (honest):** the ~6.7 fps / ~17 MB/min is measured on the
local test page while it changes every 150 ms; a continuously
animating page (video, 60 fps animation) makes Chromium encode more
frames server-side — the UI still only fetches ~10 fps, but the host
CPU does the extra encoding, so Render free (0.1 CPU) may feel
sluggish on heavy animated pages. Live internet on this VM still does
not work (local test pages only); the deployed Render service has
internet. The laptop zip was NOT rebuilt here (parent does that).

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

## EXTENSIONS — unpacked MV3 extensions load into the remote browser, 2026-10-31

Afnan asked: install an extension and test it. Built into `server.py`:
`extensions/` is scanned at browser launch for subfolders with a
`manifest.json` and loaded via `--load-extension` (plus
`--disable-extensions-except`). Test extension `extensions/cb-test/`
(MV3, no deps): content script sets `data-cb-ext="loaded"` on every
page and adds a fixed "CloudBrowser Ext ON" badge.

**How it was verified — headless does NOT load extensions the naive
way (and the proof):** first probe, plain `chromium.launch(headless=True)`
+ `--load-extension`: marker stayed `None` on a real http page, with
and without `--disable-extensions-except`. Root cause, read from
Playwright's own driver bundle: its default Chromium switches include
`--disable-extensions`. Even after `ignore_default_args=
["--disable-extensions"]` (verified gone from the live process
command line) the marker stayed `None` — and direct CLI runs of the
same full Chromium with `--headless` and `--headless=new` DID load it
(marker "loaded"). The difference: `chromium.launch()` uses the
headless-shell build and its `new_context()` pages are incognito, and
extensions do not run in incognito contexts. The working path,
verified: `launch_persistent_context` on the FULL Chromium build
(`channel="chromium"`, new headless) — marker "loaded" in the
persistent context's own pages. Extra `browser.new_context()` pages
from that browser stayed `None`, so the session page lives IN the
persistent context and each profile gets its own user-data-dir
(`profiles/<id>/`); switching profiles relaunches the browser for the
new profile (session ends on switch, as before). With no extensions
installed the launch is byte-for-byte the old path.

**Results — 2026-10-31, extensions installed:**
- **Extensions suite: 17/17 passed, exit 0 (~10s).** UI loads; start
  session; marker `data-cb-ext="loaded"` present; badge exists reading
  "CloudBrowser Ext ON"; marker survives a page reload; create profile
  "Test Ext B", switch (session ends), marker + badge present in B;
  switch back to default, marker present again; delete B, only
  `default` remains. Test profiles cleaned up.
- **v1 regression: 19/19 passed, exit 0** (incl. session ALIVE past
  65s). **v2 regression: 37/37 passed, exit 0. Profiles regression:
  36/36 passed, exit 0** — all with extensions installed.
- **Classic-mode check (extensions/ moved aside): profiles 36/36
  passed, exit 0; marker `None` as expected; server log shows no
  "Extensions found" — the old launch path is intact.
- **Combined: 109/109 passed with extensions installed** (17 + 19 +
  37 + 36). Cleanup: test server stopped; `profiles/`,
  `profiles.json`, `port.txt` removed so the folder ships clean.

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

## CONTROL v6 — cookie login + file upload + parity, 2026-10-31

Afnan: the cloud browser must be a 100% control browser for Muse's own
use, drivable by hand like her live browser. Verified gap: the server had
NO cookie-injection API at all, and a live document.cookie test with
Kristen's fresh cookies set c_user/xs but datr/sb/fr did not stick.
Built into `server.py` + `index.html`:
- `POST /api/cookies` — list form (`context.add_cookies()`, per-cookie
  url or domain+path, expires/httpOnly/secure/sameSite) or raw-string
  form (`"name=value; ..."` + one domain, Set-Cookie attributes skipped).
  `GET /api/cookies` lists the live context's cookies (optional
  `?domain=` filter). UI: paste cookie string + domain + Inject, List
  shows names + count only (never values).
- `POST /api/upload` (multipart, hand-rolled parser — cgi is
  deprecated) — `file` + `mode` (`input` | `chooser`) + `selector`.
  Input mode: `set_input_files` on the file input (default
  `input[type=file]`). Chooser mode: arms a one-time `page.once(
  "filechooser")` handler that feeds the file to the next native dialog
  (handler only records + enqueues, same rule as the screencast
  handler). `GET /api/upload/status` reports armed/fired/error. Files
  saved under `uploads/` (20 MB cap, >1h files cleaned on upload). UI:
  file picker + selector + both buttons.
- Parity: `POST /api/select` (value/label/index), `POST /api/drag`
  (mouse drag between two view points), `POST /api/click` takes
  `button` (left/middle/right). All routes token-authed (401 checks).

**Measured first, not guessed:** a direct Playwright experiment proved
`set_input_files` works on a `display:none` input AND the once-handler
+ JS click hands the file to the dialog — both before the server code
was written. One real bug found by the test run: `GET /api/cookies`
with no session crashed the HTTP connection (do_GET has no outer
try/except, unlike do_POST) — wrapped in a 410 like `/api/info`.

**Results — 2026-10-31, v6 suite `test_control_v6.py`: 42/42 passed,
exit 0 (~9 s).** Token checks (7), no-session errors (5), raw-string
cookies set + listed + visible in document.cookie, HttpOnly list cookie
set + listed httpOnly=true + NOT in document.cookie (the HttpOnly
proof), validation errors (4), upload to visible + hidden inputs,
chooser arm + fired + file on the page, upload validation (2), select,
drag (10 mousemoves), middle-click, stop. Regression the same day:
**profiles 36/36, v2 37/37, v1 19/19 — 134/134 total, exit 0.**

## OOM on Render free (512 MB) — 2026-10-31 ~23:29–23:36 PKT, v6.1 patch

Render alert: the service exceeded its memory limit and auto-restarted.
Dashboard diagnosis (read-only, 2026-10-31 23:36–23:39 PKT): NOT one
restart but FOUR "Instance failed" events — "Ran out of memory (used
over 512MB) while running your code." — at 23:29:27, 23:31:11, 23:34:50
and 23:36:38 PKT, each followed by an automatic restart. Before EVERY
failure the logs show the same sequence within seconds: POST
/api/profile/create, POST /api/profile/select, "Extensions found:
/app/extensions/cb-test" (browser launch), POST /api/start, POST
/api/cookies, GET /api/cookies — i.e. each failure hit during/just
after a fresh browser launch + cookie inject. No OOM/Killed/Traceback/
Playwright/Error lines exist in the app logs (the message is a Render
platform event only); the memory graph is a PAID Render feature, so
gradual climb vs sudden spike cannot be determined from the dashboard.
The v6 deploy went live 23:16; the failures began ~13 min later. The
live v6 verification session (Kristen logged in, 23:18–23:19) succeeded
before the failures — the launches that died came after it.

Fix (v6.1 patch, same v6 banner): low-memory Chromium flags in
`CHROMIUM_ARGS` — `--disable-gpu`, `--disable-software-rasterizer`,
`--js-flags=--max-old-space-size=256` (caps each renderer's V8 heap).
Deliberately NOT `--disable-extensions` (would break extensions mode)
and NOT `--single-process`/`--no-zygote` (desktop variant segfaulted on
`--single-process`; the zygote shares memory via fork). Local re-test
after the flags: **test_control_v6 42/42, test_profiles 36/36, exit 0**
— launch still works. If launches still OOM, the next steps are
dropping the test extension from the image (lighter classic launch) or
a paid Render plan — both need Afnan's call, neither is done here.

## OOM — flags NOT enough; extensions mode dropped (default) — 2026-10-31 ~23:49 PKT

Dashboard check (read-only, 23:49–23:52 PKT): the v6.1 flags deploy
(8cdf9e8) DID go live 23:42:59 PKT — so the 23:43–23:44 restore ran on
the NEW code with the low-memory flags. It still died: instance pvhkv
(new code) "Ran out of memory (used over 512MB)" at 23:49 PKT; a
further gx2pj failure at 23:40 PKT was the old code. That is SIX OOM
failures in one evening (23:29, 23:31, 23:34, 23:36, 23:40, 23:49).
Verdict: `--disable-gpu` + `--disable-software-rasterizer` +
`--max-old-space-size=256` do NOT save a single idle Facebook session
in extensions mode (full Chromium + persistent context) on 512 MB —
the feed's images/compositor memory is outside the V8 heap cap.
Service was "Failed service" on the dashboard at 23:51 with no
recovery event yet (Render auto-restarted it after; /api/status
answered 401 = up, no session).

Fix (v6.2): extensions are now OPT-IN. `find_extensions()` returns []
unless `CLOUD_BROWSER_EXTENSIONS=1`, so the default launch is
`chromium.launch()` (headless-shell build) — far lighter. The cb-test
extension files stay in the repo; the extension-support code is
untouched; `test_extensions.py` sets the env var for the server it
spawns. The Facebook rename job does not use extensions. If a session
still OOMs in classic mode, the remaining options are a paid Render
plan (more RAM) or moving the browser to the Oracle VM once that
account exists — both need Afnan's call.

## VERDICT — classic mode also OOMs; Render free cannot hold Facebook — 2026-11-01 ~00:03 PKT

Dashboard check (read-only, 00:04–00:06 PKT): deploy d5cbe90 went
live 23:59:38 PKT — BEFORE the re-proof restore, so the restore ran on
the NEW classic-mode code. It still died: instance 57c2d "Ran out of
memory (used over 512MB)" at 00:03 AM, ~2 min after the session went
live (Kristen logged in, idle on facebook.com). No deploy-live events
after midnight, so this was NOT a deploy restart. That is SEVEN OOM
failures in ~35 minutes (23:29, 23:31, 23:34, 23:36, 23:40, 23:49,
00:03). Service was "Failed service" on the dashboard at ~00:05 with
no recovery event yet.

FINAL VERDICT: neither the low-memory flags nor the classic
headless-shell launch saves a Facebook session on Render free (512 MB).
An idle Facebook tab alone exceeds the limit within ~2–5 minutes.
Do NOT keep launching Facebook sessions on this service — each one
OOMs and restarts it. The remaining options are a paid Render plan
(more RAM) or moving the browser to the Oracle VM once that account
exists (2 OCPU / 12 GB, muse-control already built) — both need
Afnan's call. The Facebook rename/feedback work has already moved to
machine Chrome (his order, ~23:55 PKT) and is not blocked by this.

## v7 / v7.1 — laptop, REAL Chrome, dynamic IDs (2026-11-01)

Afnan picked his own Windows laptop (free) as the browser host. The server
now runs there instead of Render: v7 attaches over CDP to the REAL installed
Google Chrome (Launch-Real-Chrome.bat, port 9222, dedicated profile) and
never closes it; the page has a separate Facebook IDs section (one-click
login per ID from ids.json, review-page links). v7.1: ids.json is GENERATED
by rebuild_ids.py (never deletes a UID) and single IDs are added from the
browser form — names change and IDs keep growing, so the list is not a
fixed snapshot. Laptop package: Cloud_Browser_Laptop_v7.1_RealChrome.zip
(111 files). Tests on the VM: Real Chrome CDP end-to-end ALL PASS,
v6 control suite 42/42 PASS, POST /api/ids add/update + 401 ungated PASS.

## v7.2 — launcher port-wait fix (2026-11-01 ~18:16 PKT)

BUG (seen on the laptop): the server binds a free port itself (8765 was
blocked by WinError 10013, so it took 8766 and wrote port.txt), but both
launchers waited only a fixed 5s and then read port.txt before the server
wrote it, defaulting to 8765. The Tailscale Funnel then proxied to 8765
(nothing listening) and the public URL returned HTTP 502, while the server
sat healthy on 8766. FIX: both launchers now wait for port.txt to appear
(up to 30s) and fail with a clear error if it never does. Manual fix for
the live run: `tailscale funnel 8766` in the funnel window.

## v7.3 — launcher port-wait fix, take 2 (2026-11-01 ~18:33 PKT)

v7.2's fix did NOT work on the laptop: after a fresh GitHub clone to
C:\cloud-browser, the funnel STILL went to 8765 while the server sat on
8766, and "The syntax of the command is incorrect." appeared again. The
v7.2 loop (goto + `set /a` counter) and/or the `set /p VAR < "file"` read
(redirect inside an IF) is the suspect. v7.3 replaces BOTH with the
standard robust batch idioms: a `for /l %%i in (1,1,30)` wait loop (goto
out on port.txt found, else a clear error after 30s) and a
`for /f "usebackq delims=" %%P in ("port.txt")` read. The live run is
still fixed by hand in the meantime: `tailscale funnel 8766` in the
funnel window.
