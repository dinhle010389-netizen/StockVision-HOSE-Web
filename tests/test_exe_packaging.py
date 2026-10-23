from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

def test_pyinstaller_spec_is_valid_python():
    ast.parse((ROOT / "StockVisionHOSE.spec").read_text(encoding="utf-8"))

def test_build_script_outputs_expected_exe():
    text = (ROOT / "BUILD_WINDOWS_EXE.bat").read_text(encoding="utf-8")
    assert "StockVisionHOSE.spec" in text
    assert r"dist\StockVisionHOSE.exe" in text
    assert "pyinstaller==6.22.3" in text

def test_frozen_launcher_keeps_config_outside_temp_bundle():
    text = (ROOT / "desktop_launcher.py").read_text(encoding="utf-8")
    assert 'getattr(sys, "_MEIPASS"' in text
    assert "(DATA_DIR / \".env\") if FROZEN" in text
    assert "stockvision_local.db" in text

def test_all_required_bundle_assets_exist():
    for relative in (
        "backend/app/static/index.html",
        "backend/app/static/market_overview_desktop.html",
        "backend/sql/001_init.sql",
        "backend/sql/002_market_index_change_migration.sql",
        ".env.example",
        "stockvision.ico",
    ):
        assert (ROOT / relative).is_file(), relative

def test_icon_is_windows_ico():
    data = (ROOT / "stockvision.ico").read_bytes()
    assert data[:4] == b"\x00\x00\x01\x00"

def test_fireant_config_helper_uses_user_config_directory():
    text = (ROOT / "CONFIG_FIREANT_EXE.bat").read_text(encoding="utf-8")
    assert "%LOCALAPPDATA%\\StockVisionHOSE" in text and "%CFGDIR%\\.env" in text
    assert "notepad.exe" in text
