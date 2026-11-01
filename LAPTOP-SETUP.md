# Cloud Browser — Windows laptop setup (v7.1: REAL Google Chrome + IDs section)

**Goal:** run the self-built cloud browser on Afnan's Windows laptop (8 GB RAM,
residential internet) and expose it on a public link, so Muse can open that
link in her own browser and drive the remote browser with her native
capabilities (click, type, scroll, navigate) — exactly like Browser.lol.

**v7 change — REAL Chrome:** the browser is now the REAL installed Google
Chrome (the normal Chrome you use), not Playwright's test Chromium. The
server attaches to it over CDP (remote debugging, port 9222) and NEVER
closes it — Stop only closes Muse's tab. **IDs section:** the browser page
has a separate "Facebook IDs" section — pick an ID, one click logs in with
its cookies, plus quick links to the review pages. The full ID automation
(drivers + data) is in the `ids/` folder of this package.

**v7.1 change — IDs are not fixed:** names change and new IDs keep coming,
so `ids.json` is a GENERATED file, not a one-time snapshot. When new IDs are
created or names change, run `python rebuild_ids.py` in this folder (it
rebuilds the list from the `ids/` data files and never deletes an ID), or add
a single ID from the browser's "Add / update ID" form. The IDs section picks
it up at once — **Refresh list** in the page, no server restart needed.

**No domain, no account, no card needed for this first test.** The Tailscale
Funnel gives a stable public URL (same address every restart). A stable
Cloudflare URL needs a cheap domain later — see the last section.

## Get the code (GitHub — the source of truth)

The setup lives on GitHub: https://github.com/Labbaik757/cloud-browser
- With Git: `git clone https://github.com/Labbaik757/cloud-browser.git`,
  then move/rename the folder to `C:\cloud-browser`.
- Without Git: open the repo page, click **Code → Download ZIP**, extract
  it, rename the folder to `C:\cloud-browser`.
