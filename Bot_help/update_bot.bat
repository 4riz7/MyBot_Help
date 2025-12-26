@echo off
chcp 65001 >nul
title Bot Update Manager
cls

echo ==========================================
echo 🤖 Bot Update Manager (Windows)
echo ==========================================

echo.
echo 🛑 Stopping any running Python bots...
taskkill /F /IM python.exe /T 2>nul
echo Done.

echo.
echo 🛠  Starting maintenance mode...
echo    (Starting maintenance.py in background)
start /B python maintenance.py > maintenance.log 2>&1

echo.
echo ⏳ The bot is now in MAINTENANCE MODE.
echo    Users will see a 'Technical break' message.
echo.
echo 👉 Pulling updates from git...
git pull

echo.
echo 🔄 Updating libraries...
pip uninstall -y pyrogram 2>nul
pip install -r requirements.txt --upgrade

echo.
echo ------------------------------------------
echo ✅ Update finished! 
echo ------------------------------------------
echo.
pause

echo.
echo 🛑 Stopping maintenance mode...
taskkill /F /IM python.exe /T 2>nul

echo.
echo 🚀 Starting main bot...
start "My Telegram Bot" python main.py

echo.
echo ==========================================
echo 🎉 Bot started! You can close this window.
echo ==========================================
timeout /t 5
