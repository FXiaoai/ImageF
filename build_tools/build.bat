@echo off
rem Rebuild the single-file installer (the setup .exe in the workspace root).
cd /d "%~dp0"
py -3.10 build_installer.py
if errorlevel 1 "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" build_installer.py
pause
