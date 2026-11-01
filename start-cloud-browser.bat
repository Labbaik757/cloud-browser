@echo off
REM Cloud Browser - Windows laptop launcher - Quick Tunnel version
REM Double-click this file. It starts server.py, then exposes it
REM on a public https://*.trycloudflare.com URL.
REM Keep this window AND the Cloud Browser Server window open
REM while you use the browser. Closing either stops it.
REM No domain, no account, no card needed for this first test.
REM The public URL changes every restart - send the new URL
REM and the token below to Muse each time you start it.
REM
REM v2 fix 2026-10-30: old file died at once with
REM "... was unexpected at this time" because it had round brackets
REM inside IF blocks. This version has NO round brackets anywhere
REM and uses goto labels instead of IF blocks, so cmd cannot
REM misread it. Token is made with RANDOM, no PowerShell needed.
REM v3 fix 2026-10-30: cloudflared.exe was in the folder but still
REM named cloudflared-windows-amd64.exe, so the bat now renames it
REM itself. Also handles the cloudflared.exe.exe double-extension case.
REM Error branch now lists matching files, so the real name shows.
REM v4 fix 2026-10-30: server picks a free port itself and writes it
REM to port.txt, because Windows sometimes forbids port 8765 with
REM WinError 10013. The bat reads port.txt and tunnels that port.
REM NOTE 2026-10-30: the free trycloudflare tunnel blocked Muse's
REM browser twice with Your request was blocked, so if that happens
REM use start-cloud-browser-tailscale.bat instead, same folder.
REM v7: the server now drives the REAL installed Google Chrome
REM (CLOUD_BROWSER_REAL_CHROME=1), not Playwright's Chromium.
REM Launch-Real-Chrome.bat starts it first; this file checks it.
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

REM --- 3. cloudflared present? Same folder first, then PATH ---
REM If the downloaded file still has its original name, rename it now.
if exist "%~dp0cloudflared-windows-amd64.exe" ren "%~dp0cloudflared-windows-amd64.exe" cloudflared.exe
if exist "%~dp0cloudflared.exe.exe" ren "%~dp0cloudflared.exe.exe" cloudflared.exe
set "CF=cloudflared"
if exist "%~dp0cloudflared.exe" set "CF=%~dp0cloudflared.exe"
where cloudflared >nul 2>&1
if not errorlevel 1 goto :cf_ok
if exist "%~dp0cloudflared.exe" goto :cf_ok
echo [ERROR] cloudflared not found.
echo Download cloudflared-windows-amd64.exe from:
echo   https://github.com/cloudflare/cloudflared/releases
echo Rename it to cloudflared.exe and put it in this same folder,
echo then double-click this file again.
echo If Windows SmartScreen blocks it, right-click the file,
echo Properties, tick Unblock, OK.
echo Files in this folder starting with cloudflared:
dir /b "%~dp0cloudflared*"
pause
exit /b 1
:cf_ok

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
set "WAIT_N=0"
:wait_port
if exist "%~dp0port.txt" goto :port_ready
timeout /t 1 /nobreak >nul
set /a WAIT_N+=1
if %WAIT_N% lss 30 goto :wait_port
echo [ERROR] Server did not write port.txt in 30s. Check the server window.
pause
exit /b 1
:port_ready

REM --- 6. Start the Quick Tunnel in THIS window, URL appears below ---
REM Read the port the server actually bound, from port.txt.
set "ACTUAL_PORT=8765"
if exist "%~dp0port.txt" set /p ACTUAL_PORT < "%~dp0port.txt"
echo.
echo Starting Cloudflare Quick Tunnel on port !ACTUAL_PORT! - your public URL appears below.
echo Keep this window AND the server window open while browsing.
echo If Windows Firewall asks about Python, click Allow, private network.
echo.
"%CF%" tunnel --url http://localhost:!ACTUAL_PORT!
echo.
echo Tunnel stopped. To restart, double-click this file again.
echo A new tunnel URL is generated every restart - send the new one to Muse.
pause
