# Cloud Browser v2 — full control (self-built prototype)

A cloud browser like Browser.lol / NetworkChuck Cloud Browser, built
from scratch. A web UI starts a fresh, disposable Playwright Chromium session
on the host machine, streams screenshots back to the page, and gives you
FULL CONTROL of that remote browser: click the live view and type directly
into it, right-click, double-click, hover, Back / Forward / Reload, and
navigate in the same session — everything goes to the remote browser.

**Unlimited time — no time limit at all.** A session runs until you click
Stop. (A 60-second timer was in the first draft and was removed on Afnan's
correction — there is no countdown, no auto-destroy, no demo limit anywhere
in this code.)

No sign-up, no payment, no phone-home. Profiles keep separate logins:
each profile's cookies + localStorage are saved when you switch away
or Stop, and reloaded when that profile becomes active (see
**Profiles** below). One shared token locks the API — see **Token auth**
below. Muse uses it by opening its public link directly in her own
browser and driving the page with her native capabilities — no extra
control code needed.

## Token auth (required before any public link)

The server **refuses to start** unless `CLOUD_BROWSER_TOKEN` is set in
the environment. The token is never hardcoded and never written to any
file by the server. Every `/api/*` route checks it (header
`X-Cloud-Token`, or `?token=` query). The UI asks for the token once
(Unlock box) and keeps it in memory only — never localStorage, never
in the URL. Wrong/missing token = `401 {"error": "unauthorized"}`,
no session data leaked.

```bash
# pick a long random token (keep it private — it is the only lock)
CLOUD_BROWSER_TOKEN=<long-random-token> ~/workspace/fbvenv/bin/python server.py
```

## Profiles — multi-profile system (separate isolated logins)

One profile per account (e.g. a different Facebook login each). Each
profile has an id (a slug of its name, e.g. `facebook-work`) and a
display name. A `default` profile always exists and cannot be deleted.

- **One active context at a time** (Render free has only 512 MB — never
  two contexts alive). Switching profiles ends the current session
  (status goes idle), saves the old profile's cookies + localStorage to
  `profiles/<id>.json` (Playwright `storage_state`), closes its
  context, and makes the new profile active. The next Start opens the
  new profile's context with its saved state, if any — so a login made
  in a profile is still there when you come back to it.
- **UI:** a Profile dropdown at the top (active profile selected), with
  New (asks for a name, then switches into the new profile) and Delete
  (asks for confirmation; deleting the active profile falls back to
  `default`). A new session in the new profile starts on the test page.
- **API** (all behind the same token auth): `GET /api/profiles`,
  `POST /api/profile/create {"name": ...}`,
  `POST /api/profile/select {"id": ...}`,
  `POST /api/profile/delete {"id": ...}`. All existing endpoints act on
  the ACTIVE profile. State is also saved on Stop.
