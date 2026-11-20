@echo off
title VIP STORE Unified Bot 24/7 Watchdog
chcp 65001 > nul
cd /d "C:\Users\MOAZ AMR\.gemini\antigravity\scratch\invoice-bot"
echo ===================================================
echo     VIP STORE BOT - AUTO RESTART SUPERVISOR 24/7
echo ===================================================
"C:\Users\MOAZ AMR\AppData\Local\Programs\Python\Python312\python.exe" watchdog.py
pause
