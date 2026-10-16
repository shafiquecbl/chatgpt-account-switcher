@echo off
setlocal
cd /d "%~dp0"
set PORT=5252

echo ========================================================
echo       ChatGPT Account Switcher (Windows Launcher)
echo ========================================================
echo.

:: Check if Python is installed
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 3 was not found in your PATH.
    echo Please install Python 3 from https://python.org or the Microsoft Store.
    echo.
    pause
    exit /b 1
)

:: Check if server is already running on port 5252
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [INFO] ChatGPT Switcher is already active on port %PORT%.
) else (
    echo [INFO] Starting ChatGPT Switcher background server on port %PORT%...
    start /b "" python web\server.py > "%TEMP%\chatgpt-switcher.log" 2>&1
    timeout /t 1 /nobreak >nul
)

echo [INFO] Opening dashboard in your default browser...
start http://localhost:%PORT%

echo.
echo [SUCCESS] Dashboard launched! You can manage your accounts at http://localhost:%PORT%
echo.