- Updates: `git pull` in the folder (or a fresh ZIP download). Your IDs
  and token are NOT in the repo — `ids.json`, the `ids/` folder and
  `token.txt` live only on your laptop, so updating the code never wipes
  them. (A fresh clone has no IDs yet — copy your `ids.json` + `ids/`
  folder into it, or add IDs from the browser's "Add / update ID" form.)
  Your proxy is also local-only — `proxy.txt` is never in the repo (see
  "Hide your real IP" below).

## Hide your real IP + appear as US (proxy)

Your real IP must never show anywhere. Chrome routes all its traffic
through a US proxy, so websites see the proxy's US IP, never yours.
WebRTC is forced through the proxy too, so the real IP cannot leak.

1. Create a file named `proxy.txt` in `C:\cloud-browser` (same folder as
   the `.bat` files). One line only, your US proxy:
   `http://user:pass@us-proxy.example.com:8080`
   (Use your own US proxy — e.g. a Webshare US proxy. Save the file as
   plain text, ANSI or UTF-8 without BOM. Do NOT put this file on GitHub
   and do NOT send it to anyone — it holds your proxy password.)
2. If Chrome is already running, CLOSE it first (the cloud-browser
   profile window), then double-click `Launch-Real-Chrome.bat` again —
   it prints "Proxy ON" when the proxy applies. Then run
   `start-cloud-browser-tailscale.bat` as usual.
3. US timezone: set the Windows timezone to a US zone (Settings →
   Time & language → Date & time → Time zone → (UTC-05:00) Eastern
   Time). Chrome's language is already forced to en-US.
4. VERIFY (important): in the cloud browser, open https://ifconfig.me
   and confirm the IP shown is a US IP and NOT your real one. If it
   shows your real IP, the proxy did not apply — close Chrome and
   re-run `Launch-Real-Chrome.bat`.
   NOTE: a free/datacenter US proxy can be flagged by Facebook (it sees
   a datacenter IP). A US residential proxy is better for Facebook but
   costs money. The proxy still hides your real IP either way.

## What you need

- Windows 10 or 11 laptop, 8 GB RAM, internet.
- **Google Chrome installed** (the normal Chrome — https://www.google.com/chrome/).
- This `cloud-browser` folder, copied to the laptop — put it at
  `C:\cloud-browser` (it must contain `server.py`, `index.html`,
  `ids.json`, `rebuild_ids.py`, `test-page.html`, `test-page2.html`,
  `requirements.txt`, `Launch-Real-Chrome.bat`,
  `start-cloud-browser-tailscale.bat` and `start-cloud-browser.bat`,
  plus the `ids/` folder).
- The laptop must stay ON, awake, and online while the browser is used.
  If it sleeps, reboots, or loses internet, the session stops.

## Step 0 — Keep the laptop awake

Settings → System → Power & sleep → set **Screen** and **Sleep** to
**Never** while using the cloud browser. (Or, as administrator in Command
Prompt: `powercfg /change standby-timeout-ac 0`.) If the laptop sleeps,
the tunnel and the browser die with it.

## Step 1 — Install Python 3.12

1. Open https://www.python.org/downloads/ in your browser.
2. Download **Python 3.12** (Windows installer, 64-bit) and run it.
3. **IMPORTANT:** on the first installer screen, tick
   **"Add python.exe to PATH"** — then click Install.
4. What you should see: install finishes with "Setup was successful".
5. Check it worked: open Command Prompt and type `python --version`.
   You should see `Python 3.12.x`. If it says "not recognized", reinstall
   with the PATH box ticked — that is the usual cause.

## Step 2 — Install Playwright (first run only)

The launcher script (`start-cloud-browser-tailscale.bat`) does this for you
automatically if Playwright is missing. To do it by hand instead, in
Command Prompt from `C:\cloud-browser`:

```bat
python -m pip install playwright
```

That is all — **no Chromium download anymore.** v7 uses your real installed
Google Chrome, so the ~150 MB `playwright install chromium` step is skipped.
(If you ever need the bundled Chromium, run
`python -m playwright install chromium` by hand.)

## Step 3 — Launch the REAL Chrome (every time you start)

Double-click **`Launch-Real-Chrome.bat`** in `C:\cloud-browser`.

What it does: opens your real Google Chrome with remote debugging on port
9222 and a dedicated profile folder `C:\cloud-browser\chrome-profile`
(your daily Chrome is untouched — this is a separate profile). What you
should see: a Chrome window opens, and the script prints "Real Chrome is
ready". **Keep this Chrome window open** while using the cloud browser.
If it is already running, the script just says so and exits.

## Step 4 — Install Tailscale + sign in (first run only)

1. Install Tailscale from https://tailscale.com/download and run it.
2. Open Command Prompt and run `tailscale up`, then sign in in the
   browser when it asks (Google / GitHub / Microsoft — any works).
3. This gives the server a stable public address like
   `https://your-laptop-name.your-tailnet.ts.net` — the address does not
   change on restart, so you only send it to Muse once.

## Step 5 — Start it (double-click)

Double-click **`start-cloud-browser-tailscale.bat`** in `C:\cloud-browser`.

What you should see, in order:

1. It checks Python, installs Playwright if missing, then makes sure Real
   Chrome is running (it runs `Launch-Real-Chrome.bat` itself if needed).
2. A **"Cloud Browser Server"** window opens and prints
   `Cloud Browser v7 — http://0.0.0.0:8765/` and
   `Browser: REAL Google Chrome via CDP http://127.0.0.1:9222`.
   If port 8765 is blocked on your laptop (WinError 10013), the server
   picks the next free port itself (8766, 8767, ...) and prints that one
   instead, and writes it to `port.txt` — the launcher reads it, nothing
   for you to change.
3. The main window prints **YOUR TOKEN** (a long code) and saves it to
   `token.txt` in the same folder.
4. The main window then prints a public URL like
   `https://your-laptop-name.your-tailnet.ts.net` — that is the link to use.
5. If Windows Firewall asks about Python: click **Allow** (private
   network). Without this the funnel cannot reach the server.

**Leave all three windows open while browsing** (Chrome + Server + Funnel).
Closing any of them stops it.

## Step 6 — Give Muse the link + token

Send Muse (in chat) two things:

1. The public URL from the funnel window, e.g.
   `https://your-laptop-name.your-tailnet.ts.net`
2. The token from the window / `token.txt`.

Muse opens that URL in her own browser, types the token into the
**Unlock** box, clicks **Start Session**, and drives the remote browser
from there — URL bar, click, type, scroll, Back/Forward/Reload, all
unlimited until Stop. **The URL does not change on restart** — send it once.
The token stays the same unless you delete `token.txt` and restart, which
makes a new one.

### Facebook IDs section

After unlocking, the page has a **Facebook IDs** section: pick an ID from
the list and click **Login as ID** — its cookies are injected and Facebook
opens logged in as that ID. **Reviews page** jumps straight to the Global
Food Hub reviews page (the feedback job's page); **Profile** opens the
ID's own profile. The detail line under the list shows the ID's current
name, its rename target, and its password (for a manual login if the
cookies are dead). The full ID automation (drivers + data) is in the
`ids/` folder — see `ids/README-IDS.md`.

**IDs are not fixed — they grow and change.** When new IDs are created or
names change: either run `python rebuild_ids.py` in this folder (it
rebuilds `ids.json` from the `ids/` data files and never deletes an ID),
or add one ID at a time with the **Add / update ID** form on the page
(UID + name + password + cookies). Then click **Refresh list** — the new
IDs appear at once, no server restart needed.

## If something fails

| What you see | Do this |
|---|---|
| `python not found` | Reinstall Python 3.12 with **Add to PATH** ticked (Step 1). |
| `pip install playwright` fails | Check internet; retry. If pip is "not recognized", fix PATH (Step 1). |
| `Google Chrome not found` | Install Chrome from https://www.google.com/chrome/ then retry. |
| `Real Chrome not reachable on http://127.0.0.1:9222` | Run `Launch-Real-Chrome.bat` by hand, wait for "Real Chrome is ready", then run the starter again. |
| `Chrome started but port 9222 is not answering` | Close Chrome and run `Launch-Real-Chrome.bat` again. Check no other program uses port 9222. |
| `tailscale not found` / `not logged in` | Install Tailscale (Step 4) and run `tailscale up` once, sign in, then retry. |
| Server window closes at once / `CLOUD_BROWSER_TOKEN is not set` | The `.bat` sets the token itself — if you run `server.py` by hand instead, set it first: `set CLOUD_BROWSER_TOKEN=<token from token.txt>` then `python server.py`. |
| Funnel prints an error / no URL | Check internet; close the windows and double-click the `.bat` again. |
| Server window shows `PermissionError: [WinError 10013]` on port 8765 | Fixed in the current server: it tries the next free port itself (8766, 8767, ...) and writes it to `port.txt`. Replace `server.py` with the new one and run the `.bat` again. |
| Muse's browser shows only `Your request was blocked.` | That was the free trycloudflare tunnel (see below). Use the Tailscale starter instead. |
| Page loads but says `unauthorized` | Wrong token typed. Copy it exactly from `token.txt` (no extra spaces). |
| Remote page never loads a real site | On the laptop it should work (the laptop has internet). Check the server window for an error line; check the site is not blocked. |
| Browser stops after a while | Laptop slept or internet dropped. Wake it, set Sleep to Never (Step 0), restart the `.bat`, send Muse the new URL. |

## Security — read this

The token is the **only** lock on the browser. Anyone with the public URL
**and** the token can drive the remote browser, so:

- Send the URL + token to Muse in chat only. Do not post them anywhere public.
- To change the token: close all windows, delete `token.txt`, run the
  `.bat` again — a new token is generated.
- `ids.json` holds live Facebook session cookies + passwords — keep this
  folder private, do not share the ZIP with anyone but Muse.
- The funnel URL itself is random-looking and hard to guess, but it is
  public — the token is what protects it.

## If Tailscale is not an option — Cloudflare Quick Tunnel (fallback)

**Found 2026-10-30:** the free trycloudflare tunnel blocked Muse's
browser twice with only `Your request was blocked.` — no challenge, no
UI. The free `*.trycloudflare.com` tunnel treats automated browsers as
bots. That is why Tailscale Funnel (Step 4–5 above) is the main path.
If you still want the Quick Tunnel:

1. Download **cloudflared-windows-amd64.exe** from
   https://github.com/cloudflare/cloudflared/releases, rename it to
   `cloudflared.exe`, put it in `C:\cloud-browser`.
2. Double-click **`start-cloud-browser.bat`** instead of the Tailscale one.
   It also starts Real Chrome first (same v7 check). The URL changes
   every restart — send the new one to Muse each time.

## Later: a STABLE URL (named tunnel, needs a cheap domain)

The Tailscale Funnel URL above already stays the same every restart. For a
custom URL that never changes, buy a cheap domain (about $10/year), point
its nameservers at Cloudflare, and switch from the funnel to a **named
tunnel** (`cloudflared tunnel login` + `cloudflared tunnel create <name>` +
a DNS route like `browser.yourdomain.com`). That is a separate setup for
later — nothing in this file changes for the first test.
