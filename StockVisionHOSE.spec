# PyInstaller spec for a single-file Windows desktop app.
# Build this spec on Windows (PyInstaller is not a cross-compiler).
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT = Path(SPECPATH).resolve()

webview_datas, webview_binaries, webview_hiddenimports = collect_all("webview")
backend_hiddenimports = collect_submodules("backend.app")
try:
    public_data_hiddenimports = collect_submodules("vn_market_data")
except Exception:
    public_data_hiddenimports = []  # optional dependency: demo/desktop build remains possible

uvicorn_hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

extra_datas = [
    (str(PROJECT / "backend" / "app" / "static"), "backend/app/static"),
    (str(PROJECT / "backend" / "sql"), "backend/sql"),
    (str(PROJECT / ".env.example"), "."),
]

a = Analysis(
    [str(PROJECT / "desktop_launcher.py")],
    pathex=[str(PROJECT)],
    binaries=webview_binaries,
    datas=extra_datas + webview_datas,
    hiddenimports=sorted(set(backend_hiddenimports + uvicorn_hiddenimports + webview_hiddenimports + public_data_hiddenimports + [
        "clr", "pythonnet", "clr_loader", "webview.platforms.edgechromium",
        "webview.platforms.winforms", "uvicorn.main"
    ])),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "gi",
        "cefpython3", "tkinter", "pytest", "tests"
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="StockVisionHOSE",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT / "stockvision.ico"),
)
