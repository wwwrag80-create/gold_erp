@echo off
title Jadeite Gold ERP
color 0E
cd /d "%~dp0"
echo.
echo  ==========================================
echo        JADEITE GOLD ERP
echo  ==========================================
echo.
python --version >nul 2>&1
if errorlevel 1 goto NOPY
if exist ".setup_done" goto RUN
echo  First time setup... please wait
python -m pip install --upgrade pip --quiet
python -m pip install PyQt5 qrcode pillow python-barcode --quiet
if errorlevel 1 goto NONET
echo done > .setup_done
:RUN
echo  Starting...
echo.
python main.py
if errorlevel 1 pause
exit /b
:NOPY
echo  [!] Python is NOT installed.
echo      Download page opens now.
echo      IMPORTANT: check "Add Python to PATH"
start https://www.python.org/downloads/
pause
exit /b
:NONET
echo  [!] Check internet connection.
pause
