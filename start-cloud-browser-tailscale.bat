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
REM v7: the server now drives the REAL installed Google Chrome
REM (CLOUD_BROWSER_REAL_CHROME=1), not Playwright's Chromium.
REM Launch-Real-Chrome.bat starts it first; this file checks it.
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
echo Playwright installed. Skipping the Chromium download - v7 uses your
echo real installed Google Chrome, not the bundled Chromium.
goto :pw_ok
:pip_fail
echo [ERROR] pip install playwright failed.
echo Check your internet, then double-click this file again.
echo If pip says not recognized, reinstall Python with PATH ticked.
pause
exit /b 1
:pw_ok

REM --- 2b. Real Chrome: the server drives the REAL installed Google Chrome ---
REM v7: no more Playwright Chromium. Launch Real Chrome first if needed.
REM Launch-Real-Chrome.bat opens it with remote debugging on port 9222.
set "CLOUD_BROWSER_REAL_CHROME=1"
set "CB_NO_PAUSE=1"
call "%~dp0Launch-Real-Chrome.bat"
if errorlevel 1 goto :chrome_fail
set "CB_NO_PAUSE="
goto :chrome_ok
:chrome_fail
echo [ERROR] Real Chrome could not be started.
echo Run Launch-Real-Chrome.bat by hand and follow what it says,
echo then double-click this file again.
pause
exit /b 1
:chrome_ok

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
REM Wait for the server to write port.txt (it binds a free port itself).
REM A fixed 5s was too short when port 8765 was blocked - the server needs
REM a moment to try the next port. Wait up to 30s for the file.
for /l %%i in (1,1,30) do (
  if exist "%~dp0port.txt" goto :port_ready
  timeout /t 1 /nobreak >nul
)
echo [ERROR] Server did not write port.txt in 30s. Check the server window.
pause
exit /b 1
:port_ready

REM --- 6. Start Tailscale Funnel in THIS window, URL appears below ---
REM Read the port the server actually bound, from port.txt.
set "ACTUAL_PORT=8765"
for /f "usebackq delims=" %%P in ("%~dp0port.txt") do set "ACTUAL_PORT=%%P"
echo.
echo Starting Tailscale Funnel on port !ACTUAL_PORT! - your public URL appears below.
echo Keep this window AND the server window open while browsing.
echo.
tailscale funnel !ACTUAL_PORT!
echo.
echo Funnel stopped. To restart, double-click this file again.
echo The funnel address stays the same every restart - send it to Muse once.
pause
