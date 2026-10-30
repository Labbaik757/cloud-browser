# Cloud Browser — Windows laptop setup (Cloudflare Quick Tunnel)

**Goal:** run the self-built cloud browser on Afnan's Windows laptop (8 GB RAM,
residential internet) and expose it on a public link, so Muse can open that
link in her own browser and drive the remote browser with her native
capabilities (click, type, scroll, navigate) — exactly like Browser.lol.

**No domain, no account, no card needed for this first test.** The Quick
Tunnel gives a random public URL each restart. A stable URL needs a cheap
domain later — see the last section.

## What you need

- Windows 10 or 11 laptop, 8 GB RAM, internet.
- This `cloud-browser` folder, copied to the laptop — put it at
  `C:\cloud-browser` (it must contain `server.py`, `index.html`,
  `test-page.html`, `test-page2.html`, `requirements.txt` and
  `start-cloud-browser.bat`).
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

## Step 2 — Install Playwright + Chromium (first run only)

The launcher script (`start-cloud-browser.bat`) does this for you
automatically if Playwright is missing. To do it by hand instead, in
Command Prompt from `C:\cloud-browser`:

```bat
python -m pip install playwright
python -m playwright install chromium
```

What you should see: pip downloads packages, then Chromium downloads
(about 150 MB). If it fails: check internet, check free disk space
(need ~500 MB), check antivirus is not blocking the download, then retry
the same two commands.

## Step 3 — Get cloudflared (first run only)

1. Open https://github.com/cloudflare/cloudflared/releases in your browser.
2. Download **cloudflared-windows-amd64.exe** (latest release).
3. Rename it to `cloudflared.exe` and put it in `C:\cloud-browser`
   (same folder as `server.py`).
4. Check it worked: in Command Prompt from that folder,
   `cloudflared --version` should print a version number.
5. If Windows SmartScreen blocks it: right-click the file → Properties →
   tick **Unblock** → OK. If the browser warns on download, keep the file
   — it is the official Cloudflare release.

## Step 4 — Start it (double-click)

Double-click **`start-cloud-browser.bat`** in `C:\cloud-browser`.

What you should see, in order:

1. A **"Cloud Browser Server"** window opens and prints
   `Cloud Browser v2 — http://0.0.0.0:8765/` and `Token auth ON`.
   (First run: it installs Playwright/Chromium first, so this takes
   a few minutes. Leave it alone.) If port 8765 is blocked on your
   laptop (WinError 10013), the server picks the next free port
   itself (8766, 8767, ...) and prints that one instead, and writes
   it to `port.txt` — the launcher reads it, nothing for you to change.
2. The main window prints **YOUR TOKEN** (a long code) and saves it to
   `token.txt` in the same folder.
3. The main window then prints a public URL like
   `https://something-trycloudflare.com` — that is the link to use.
4. If Windows Firewall asks about Python: click **Allow** (private
   network). Without this the tunnel cannot reach the server.

**Leave both windows open while browsing.** Closing either stops it.

## Step 5 — Give Muse the link + token

Send Muse (in chat) two things:

1. The public URL from the tunnel window, e.g.
   `https://random-words.trycloudflare.com`
2. The token from the window / `token.txt`.

Muse opens that URL in her own browser, types the token into the
**Unlock** box, clicks **Start Session**, and drives the remote browser
from there — URL bar, click, type, scroll, Back/Forward/Reload, all
unlimited until Stop. **The URL changes every restart** — after any
restart, send Muse the new URL (the token stays the same unless you
delete `token.txt` and restart, which makes a new one).

## If something fails

| What you see | Do this |
|---|---|
| `python not found` | Reinstall Python 3.12 with **Add to PATH** ticked (Step 1). |
| `pip install playwright` fails | Check internet; retry. If pip is "not recognized", fix PATH (Step 1). |
| `playwright install chromium` fails | Check internet + disk space (~500 MB free); check antivirus; retry. |
| `cloudflared not found` | Put `cloudflared.exe` in the folder (Step 3); unblock it in Properties if SmartScreen blocks it. |
| Server window closes at once / `CLOUD_BROWSER_TOKEN is not set` | The `.bat` sets the token itself — if you run `server.py` by hand instead, set it first: `set CLOUD_BROWSER_TOKEN=<token from token.txt>` then `python server.py`. |
| Tunnel prints an error / no URL | Check internet; close the windows and double-click the `.bat` again. A new URL is generated each restart. |
| Server window shows `PermissionError: [WinError 10013]` on port 8765 | Fixed in the current server: it tries the next free port itself (8766, 8767, ...) and writes it to `port.txt`. Replace `server.py` with the new one and run the `.bat` again. |
| Muse's browser shows only `Your request was blocked.` | The free trycloudflare tunnel blocks automated browsers. Use the Tailscale option below instead. |
| Page loads but says `unauthorized` | Wrong token typed. Copy it exactly from `token.txt` (no extra spaces). |
| Remote page never loads a real site | On the laptop it should work (the laptop has internet). Check the server window for an error line; check the site is not blocked. |
| Browser stops after a while | Laptop slept or internet dropped. Wake it, set Sleep to Never (Step 0), restart the `.bat`, send Muse the new URL. |

## Security — read this

The token is the **only** lock on the browser. Anyone with the public URL
**and** the token can drive the remote browser, so:

- Send the URL + token to Muse in chat only. Do not post them anywhere public.
- To change the token: close both windows, delete `token.txt`, run the
  `.bat` again — a new token is generated.
- The tunnel URL itself is random and hard to guess, but it is public —
  the token is what protects it.

## If the Cloudflare link gets blocked — use Tailscale Funnel instead

**Found 2026-10-30:** the free trycloudflare tunnel blocked Muse's
browser twice with only `Your request was blocked.` — no challenge, no
UI. The free `*.trycloudflare.com` tunnel treats automated browsers as
bots. The fix is **Tailscale Funnel**: free, no card, no domain, and the
address stays the same every restart.

1. Install Tailscale from https://tailscale.com/download and run it.
2. Open Command Prompt and run `tailscale up`, then sign in in the
   browser when it asks (Google / GitHub / Microsoft — any works).
3. Double-click **`start-cloud-browser-tailscale.bat`** in
   `C:\cloud-browser` instead of the cloudflared one.
4. It prints a public URL like
   `https://your-laptop-name.your-tailnet.ts.net` — send that + the
   token to Muse, same as Step 5 above. The address does not change
   on restart, so you only send it once.

## Later: a STABLE URL (named tunnel, needs a cheap domain)

The Quick Tunnel URL above changes every restart. For a URL that never
changes, buy a cheap domain (about $10/year), point its nameservers at
Cloudflare, and switch from Quick Tunnel to a **named tunnel**
(`cloudflared tunnel login` + `cloudflared tunnel create <name>` +
a DNS route like `browser.yourdomain.com`). That is a separate setup for
later — nothing in this file changes for the first test.
