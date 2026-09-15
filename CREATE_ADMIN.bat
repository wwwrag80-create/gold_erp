@echo off
title Create Super Admin Account
color 0D
cd /d "%~dp0"
echo.
echo  ==========================================
echo    CREATE YOUR SUPER ADMIN ACCOUNT
echo  ==========================================
echo.
echo  Run this ONE time.
echo  After that you can sign in from any copy.
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Install Python first from python.org
    pause
    exit /b 1
)
python tools/create_admin.py
echo.
pause
