@echo off
title Build DEBUG EXE
color 0E
cd /d "%~dp0"
echo.
echo  ==========================================
echo     BUILD DEBUG EXE  (with console window)
echo  ==========================================
echo.
echo  Use this ONLY if gold_erp.exe does not open.
echo  It builds dist\gold_erp_debug.exe that shows a black
echo  window: any startup error is printed there.
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python is not installed.
    pause
    exit /b 1
)

python -m pip install PyQt5 qrcode pillow python-barcode pyinstaller
echo.
echo  Building... wait 3-10 minutes
echo.
python core\build.py --onefile --console
if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed. Read the message above.
    pause
    exit /b 1
)
echo.
if exist "dist\gold_erp_debug.exe" (
    echo  ==========================================
    echo   DONE:  dist\gold_erp_debug.exe
    echo.
    echo   Run it. If the program closes, take a photo
    echo   of the black window and send it, together with
    echo   the files startup.log and crash.log from the
    echo   "logs" folder next to the program data.
    echo  ==========================================
    explorer dist
)
echo.
pause
