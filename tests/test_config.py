from __future__ import annotations

import json

import pytest

from historian.config import Settings
from historian.errors import ConfigError


def test_config_file_and_environment_override(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"http_port": 9000, "resolver_api_key": "secret"}), encoding="utf-8")
    monkeypatch.setenv("HISTORIAN_HTTP_PORT", "9001")
    settings = Settings.load(str(path))
    assert settings.http_port == 9001
    assert settings.sanitized()["has_resolver_api_key"] is True
    assert "resolver_api_key" not in settings.sanitized()


def test_unknown_config_field_is_rejected(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"surprise": True}), encoding="utf-8")
    with pytest.raises(ConfigError, match="Unknown config fields"):
        Settings.load(str(path))


def test_debug_paths_are_required_when_enabled(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"debug_enabled": True, "debug_log_path": ""}),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="debug_log_path"):
        Settings.load(str(path))
