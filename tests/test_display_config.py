from fastapi.testclient import TestClient

from backend import display_config as config
from backend.main import app


def test_offline_mode_never_exposes_browser_or_server_key(monkeypatch):
    monkeypatch.setenv("NEIGHBORHOOD_IGNORE_ENV", "1")
    monkeypatch.setenv("BAIDU_BROWSER_AK", "b" * 32)
    monkeypatch.setenv("BAIDU_MAP_AK", "s" * 32)
    monkeypatch.setattr(
        config, "dotenv_values", lambda _: (_ for _ in ()).throw(AssertionError("offline must not read env"))
    )
    assert config.display_config() == {"configured": False, "reason": "offline", "provider": "baidu-gl"}


def test_public_map_config_only_returns_separate_browser_key(monkeypatch):
    monkeypatch.delenv("NEIGHBORHOOD_IGNORE_ENV", raising=False)
    monkeypatch.setenv("BAIDU_BROWSER_AK", "b" * 32)
    monkeypatch.setenv("BAIDU_MAP_AK", "s" * 32)
    monkeypatch.setattr(config, "dotenv_values", lambda _: {})
    response = TestClient(app).get("/api/map/display-config")
    assert response.json()["browser_ak"] == "b" * 32
    assert "s" * 32 not in response.text
    assert response.headers["cache-control"] == "no-store"
    monkeypatch.setenv("BAIDU_BROWSER_AK", "s" * 32)
    assert config.display_config()["reason"] == "key_type_conflict"
    assert "browser_ak" not in config.display_config()


def test_browser_key_can_be_configured_in_env_file_without_server_fallback(monkeypatch):
    monkeypatch.delenv("NEIGHBORHOOD_IGNORE_ENV", raising=False)
    monkeypatch.delenv("BAIDU_BROWSER_AK", raising=False)
    monkeypatch.setenv("BAIDU_MAP_AK", "s" * 32)
    monkeypatch.setattr(config, "dotenv_values", lambda _: {"BAIDU_BROWSER_AK": "c" * 32})
    assert config.display_config()["browser_ak"] == "c" * 32
    monkeypatch.setattr(config, "dotenv_values", lambda _: {})
    assert not config.display_config()["configured"]
