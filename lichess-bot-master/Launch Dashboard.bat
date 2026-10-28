@echo off
setlocal
cd /d "%~dp0"
python "database\dashboard\server.py" --open %*
if errorlevel 1 pause
