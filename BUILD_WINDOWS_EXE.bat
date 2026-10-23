@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Build StockVision HOSE EXE

echo ========================================================
echo   StockVision HOSE - Tao file EXE cho Windows
echo   Chi can chay 1 lan tren Windows de tao EXE
echo ========================================================
echo.

set "PY_CMD="
where py >nul 2>nul
if %errorlevel%==0 (
  py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY_CMD=py -3.12"
  if not defined PY_CMD (
    py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3.13"
  )
  if not defined PY_CMD (
    py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3.11"
  )
)
if not defined PY_CMD (
  echo Chua tim thay Python 3.11, 3.12 hoac 3.13.
  echo Trinh dung EXE can Python tam thoi, nhung EXE tao ra se khong can Python.
  echo Hay cai Python tu trang chinh thuc va chon Add Python to PATH:
  start "" "https://www.python.org/downloads/windows/"
  pause
  exit /b 2
)

if not exist ".build-venv\Scripts\python.exe" (
  echo [1/4] Tao moi truong build rieng...
  %PY_CMD% -m venv .build-venv
  if errorlevel 1 goto :error
)

echo [2/4] Cai thu vien can thiet va PyInstaller...
".build-venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :error
".build-venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-windows.txt pyinstaller==6.22.3
if errorlevel 1 goto :error

echo.
echo Co the bo sung chuoi du lieu cong khai DNSE/Vietcap/VNDirect/CafeF vao EXE.
echo Tuy chon nay can Git for Windows va ket noi Internet.
set "SV_PUBLIC_DATA=n"
set /p "SV_PUBLIC_DATA=Ban co muon dong goi public-data provider vao EXE? (y/N): "
if /I "%SV_PUBLIC_DATA%"=="Y" (
  where git >nul 2>nul
  if errorlevel 1 (
    echo Khong tim thay Git. EXE se duoc build ma khong co public-data provider.
  ) else (
    ".build-venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-public-data.txt
    if errorlevel 1 goto :error
  )
)

echo [3/4] Dang dong goi EXE... (co the mat vai phut lan dau)
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean StockVisionHOSE.spec
if errorlevel 1 goto :error

if not exist "dist\StockVisionHOSE.exe" (
  echo Khong tim thay dist\StockVisionHOSE.exe sau khi build.
  goto :error
)
copy /y ".env.example" "dist\.env.example" >nul
copy /y "CONFIG_FIREANT_EXE.bat" "dist\CONFIG_FIREANT.bat" >nul
copy /y "README_EXE_VI.txt" "dist\HUONG_DAN.txt" >nul
copy /y "FIREANT_SETUP_VI.md" "dist\FIREANT_SETUP_VI.md" >nul

echo [4/4] Hoan tat.
echo.
echo EXE cua bro nam tai:
echo %CD%\dist\StockVisionHOSE.exe
echo Hay chay EXE mot lan de tao cau hinh lan dau.
echo File .env duoc luu tai %%LOCALAPPDATA%%\StockVisionHOSE\.env
start "" "%CD%\dist"
pause
exit /b 0

:error
echo.
echo Tao EXE that bai. Kiem tra loi phia tren va Internet.
pause
exit /b 1
