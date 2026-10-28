@echo off
rem Builds Mr. Bits with plain g++, like always: Engine UCI.exe (with SQLite inside it) and Kernel.exe.
rem
rem Every build gets a new stamp (its date and time), so every .exe gets a new hash. That matters on this PC:
rem Windows Smart App Control judges every new .exe on its first launch, and when it blocks one, running this
rem file again is enough (a new hash gets a new verdict).
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

rem The first launch of a new .exe is where Smart App Control decides (both exit at the end of their input).
".\Engine UCI.exe" <nul >nul || goto blocked
".\Kernel.exe" <nul >nul || goto blocked
echo Both of them run. Build %STAMP% is ready.

if /i "%~1"=="test" python -B tests\engine_test.py
exit /b %errorlevel%

:blocked
echo Windows blocked the new build (Smart App Control). Run Build Engines.bat again: a new build gets a new verdict.
exit /b 1

:failed
echo The build failed, see the errors above. (If lichess-bot is still running a game, the .exe files are in use.)
exit /b 1
