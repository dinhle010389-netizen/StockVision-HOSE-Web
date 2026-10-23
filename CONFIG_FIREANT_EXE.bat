@echo off
setlocal
set "CFGDIR=%LOCALAPPDATA%\StockVisionHOSE"
set "CFG=%CFGDIR%\.env"
if not exist "%CFGDIR%" mkdir "%CFGDIR%"
if not exist "%CFG%" (
  if exist "%~dp0.env.example" (
    copy "%~dp0.env.example" "%CFG%" >nul
  ) else (
    echo Chua co file cau hinh. Hay mo StockVisionHOSE.exe mot lan truoc.
    pause
    exit /b 1
  )
)
notepad.exe "%CFG%"
