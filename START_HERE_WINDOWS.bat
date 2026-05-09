@echo off
setlocal

title ChatVault Starter
cd /d "%~dp0"

rem Optional: set CHATVAULT_PYTHON to a full python.exe path if Python is not on PATH.
rem Example: set "CHATVAULT_PYTHON=C:\Path\To\Python313\python.exe"

echo.
echo Starting ChatVault...
echo.

if defined CHATVAULT_PYTHON (
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_chatvault.ps1" -PythonExe "%CHATVAULT_PYTHON%"
) else (
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_chatvault.ps1"
)
set "status=%ERRORLEVEL%"

if not "%status%"=="0" (
    echo.
    echo ChatVault did not start successfully.
    echo Press any key to close this window.
    pause >nul
)

exit /b %status%
