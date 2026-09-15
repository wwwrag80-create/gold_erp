@echo off
title Build EXE
color 0B
cd /d "%~dp0"
echo.
echo  ==========================================
echo     BUILD ONE EXE FILE
echo  ==========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python is not installed.
    pause
    exit /b 1
)

echo  [1/4] Removing old build...
if exist "dist\gold_erp.exe" del /f /q "dist\gold_erp.exe"
if exist "build" rmdir /s /q "build"
for %%f in (*.spec) do del /f /q "%%f"
echo         OK
echo.

echo  [2/4] Installing tools...
python -m pip install --upgrade pip
python -m pip install PyQt5 qrcode pillow python-barcode pyinstaller
echo.

echo  [3/4] Checking PyInstaller...
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] PyInstaller not installed.
    echo          Run:  python -m pip install pyinstaller
    pause
    exit /b 1
)
echo         OK
echo.

echo  [4/4] Building... wait 3-10 minutes
echo.
python core\build.py --clean --onefile
if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed. Read the message above.
    pause
    exit /b 1
)

echo.
if exist "dist\gold_erp.exe" (
    echo  ==========================================
    echo   SUCCESS
    echo   File:  dist\gold_erp.exe
    echo.
    echo   IMPORTANT: delete any OLD copy of the exe
    echo   before testing, and check the build stamp
    echo   on the login screen.
    echo  ==========================================
    explorer dist
) else (
    echo  [ERROR] dist\gold_erp.exe was not created.
)
echo.
pause
