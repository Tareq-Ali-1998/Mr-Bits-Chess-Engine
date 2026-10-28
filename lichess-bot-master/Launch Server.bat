@echo off
setlocal
cd /d "%~dp0"
python "engines\Kernels\launch_server.py" %*
if errorlevel 1 pause
