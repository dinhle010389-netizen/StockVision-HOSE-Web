@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -c "import fastapi,uvicorn,sqlalchemy,httpx,webview; print('StockVision desktop dependencies: OK')"
) else (
  echo Chua cai dependency. Hay chay START_STOCKVISION.bat truoc.
)
pause
