@echo off
title VIP STORE Bot - Windows AutoStart Setup
chcp 65001 > nul
echo =========================================================
echo    VIP STORE BOT - WINDOWS 24/7 AUTOSTART INSTALLER
echo =========================================================
echo.

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS_PATH=C:\Users\MOAZ AMR\.gemini\antigravity\scratch\invoice-bot\start_silent.vbs"
set "SHORTCUT_PATH=%STARTUP_DIR%\VIPStoreBot.vbs"

echo [1/2] Copying background runner to Windows Startup folder...
copy /Y "%VBS_PATH%" "%SHORTCUT_PATH%" > nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Added to Startup folder successfully!
) else (
    echo [WARN] Could not copy to startup folder.
)

echo.
echo [2/2] Registering Task Scheduler Job for 24/7 reliability...
schtasks /create /tn "VIPStoreBot247" /tr "wscript.exe \"%VBS_PATH%\"" /sc onlogon /f > nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Registered Windows Scheduled Task: VIPStoreBot247
) else (
    echo [INFO] Scheduled task setup skipped (Startup folder is active).
)

echo.
echo =========================================================
echo [SUCCESS] The Bot is now configured to start automatically 
echo           every time Windows turns on or restarts!
echo =========================================================
echo.
pause