- **Persistence limit (honest): on Render free the disk is ephemeral**,
  so profiles reset when the service restarts or sleeps — a profile's
  saved login does not survive a Render restart. On the laptop the
  profiles persist in `profiles/` because the folder stays on disk.
  State is saved on switch/Stop, not on a killed server (`Ctrl+C`
  without Stop loses the current session's unsaved state).

## Files

| File | What it is |
|---|---|
| `server.py` | Stdlib `http.server` + Playwright. Serves the UI, owns the session, forwards all input, streams screenshots. Token auth on every `/api/*` route. |
| `index.html` | The UI: token Unlock box, URL bar, Go / Start / Stop, Back / Forward / Reload, live view with direct keyboard, right/double-click, hover, wheel-scroll, session-time display. |
| `LAPTOP-SETUP.md` | Windows laptop setup: Python, Playwright, cloudflared, Quick Tunnel, what to do when each step fails. |
| `start-cloud-browser.bat` | Double-click launcher for the Windows laptop: installs Playwright if missing, makes/saves a token, starts the server + Quick Tunnel. |
| `test-page.html` | Local test page (heading, input, click-me button, scroll target, hover / right-click / double-click boxes, link to page 2). |
| `test-page2.html` | Second local test page (Back/Forward + navigate-in-session proof). |
| `test_v1.py` | v1 end-to-end test (UI, click, type-box, scroll, unlimited-time proof, token 401 checks). |
| `test_v2.py` | v2 end-to-end test (direct keyboard, Back/Forward/Reload, navigate in session, right/double-click, hover, token 401 checks). |
| `test_profiles.py` | Profiles end-to-end test (create/select/delete, localStorage isolation + persistence across switches, token 401 checks). |
| `profiles.json` + `profiles/` | Runtime state, created on first use (not shipped): profile registry + each profile's saved cookies/localStorage (`profiles/<id>.json`). |
| `TEST-REPORT.md` | Exact test commands and honest pass/fail results (v2: 33/33, v1 regression: 16/16, plus auth checks). |

## Run it

```bash
CLOUD_BROWSER_TOKEN=<long-random-token> ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/server.py
```

Then open in your own browser:

```
http://127.0.0.1:8765/
```

Type the token into the **Unlock** box first — every API call needs it.
Default page is the local test page: `http://127.0.0.1:8765/test-page.html`

Port can be changed with `CLOUD_BROWSER_PORT`, e.g.:

```bash
CLOUD_BROWSER_PORT=8899 ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/server.py
```

Render sets `PORT` itself; `server.py` reads `PORT` first and falls back
to `CLOUD_BROWSER_PORT`. It binds `0.0.0.0` so it is reachable in a
container (local runs still work at `http://127.0.0.1:8765/`).

## Windows laptop + Cloudflare Quick Tunnel (public link, no domain)

Full steps in [LAPTOP-SETUP.md](sandbox://workspace/cloud-browser/LAPTOP-SETUP.md).
Short version: copy this folder to `C:\cloud-browser` on the laptop,
double-click `start-cloud-browser.bat` (installs Playwright and
cloudflared if missing, makes + saves a token, starts the server and
the Quick Tunnel), then send Muse the printed public
`https://*.trycloudflare.com` URL **and** the token. The URL changes
every restart; a stable URL later needs a cheap domain + named tunnel
(see LAPTOP-SETUP.md, last section).

## Deploy on Render (public URL)

Full steps in [DEPLOY.md](sandbox://workspace/cloud-browser/DEPLOY.md).
Short version: push this folder to a GitHub repo (files at repo root),
create a free Render Web Service from it (Docker runtime, `./Dockerfile`),
open the `https://<name>.onrender.com/` URL.

**Do NOT use Netlify** — static hosting + serverless Functions (10s
default timeout, max 26–30s, no persistent process) cannot run this
persistent server holding a live Chromium session. Render free sleeps
after 15 min idle and has 512 MB RAM (tight for Chromium); live internet
on the deployed host is unproven until a real deploy. On Render the
token is generated by the Blueprint (`CLOUD_BROWSER_TOKEN`,
`generateValue: true`) — read it back in the dashboard and give it to
Muse with the URL.

To stop: Ctrl+C in the terminal, or the **Stop** button in the UI.

## Run the tests

```bash
# terminal 1 — start the server with a test token (as above, e.g. test-token-123)
# terminal 2 — run the tests (same token in the environment)
CLOUD_BROWSER_TOKEN=test-token-123 ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_profiles.py
CLOUD_BROWSER_TOKEN=test-token-123 ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_v2.py
CLOUD_BROWSER_TOKEN=test-token-123 ~/workspace/fbvenv/bin/python ~/workspace/cloud-browser/test_v1.py
```

`test_profiles.py` is fast (~5s) and `test_v2.py` is fast (~12s).
`test_v1.py` takes ~75s: it waits past 65s to prove the session does
NOT auto-destroy. Results on 2026-10-31 after the profiles change:
**profiles 36/36 passed, v2 37/37 passed, v1 19/19 passed — 92/92
total, exit 0.** See TEST-REPORT.md.

## API (what the UI calls)

Every `/api/*` route needs the token: header `X-Cloud-Token`, or
`?token=` query. Without it: `401 {"error": "unauthorized"}`.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | The UI |
| `GET` | `/test-page.html`, `/test-page2.html` | Local test pages |
| `POST` | `/api/start` `{"url": ...}` | Fresh disposable Chromium — or navigate the LIVE session to the URL (same sid) if one is already running |
| `POST` | `/api/navigate` `{"url": ...}` | Go to a URL in the current live session (error if none live) |
| `POST` | `/api/back` / `/api/forward` | History Back / Forward in the live session |
| `POST` | `/api/reload` | Reload the live session's page |
| `GET` | `/api/screenshot` | Latest PNG screenshot of the remote browser |
| `GET` | `/api/status` | `{active, sid, url, title, elapsed}` |
| `GET` | `/api/info` | Page title/URL/text, input value, element boxes, focused element, history length |
| `POST` | `/api/click` `{"x","y","disp_w","disp_h"}` | Left-click in the remote browser (coords scaled to 1280×720) |
| `POST` | `/api/rightclick` `{"x","y","disp_w","disp_h"}` | Right-click in the remote browser |
| `POST` | `/api/dblclick` `{"x","y","disp_w","disp_h"}` | Double-click in the remote browser |
| `POST` | `/api/hover` `{"x","y","disp_w","disp_h"}` | Move the mouse (hover) in the remote browser |
| `POST` | `/api/type` `{"text": ...}` | Type text into the focused element (backup type box) |
| `POST` | `/api/key` `{"key": "Enter"}` | Press a single key |
| `POST` | `/api/keydown` `{"key","ctrl","meta","shift","alt"}` | Key down — direct keyboard (Ctrl+letter sent as one combo press) |
| `POST` | `/api/keyup` `{"key","ctrl","meta","shift","alt"}` | Key up — releases a held-down key |
| `POST` | `/api/scroll` `{"dy": 300}` | Scroll the remote page |
| `POST` | `/api/stop` | Destroy browser + session immediately |
| `GET` | `/api/profiles` | List profiles `[{id, name}]` + which is `active` |
| `POST` | `/api/profile/create` `{"name": ...}` | Create a profile, returns `{id, name}` (id is a slug of the name; a duplicate name gets `-2`) |
| `POST` | `/api/profile/select` `{"id": ...}` | Switch profile — ends the live session, saves its state, returns `{ok, active, switched, session_ended}` |
| `POST` | `/api/profile/delete` `{"id": ...}` | Delete a profile + its saved state; deleting the active one falls back to `default` (default itself cannot be deleted) |
| `POST` | `/api/eval` `{"js": ...}` | Run a JS expression in the live page (test/debug helper), returns `{result}` |

## Honest limits

- **Live internet browsing on this VM is UNPROVEN and does not work.**
  The VM's Chromium has no internet path: starting a session to
  `https://example.org` fails with `net::ERR_TUNNEL_CONNECTION_FAILED`.
  v2 is proven only against the local test pages. To browse real sites it
  needs a host with internet (Afnan's PC).
- Single session at a time (v2 scope). Starting a new session destroys
  the old one; Go/Back/Forward/Reload keep the same session.
- One ACTIVE profile/context at a time. Profiles are isolated (separate
  cookies + localStorage each), but on Render free the disk is
  ephemeral: profiles reset when the service restarts or sleeps. On the
  laptop they persist in `profiles/`.
- Screenshot polling (~2 fps), not a video stream. Good enough for v2.
- Remote viewport is fixed at 1280×720.
- **Still NOT controllable:** file upload dialogs, drag-and-drop /
  drag-select, the browser's own UI (tabs, extensions, DevTools),
  multi-tab sessions, shared clipboard with the local machine, touch
  gestures, audio, middle-click. See TEST-REPORT.md for the full list.
