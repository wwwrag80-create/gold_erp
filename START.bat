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
if exist ".setup_done" goto FLUENT
echo  First time setup... please wait
python -m pip install --upgrade pip --quiet
python -m pip install PyQt5 qrcode pillow python-barcode --quiet
if errorlevel 1 goto NONET
echo done > .setup_done
:FLUENT
rem Modern UI library (4.69) - installed once, also on older setups
if exist ".setup_fluent" goto RUN
echo  Installing modern UI library...
python -m pip install "PyQt-Fluent-Widgets==1.11.3" --quiet
if not errorlevel 1 echo done > .setup_fluent
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
