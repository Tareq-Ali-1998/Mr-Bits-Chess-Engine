@echo off
rem Builds Mr. Bits with plain g++, like always: Engine UCI.exe (with SQLite inside it) and Kernel.exe.
rem
rem Every build gets a timestamp for provenance. Windows application trust must be resolved separately.
rem If Windows blocks startup, review Code Integrity events before another startup attempt.
rem
rem   Build Engines.bat          builds both, then checks that Windows lets them run
rem   Build Engines.bat test     the same, then runs tests\engine_test.py (about a minute)

setlocal
cd /d "%~dp0"
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set STAMP=%%t

rem SQLite is one big C file (sqlite\sqlite3.c), so it's compiled only once and then just linked.
if not exist "sqlite\sqlite3.o" (
    echo Compiling SQLite once, about 30 seconds...
    gcc -O2 -DSQLITE_DQS=0 -DSQLITE_DEFAULT_FOREIGN_KEYS=1 -DSQLITE_OMIT_LOAD_EXTENSION -c "sqlite\sqlite3.c" -o "sqlite\sqlite3.o" || goto failed
)

echo Building Engine UCI.exe (build %STAMP%)...
g++ -DMRBITS_BUILD_STAMP=\"%STAMP%\" "Engine UCI.cpp" "sqlite\sqlite3.o" -o "Engine UCI.exe" || goto failed
echo Building Kernel.exe (build %STAMP%)...
g++ -DMRBITS_BUILD_STAMP=\"%STAMP%\" "Kernel.cpp" -o "Kernel.exe" || goto failed

rem Check startup only after compilation; both programs exit at the end of their input.
".\Engine UCI.exe" <nul >nul || goto blocked
".\Kernel.exe" <nul >nul || goto blocked
echo Both of them run. Build %STAMP% is ready.

if /i "%~1"=="test" python -B tests\engine_test.py
exit /b %errorlevel%

:blocked
echo A startup check failed. Review the error and Windows Code Integrity events.
echo Resolve application trust before trying startup again.
exit /b 1

:failed
echo The build failed, see the errors above. (If lichess-bot is still running a game, the .exe files are in use.)
exit /b 1
