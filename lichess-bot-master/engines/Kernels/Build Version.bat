@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  python build_version.py v1
) else (
  python build_version.py %*
)
exit /b %errorlevel%
