@echo off
rem Image F (MJ restore tool) - double-click entry, works on any 64-bit Windows PC. ASCII only (cmd reads .bat in the console code page).
rem  * Python 3.10 already installed  -> tools\launcher.pyw checks numpy / OpenCV / Pillow,
rem    installs anything missing (progress bar), then opens the panel.
rem  * No Python 3.10                 -> tools\bootstrap.ps1 installs it first (progress window),
rem    then continues as above. Per-user install, no admin rights, offline files in tools\runtime.
rem  * PowerShell blocked (security software / company policy, V4.9.1) -> open tools\HELP_python.txt,
rem    start the offline Python 3.10 installer for the user (one click: Install Now), then check again
rem    and open the tool. Without the offline installer (source version) open the download page instead.
rem bootstrap.ps1 exit codes: 0 = ok, 3 = failed and already showed its own error window.
rem Flow uses goto instead of ( ) blocks so that paths containing parentheses cannot break it.
cd /d "%~dp0"
if exist "tools\launcher.pyw" goto ok
echo.
echo   Please extract (unzip) the whole folder first, then double-click this .bat again.
echo.
pause
exit /b 1

:ok
rem 1) the py launcher, if this PC has it
py -3.10 -c "import tkinter" >nul 2>&1
if errorlevel 1 goto local
start "" pyw -3.10 "tools\launcher.pyw"
exit /b 0

:local
rem 2) the per-user Python 3.10 that bootstrap.ps1 (or "Install Now" of the Python installer) puts here
set "PY310=%LOCALAPPDATA%\Programs\Python\Python310"
if not exist "%PY310%\pythonw.exe" goto boot
"%PY310%\python.exe" -c "import tkinter" >nul 2>&1
if errorlevel 1 goto boot
start "" "%PY310%\pythonw.exe" "tools\launcher.pyw"
exit /b 0

:boot
if defined IMAGEF_MANUAL goto stillno
rem 3) no usable Python 3.10: install it (wait, so that a blocked PowerShell is reported instead of doing nothing)
echo Image F: preparing Python 3.10 (first run only, about 1-2 minutes). Please keep this window open.
start "" /wait powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "tools\bootstrap.ps1"
set "RC=%errorlevel%"
if "%RC%"=="0" exit /b 0
if "%RC%"=="3" exit /b 1
>>"tools\setup.log" 2>nul echo ImageF.bat: PowerShell setup could not run, exit code %RC%. Offered the manual Python install.

rem 4) PowerShell could not run: the normal Python installer needs no PowerShell, so start it for the user
set "IMAGEF_MANUAL=1"
start "" notepad.exe "%~dp0tools\HELP_python.txt"
echo.
echo   Automatic setup was blocked (code %RC%), usually by security software.
echo   No problem: install Python 3.10 yourself. It takes about one minute.
echo   A help file has opened (Chinese + English).
echo.
set "PYEXE="
for %%F in ("%~dp0tools\runtime\python-3.10*-amd64.exe") do set "PYEXE=%%~fF"
if not defined PYEXE goto web
echo   The Python 3.10 installer is opening now. Click "Install Now".
echo   When it says "Setup was successful", click Close - Image F then opens by itself.
echo.
start "" /wait "%PYEXE%" InstallAllUsers=0 Include_launcher=0 Include_test=0
goto ok

:web
echo   This folder has no offline Python installer, so the download page opens now.
echo   Download "Windows installer (64-bit)", run it, click "Install Now",
echo   then double-click Image F (ImageF.bat) again.
echo.
start "" "https://www.python.org/downloads/release/python-31011/"
pause
exit /b 1

:stillno
echo.
echo   Python 3.10 was still not found, so Image F cannot start yet.
echo   If the Python installer was closed early, double-click Image F again to retry.
echo   Otherwise please send a screenshot of this window and this file
echo   to the person who gave you this tool:
echo   %~dp0tools\setup.log
echo.
pause
exit /b 1
