from pathlib import Path
import yaml

from app.db import normalize_database_url
from app.main import _split_sql_statements

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_managed_url_is_normalized_for_psycopg3():
    assert normalize_database_url("postgres://u:p@db:5432/x") == "postgresql+psycopg://u:p@db:5432/x"
    assert normalize_database_url("postgresql://u:p@db:5432/x") == "postgresql+psycopg://u:p@db:5432/x"
    assert normalize_database_url("sqlite:///./test.db") == "sqlite:///./test.db"


def test_sql_split_does_not_split_semicolons_inside_literal_or_comments():
    script = "-- comment ; not a separator\nSELECT 'a;b'; SELECT \"x;y\"; /* nested /* ; */ comment */ SELECT 3;"
    out = _split_sql_statements(script)
    assert len(out) == 3
    assert "'a;b'" in out[0]
    assert '"x;y"' in out[1]
    assert out[2].endswith("SELECT 3")


def test_project_sql_bootstrap_files_are_splittable_and_nonempty():
    sql_dir = ROOT / "backend" / "sql"
    for path in sorted(sql_dir.glob("*.sql")):
        statements = _split_sql_statements(path.read_text(encoding="utf-8"))
        assert statements
        assert all(s.strip() for s in statements)
    assert len(_split_sql_statements((sql_dir / "001_init.sql").read_text(encoding="utf-8"))) >= 30


def test_render_blueprint_uses_paid_production_resources_and_secrets_are_blank():
    cfg = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    service = next(x for x in cfg["services"] if x["name"] == "stockvision-hose")
    db = next(x for x in cfg["databases"] if x["name"] == "stockvision-db")
    assert service["healthCheckPath"] == "/api/v1/health"
    assert next(e for e in service["envVars"] if e["key"] == "DEMO_MODE")["value"] == "false"
    assert next(e for e in service["envVars"] if e["key"] == "MARKET_DATA_PROVIDER")["value"] == "public"
    assert next(e for e in service["envVars"] if e["key"] == "PUBLIC_DATA_AUTO_SYNC_ON_STARTUP")["value"] == "true"
    assert next(e for e in service["envVars"] if e["key"] == "FIREANT_API_TOKEN")["value"] == ""
    assert next(e for e in service["envVars"] if e["key"] == "FIREANT_LICENSE_CONFIRMED")["value"] == "false"
    assert service["plan"] == "starter"
    assert service["autoDeployTrigger"] == "checksPass"
    assert db["plan"] == "basic-256mb"
    assert db["ipAllowList"] == []
    assert cfg["previews"]["generation"] == "off"
    assert not any(x.get("plan") == "free" for x in cfg["services"])
    assert not any(x.get("plan") == "free" for x in cfg["databases"])


def test_pwa_assets_have_root_paths_and_do_not_cache_api():
    static = ROOT / "backend" / "app" / "static"
    for name in ("index.html", "manifest.webmanifest", "sw.js", "apple-touch-icon.png", "icon-192.png", "icon-512.png"):
        assert (static / name).is_file(), name
    manifest = (static / "manifest.webmanifest").read_text(encoding="utf-8")
    sw = (static / "sw.js").read_text(encoding="utf-8")
    html = (static / "index.html").read_text(encoding="utf-8")
    assert '"start_url": "/"' in manifest
    assert "url.pathname.startsWith('/api/')" in sw
    assert "location.origin" in html
    assert "connectBackend(false)" in html


def test_render_private_password_is_requested_and_session_secret_generated():
    cfg = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    service = cfg["services"][0]
    env = {x["key"]: x for x in service["envVars"]}
    assert env["APP_ACCESS_PASSWORD"].get("sync") is False
    assert env["APP_SESSION_SECRET"].get("generateValue") is True


def test_authenticated_cloud_api_gate_and_cookie_session():
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app

    original = settings.app_access_password
    object.__setattr__(settings, "app_access_password", "test-passphrase-01")
    try:
        with TestClient(app) as client:
            status = client.get("/api/v1/session/status")
            assert status.status_code == 200
            assert status.json() == {"access_required": True, "authenticated": False}
            assert client.get("/api/v1/market/overview").status_code == 401
            wrong = client.post("/api/v1/session/login", json={"password": "bad"})
            assert wrong.status_code == 401
            good = client.post("/api/v1/session/login", json={"password": "test-passphrase-01"})
            assert good.status_code == 200 and good.json()["authenticated"] is True
            assert client.get("/api/v1/market/overview").status_code == 200
            client.post("/api/v1/session/logout")
            assert client.get("/api/v1/market/overview").status_code == 401
    finally:
        object.__setattr__(settings, "app_access_password", original)


def test_same_origin_iphone_pwa_routes_are_served():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/manifest.webmanifest").headers["content-type"].startswith("application/manifest+json")
        assert client.get("/sw.js").headers["service-worker-allowed"] == "/"
        for path in ("/apple-touch-icon.png", "/icon-192.png", "/icon-512.png", "/icon.svg"):
            assert client.get(path).status_code == 200, path
        assert client.get("/api/v1/session/status").status_code == 200


def test_login_endpoint_throttles_repeated_failed_attempts():
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app, _LOGIN_ATTEMPTS

    original = settings.app_access_password
    object.__setattr__(settings, "app_access_password", "test-passphrase-01")
    _LOGIN_ATTEMPTS.clear()
    try:
        with TestClient(app) as client:
            for _ in range(10):
                assert client.post("/api/v1/session/login", json={"password": "wrong"}).status_code == 401
            limited = client.post("/api/v1/session/login", json={"password": "test-passphrase-01"})
            assert limited.status_code == 429
    finally:
        _LOGIN_ATTEMPTS.clear()
        object.__setattr__(settings, "app_access_password", original)


def test_preview_blueprint_is_explicitly_non_production():
    cfg = yaml.safe_load((ROOT / "render.preview.yaml").read_text(encoding="utf-8"))
    service = cfg["services"][0]
    db = cfg["databases"][0]
    assert service["plan"] == "free"
    assert db["plan"] == "free"
    assert next(e for e in service["envVars"] if e["key"] == "DEMO_MODE")["value"] == "true"
    assert next(e for e in service["envVars"] if e["key"] == "PUBLIC_DATA_AUTO_SYNC_ON_STARTUP")["value"] == "false"
