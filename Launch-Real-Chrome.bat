@echo off
REM Cloud Browser - launch the REAL installed Google Chrome for remote control
REM Double-click this file BEFORE starting the cloud browser server.
REM It opens Chrome with remote debugging on port 9222 and a dedicated
REM profile folder C:\cloud-browser\chrome-profile, so the server can drive
REM your real Chrome. Keep this Chrome window open while using the browser.
REM Your daily Chrome is untouched - this is a separate profile folder.
REM Same rules as the other launchers: NO round brackets anywhere in this
REM file, goto labels instead of IF blocks. Set CB_NO_PAUSE=1 to skip the
REM final pause when another script calls this file.
setlocal
cd /d "%~dp0"

REM --- 1. Find chrome.exe ---
set "CHROME="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if defined CHROME goto :found
where chrome >nul 2>&1
if not errorlevel 1 goto :in_path
echo [ERROR] Google Chrome not found.
echo Install Google Chrome from https://www.google.com/chrome/ then run this file again.
pause
exit /b 1
:in_path
set "CHROME=chrome"
:found

REM --- 2. Is Chrome with debugging already answering on port 9222? ---
where curl >nul 2>&1
if errorlevel 1 goto :launch
curl -s http://127.0.0.1:9222/json/version >nul 2>&1
if not errorlevel 1 goto :already
:launch
echo Starting real Chrome with remote debugging on port 9222 ...
echo Profile folder: C:\cloud-browser\chrome-profile
start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir=C:\cloud-browser\chrome-profile --no-first-run --start-maximized
timeout /t 5 /nobreak >nul
where curl >nul 2>&1
if errorlevel 1 goto :nocurl
curl -s http://127.0.0.1:9222/json/version >nul 2>&1
if not errorlevel 1 goto :ok
echo [ERROR] Chrome started but port 9222 is not answering.
echo Close Chrome and run this file again. If it keeps failing, check that
echo no other program is using port 9222.
pause
exit /b 1
:already
echo Real Chrome is already running with debugging on port 9222.
goto :ok
:nocurl
echo Chrome launched. curl is not available to verify port 9222, so if the
echo server later says Real Chrome is not reachable, close Chrome and retry.
goto :ok
:ok
echo.
echo Real Chrome is ready. Now double-click start-cloud-browser-tailscale.bat
echo to start the cloud browser server. Keep this Chrome window open.
if defined CB_NO_PAUSE exit /b 0
pause
