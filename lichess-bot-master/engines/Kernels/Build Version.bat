@echo off
setlocal
set "VERSION=%~1"
if "%VERSION%"=="" set "VERSION=v1"
if "%VERSION%"=="v1" goto build
if "%VERSION%"=="v2" goto build
if "%VERSION%"=="v3" goto build
echo Usage: "Build Version.bat" v1^|v2^|v3
exit /b 2
:build
pushd "%~dp0.." || exit /b 1
g++ -std=c++17 -O2 -I. "Kernels\%VERSION%\Kernel-%VERSION%.cpp" -o "Kernels\%VERSION%\Kernel-%VERSION%.exe"
set "RESULT=%errorlevel%"
popd
exit /b %RESULT%
