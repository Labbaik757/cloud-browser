# Deploy Cloud Browser v1 on Render (free) — step by step

## Why NOT Netlify

Do NOT deploy this to Netlify. Netlify is static hosting + serverless
Functions only. Functions time out at 10 seconds by default (max 26–30s
even on paid plans) and have no persistent memory or disk between calls.
`server.py` is a persistent Python process holding a live Playwright
Chromium session that runs **unlimited until Stop** — that cannot run on
Netlify. The correct host type is a persistent container host. This pack
targets **Render free web service (Docker)**.

## Render free limits (honest)

- 750 hours/month free; **sleeps after 15 minutes idle** — the first
  request after sleep takes ~30–60s to wake the service.
- **512 MB RAM, shared CPU** — tight for Chromium. Light pages should
  work; heavy pages (many tabs/media) may be slow or crash the browser
  process (out-of-memory). If that happens, the fix is a paid Render
  plan with more RAM, not a code change.
- Single session at a time (v1 scope); starting a new session destroys
  the old one.
- Live internet browsing on the deployed host is **still unproven until
  a real deploy happens** — the VM could not test it (no internet path
  for Chromium there). The first real-site test must happen on the live
  Render URL.

## Step 1 — Push the code to GitHub

From your PC (or any machine with git + this folder):

```bash
cd cloud-browser
git init
git add server.py index.html test-page.html test-page2.html test_v1.py test_v2.py \
  requirements.txt Dockerfile .dockerignore render.yaml \
  README.md TEST-REPORT.md DEPLOY.md LAPTOP-SETUP.md start-cloud-browser.bat
git commit -m "Cloud Browser v2 — token auth + Render deploy pack"
# Create an EMPTY repo on github.com first (e.g. cloud-browser),
# then:
git remote add origin https://github.com/<your-user>/cloud-browser.git
git push -u origin main
```

Repo layout: the files above must be at the **repo root**, because
`render.yaml` points at `./Dockerfile`.

No secrets are in this repo. No account, key, or credential is needed
in the code.

## Step 2 — Create the Render service

1. Go to https://dashboard.render.com/ and sign in (free account).
2. **New → Web Service** → **Build and deploy from a Git repository** →
   select the `cloud-browser` repo.
3. Render detects `render.yaml` (Blueprint) or asks for settings — use:
   - **Runtime:** Docker
   - **Dockerfile path:** `./Dockerfile`
   - **Plan:** Free
   - **Health check path:** `/`
   - **Environment:** `CLOUD_BROWSER_TOKEN` is generated automatically
     by the Blueprint (`generateValue: true`). After the first deploy,
     read it back in the dashboard under **Environment** — that is the
     token you give Muse with the URL. (If you deploy without the
     Blueprint, set `CLOUD_BROWSER_TOKEN` yourself to a long random
     value; the server refuses to start without it.)
4. Click **Deploy**. First build takes several minutes — the Playwright
   base image is large (~2 GB).

## Step 3 — Open it

Your public URL is shown on the Render dashboard, e.g.:

```
https://cloud-browser.onrender.com/
```

1. Open it in any browser. The page should show the Cloud Browser UI.
   (If it just deployed or slept, wait ~30–60s and reload — it is
   waking up, not broken.)
2. First test: leave the default URL (the local test page) and click
   **Start Session**. The live view should load the test page, the
   button click should work, and the session timer should keep counting
   up with no limit.
3. Then try a real site in the URL bar, e.g. `https://example.org`.
   This is the first live-internet test — report whether it loads.

## Step 4 — How Muse's live browser uses it

Give Muse the public Render URL **and** the `CLOUD_BROWSER_TOKEN`
(from the dashboard → Environment). Muse's live browser opens that
URL directly — no install, no sign-in. She types the token into the
**Unlock** box, then can Start a session, browse, click, and type
through the cloud browser, and Stop it when done. Without the token
every `/api/*` call returns 401 and no session data is exposed.

## If the service sleeps

Free Render services sleep after 15 min idle. Symptoms: first load is
slow or times out once, then works on reload. That is expected on the
free plan. A paid Render plan ($7+/month) removes sleeping; the code
needs no change for that.

## Files in this pack

| File | Purpose |
|---|---|
| `server.py` | App server (binds `0.0.0.0`, reads `PORT` from env, token auth on every `/api/*`) |
| `index.html` | UI (token Unlock box + full-control live view) |
| `test-page.html` / `test-page2.html` | Local test pages |
| `Dockerfile` | Playwright `v1.64.1-jammy` base image |
| `requirements.txt` | `playwright==1.64.1` |
| `.dockerignore` | Keeps tests/docs out of the image |
| `render.yaml` | Render Docker web service, free plan (generates `CLOUD_BROWSER_TOKEN`) |
| `test_v1.py` / `test_v2.py` | Local end-to-end tests (16 + 33 checks, plus token 401 checks) |
| `LAPTOP-SETUP.md` / `start-cloud-browser.bat` | Windows laptop + Cloudflare Quick Tunnel setup (alternative to Render) |
