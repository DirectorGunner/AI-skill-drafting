@echo off
setlocal

cd /d "%~dp0"

if "%~1"=="" (
    set "BRIDGE_ARGS=--run-bridge --login-if-needed"
) else (
    set "BRIDGE_ARGS=%*"
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 "%~dp0codex_usage_check.py" %BRIDGE_ARGS%
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo Python was not found on PATH.
        echo Install Python or run codex_usage_check.py --run-bridge from an environment that has Python.
        echo.
        echo Press any key to close this window.
        pause >nul
        exit /b 1
    )
    python "%~dp0codex_usage_check.py" %BRIDGE_ARGS%
)

set "BRIDGE_EXIT=%ERRORLEVEL%"

if not "%BRIDGE_EXIT%"=="0" (
    echo.
    echo Codex usage bridge exited with code %BRIDGE_EXIT%.
    echo Press any key to close this window.
    pause >nul
)

exit /b %BRIDGE_EXIT%
