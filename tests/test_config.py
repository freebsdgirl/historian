from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

from historian.config import (
    Settings,
    default_config_path,
    read_config_template,
    write_default_config,
)
from historian.errors import ConfigError


def test_config_file_and_environment_override(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"http_port": 9000, "resolver_api_key": "secret"}), encoding="utf-8")
    monkeypatch.setenv("HISTORIAN_HTTP_PORT", "9001")
    settings = Settings.load(str(path))
    assert settings.http_port == 9001
    assert settings.sanitized()["has_resolver_api_key"] is True
    assert "resolver_api_key" not in settings.sanitized()
    assert settings.expanded_cli_token_path.name == "cli-token"


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


def test_resolver_retry_count_is_bounded(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"resolver_max_retries": 11}), encoding="utf-8")
    with pytest.raises(ConfigError, match="resolver_max_retries"):
        Settings.load(str(path))


def test_record_synthesis_limits_have_expected_defaults() -> None:
    settings = Settings()
    assert settings.max_records_per_model_call == 50
    assert settings.max_query_records == 1000


def _template_text() -> str:
    return files("historian").joinpath("config.example.json").read_text(encoding="utf-8")


def test_write_default_config_writes_template(tmp_path) -> None:
    target = tmp_path / "config.json"
    write_default_config(target)
    assert target.read_text(encoding="utf-8") == _template_text()


def test_write_default_config_refuses_overwrite(tmp_path) -> None:
    target = tmp_path / "config.json"
    target.write_text("existing", encoding="utf-8")
    with pytest.raises(ConfigError, match="--force"):
        write_default_config(target)
    assert target.read_text(encoding="utf-8") == "existing"


def test_write_default_config_force_overwrites(tmp_path) -> None:
    target = tmp_path / "config.json"
    target.write_text("existing", encoding="utf-8")
    write_default_config(target, force=True)
    assert target.read_text(encoding="utf-8") == _template_text()


def test_write_default_config_creates_parent_dirs(tmp_path) -> None:
    target = tmp_path / "nested" / "dir" / "config.json"
    write_default_config(target)
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == _template_text()


def test_default_config_path_respects_xdg_config_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_config_path() == tmp_path / "historian" / "config.json"

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert default_config_path() == Path("~/.config").expanduser() / "historian" / "config.json"


def test_read_config_template_returns_template_text() -> None:
    assert read_config_template() == _template_text()
