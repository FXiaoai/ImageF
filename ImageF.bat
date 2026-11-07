@echo off
rem Image F (MJ restore tool) - double-click entry, works on any 64-bit Windows PC. ASCII only (cmd reads .bat in the console code page).
rem  * Python 3.10 already installed  -> tools\launcher.pyw checks numpy / OpenCV / Pillow,
rem    installs anything missing (progress bar), then opens the panel.
rem  * No Python 3.10                 -> tools\bootstrap.ps1 installs it first (progress window),
rem    then continues as above. Per-user install, no admin rights, offline files in tools\runtime.
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
rem 2) the per-user Python 3.10 that bootstrap.ps1 installs (it does not install the py launcher)
set "PY310=%LOCALAPPDATA%\Programs\Python\Python310"
if not exist "%PY310%\pythonw.exe" goto boot
"%PY310%\python.exe" -c "import tkinter" >nul 2>&1
if errorlevel 1 goto boot
start "" "%PY310%\pythonw.exe" "tools\launcher.pyw"
exit /b 0

:boot
rem 3) no usable Python 3.10: install it (wait, so that a blocked PowerShell is reported instead of doing nothing)
echo Image F: preparing Python 3.10 (first run only, about 1-2 minutes). Please keep this window open.
start "" /wait powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "tools\bootstrap.ps1"
set "RC=%errorlevel%"
if "%RC%"=="0" exit /b 0
if "%RC%"=="3" exit /b 1
echo.
echo   Automatic setup could not run (exit code %RC%). Security software may have blocked PowerShell.
echo   Log file: %~dp0tools\setup.log
echo   Please send that file, or a screenshot of this window, to the person who gave you this tool.
echo.
pause
exit /b 1
