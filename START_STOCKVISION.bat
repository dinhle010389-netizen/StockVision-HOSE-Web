@echo off
setlocal
cd /d "%~dp0"
title StockVision HOSE - Windows Desktop

echo ========================================================
echo   StockVision HOSE - Windows Desktop 0.3
echo   Khong can Docker hoac WSL
echo ========================================================
echo.

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Da tao file .env tu cau hinh mau.
)

set "PYTHON_CMD="
where py >nul 2>nul
if %errorlevel%==0 (
  py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
  if %errorlevel%==0 set "PYTHON_CMD=py -3.13"
  if not defined PYTHON_CMD (
    py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if %errorlevel%==0 set "PYTHON_CMD=py -3.12"
  )
  if not defined PYTHON_CMD (
    py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if %errorlevel%==0 set "PYTHON_CMD=py -3.11"
  )
)
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if %errorlevel%==0 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if %errorlevel%==0 set "PYTHON_CMD=python"
  )
)

if not defined PYTHON_CMD (
  echo Chua tim thay Python 3.11 hoac moi hon.
  echo Hay cai Python tu trang chinh thuc, chon Add python.exe to PATH,
  echo roi chay lai START_STOCKVISION.bat.
  start "" "https://www.python.org/downloads/windows/"
  pause
  exit /b 2
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Tao moi truong Python rieng cho StockVision...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :error
)

echo [2/3] Kiem tra/cai thu vien can thiet (lan dau can Internet)...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-windows.txt
if errorlevel 1 goto :error

echo [3/3] Khoi dong StockVision...
.venv\Scripts\python.exe desktop_launcher.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo StockVision gap loi. Hay chup man hinh nay gui cho ho tro.
pause
exit /b 1
