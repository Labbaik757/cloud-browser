@echo off
REM Cloud Browser - Windows laptop launcher - Tailscale Funnel version
REM Double-click this file. It starts server.py, then exposes it
REM on your stable Tailscale address, like
REM https://your-laptop-name.your-tailnet.ts.net
REM Keep this window AND the Cloud Browser Server window open
REM while you use the browser. Closing either stops it.
REM
REM Why this file exists: the free Cloudflare Quick Tunnel blocked
REM Muse's browser twice with Your request was blocked, because
REM trycloudflare.com treats automated browsers as bots. Tailscale
REM Funnel has no such block, no card, no domain, and the address
REM stays the same every restart.
REM
REM You need Tailscale installed and signed in once, see step 3 below.
REM Same rules as the cloudflared version: NO round brackets anywhere
REM in this file, goto labels instead of IF blocks, token via RANDOM.
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "PY=python"

REM --- 1. Find Python, python first, py launcher as fallback ---
where python >nul 2>&1
if not errorlevel 1 goto :py_found
where py >nul 2>&1
if not errorlevel 1 goto :py_launcher
echo [ERROR] Python not found.
echo Install Python 3.12 from https://www.python.org/downloads/
echo IMPORTANT: tick Add python.exe to PATH during install,
echo then double-click this file again.
pause
exit /b 1
:py_launcher
set "PY=py"
:py_found

REM --- 2. Playwright installed? If not, install it, first run only ---
%PY% -c "import playwright" 2>nul
if not errorlevel 1 goto :pw_ok
echo Playwright not found - installing it now, first run only ...
%PY% -m pip install --upgrade pip
%PY% -m pip install playwright
if errorlevel 1 goto :pip_fail
echo Downloading Chromium for Playwright - first run only, about 150 MB ...
%PY% -m playwright install chromium
if errorlevel 1 goto :chromium_fail
goto :pw_ok
:pip_fail
echo [ERROR] pip install playwright failed.
echo Check your internet, then double-click this file again.
echo If pip says not recognized, reinstall Python with PATH ticked.
pause
exit /b 1
:chromium_fail
echo [ERROR] playwright install chromium failed.
echo Check internet and free disk space, check antivirus is not
echo blocking the download, then double-click this file again.
pause
exit /b 1
:pw_ok

REM --- 3. Tailscale present and logged in? ---
where tailscale >nul 2>&1
if not errorlevel 1 goto :ts_found
echo [ERROR] tailscale not found.
echo Install Tailscale from https://tailscale.com/download
echo then run tailscale up once and sign in, then double-click this file again.
pause
exit /b 1
:ts_found
tailscale status >nul 2>&1
if not errorlevel 1 goto :ts_ok
echo [ERROR] Tailscale is installed but not logged in yet.
echo Open Command Prompt in this folder and run tailscale up
echo then sign in in the browser, then double-click this file again.
pause
exit /b 1
:ts_ok

REM --- 4. Token: reuse the one already set, else make one and save it ---
REM The token is the ONLY lock on the browser. Anyone with the public URL
REM and this token can drive it, so keep it private - send it to Muse only.
if defined CLOUD_BROWSER_TOKEN goto :token_ready
set "CLOUD_BROWSER_TOKEN=cb-%RANDOM%-%RANDOM%-%RANDOM%-%RANDOM%"
:token_ready
echo !CLOUD_BROWSER_TOKEN! > token.txt
echo.
echo ============================================================
echo  YOUR TOKEN - keep it safe, send it to Muse with the URL:
echo  !CLOUD_BROWSER_TOKEN!
echo ============================================================
echo Token also saved in token.txt, same folder as this file.

REM --- 5. Start the server in its own window ---
REM It inherits CLOUD_BROWSER_TOKEN from this window. Do NOT close it.
REM Delete the old port file first, so the server writes a fresh one.
if exist "%~dp0port.txt" del "%~dp0port.txt"
echo.
echo Starting Cloud Browser server - it picks a free port itself ...
start "Cloud Browser Server" cmd /k %PY% "%~dp0server.py"
timeout /t 5 /nobreak >nul

REM --- 6. Start Tailscale Funnel in THIS window, URL appears below ---
REM Read the port the server actually bound, from port.txt.
set "ACTUAL_PORT=8765"
if exist "%~dp0port.txt" set /p ACTUAL_PORT < "%~dp0port.txt"
echo.
echo Starting Tailscale Funnel on port !ACTUAL_PORT! - your public URL appears below.
echo Keep this window AND the server window open while browsing.
echo.
tailscale funnel !ACTUAL_PORT!
echo.
echo Funnel stopped. To restart, double-click this file again.
echo The funnel address stays the same every restart - send it to Muse once.
pause
