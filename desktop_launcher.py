from __future__ import annotations

"""Windows desktop shell for StockVision HOSE (local-only bind, no Docker/WSL)."""
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from dotenv import load_dotenv

FROZEN = bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))
# PyInstaller unpacks bundled resources to _MEIPASS; source runs use the project folder.
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).resolve()
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else ROOT
os.chdir(APP_DIR)

# Keep settings, logs, and the local database outside the executable bundle.
# This also works when the EXE is installed under Program Files (read-only to users).
local_appdata = Path(os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
DATA_DIR = local_appdata / "StockVisionHOSE"
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "logs").mkdir(exist_ok=True)

# In a frozen EXE, keep secrets/configuration in LocalAppData, never inside _MEIPASS.
# In source mode, preserve the existing project-local .env workflow.
CONFIG_PATH = (DATA_DIR / ".env") if FROZEN else (APP_DIR / ".env")
if not CONFIG_PATH.exists():
    example_path = ROOT / ".env.example"
    if example_path.is_file():
        try:
            CONFIG_PATH.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
load_dotenv(CONFIG_PATH, override=False)

# pythonw has no console; retain a small local log for troubleshooting.
if sys.stdout is None or sys.stderr is None:
    log_stream = open(DATA_DIR / "logs" / "desktop.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = log_stream
    if sys.stderr is None:
        sys.stderr = log_stream

# Desktop app must only bind to localhost; never expose its unauthenticated local API to LAN.
os.environ["APP_HOST"] = "127.0.0.1"
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("APP_SESSION_SECRET", "stockvision-local-desktop-session-only")
os.environ.setdefault("AUTO_CREATE_TABLES", "true")
os.environ.setdefault("MARKET_DATA_PROVIDER", "public")
os.environ.setdefault("PUBLIC_DATA_AUTO_SYNC_ON_STARTUP", "true")
os.environ.setdefault("PUBLIC_DATA_SYNC_INTERVAL_MINUTES", "60")
os.environ.setdefault("PUBLIC_DATA_LOOKBACK_DAYS", "730")
os.environ.setdefault("PUBLIC_DATA_CACHE_TTL_SECONDS", "900")
os.environ.setdefault("PUBLIC_DATA_SYMBOLS", "FPT,VCB,HPG,SSI,MWG,TCB,VIC,VHM")
os.environ.setdefault("PUBLIC_DATA_INDEX_SYMBOLS", "VNINDEX,VN30")
os.environ.setdefault("VN_MARKET_DATA_DB", str(DATA_DIR / "vn_market_data.db"))
os.environ.setdefault("FIREANT_AUTO_SYNC_ON_STARTUP", "true")
os.environ.setdefault("FIREANT_SYMBOLS", "FPT,VCB,HPG,SSI,MWG,TCB,VIC,VHM")
os.environ.setdefault("FIREANT_COUNT_BACK", "250")
os.environ.setdefault("FIREANT_TIMEOUT_SECONDS", "12")
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("APP_ACCESS_PASSWORD", "")

# Use a durable local SQLite database unless the user explicitly enters a non-SQLite DB URL.
configured_db = os.getenv("DATABASE_URL", "").strip()
if not configured_db or configured_db.startswith("sqlite:///./") or configured_db.startswith("sqlite:///data/"):
    db_path = (DATA_DIR / "stockvision_local.db").as_posix()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"


def _fireant_env_ready() -> bool:
    """Safe preflight; requires explicit provider authorization and the provider's contract."""
    confirmed = os.getenv("FIREANT_LICENSE_CONFIRMED", "false").strip().lower() in {"1", "true", "yes", "on"}
    token = bool(os.getenv("FIREANT_API_TOKEN", "").strip())
    base = urlparse(os.getenv("FIREANT_BASE_URL", "https://api.fireant.vn").strip())
    path = os.getenv("FIREANT_BARS_PATH", "").strip()
    try:
        query = json.loads(os.getenv("FIREANT_BARS_QUERY_JSON", "{}"))
        field_map = json.loads(os.getenv("FIREANT_BAR_FIELD_MAP_JSON", "{}"))
    except (ValueError, TypeError):
        return False
    required = {"date", "open", "high", "low", "close", "volume"}
    safe_path = bool(path.startswith("/") and not path.startswith("//") and ".." not in path.split("/") and "?" not in path and "#" not in path)
    base_ok = base.scheme == "https" and bool(base.netloc) and not base.username and not base.password
    return bool(confirmed and token and base_ok and safe_path and isinstance(query, dict) and isinstance(field_map, dict) and required.issubset(field_map))


# Never label the interface live unless the selected provider is configured/installed.
selected_provider = os.getenv("MARKET_DATA_PROVIDER", "public").strip().lower()
if selected_provider == "fireant":
    os.environ["DEMO_MODE"] = "false" if _fireant_env_ready() else "true"
elif selected_provider == "tcbs":
    os.environ["DEMO_MODE"] = "false" if os.getenv("TCBS_API_TOKEN", "").strip() else "true"
elif selected_provider == "public":
    try:
        import importlib.util as _importlib_util
        public_ready = _importlib_util.find_spec("vn_market_data") is not None
    except (ImportError, ValueError):
        public_ready = False
    os.environ["DEMO_MODE"] = "false" if public_ready else "true"
else:
    os.environ["DEMO_MODE"] = "true"


def _find_port(preferred: int = 8765) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


def _wait_for_server(url: str, timeout: float = 40) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.25)
    return False


def main() -> int:
    try:
        import uvicorn
        import webview
    except ImportError as exc:
        print(f"Thiếu thư viện {exc.name}. Hãy chạy lại trình đóng gói hoặc xem logs/desktop.log.")
        return 2

    port = _find_port()
    os.environ["APP_PORT"] = str(port)
    base_url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config("backend.app.main:app", host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="StockVision-LocalAPI", daemon=True)
    thread.start()

    if not _wait_for_server(base_url + "/api/v1/health"):
        print("StockVision backend không khởi động được. Xem logs/desktop.log và thử lại.")
        server.should_exit = True
        thread.join(timeout=5)
        return 3

    try:
        window = webview.create_window(
            "StockVision HOSE",
            base_url,
            width=1440,
            height=930,
            min_size=(960, 680),
            resizable=True,
            text_select=True,
            confirm_close=True,
        )
        webview.start(gui="edgechromium", debug=False)
    except Exception as exc:  # desktop runtime/WebView2 failures should be actionable, not crash silently
        print(f"Không mở được cửa sổ desktop ({type(exc).__name__}).")
        print("Hãy cài Microsoft Edge WebView2 Runtime rồi chạy lại. URL cục bộ:", base_url)
        try:
            import webbrowser
            webbrowser.open(base_url)
        except Exception:
            pass
        # Do not block or raise EOFError in a windowed/frozen build without a console.
        if not FROZEN and sys.stdin is not None:
            try:
                input("Nhấn Enter để đóng StockVision…")
            except EOFError:
                pass
    finally:
        server.should_exit = True
        thread.join(timeout=8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
