from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path

from historian.app import build_app
from historian.cli import main


def test_app_install_and_doctor(config_path, tmp_path, capsys) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "app_id": "test-app",
                "description": "Test application.",
                "default_scopes": ["events:write"],
                "schemas": [
                    {
                        "event_type": "test.event.created",
                        "version": 1,
                        "record_family": "event",
                        "description": "Test event.",
                        "searchable_fields": ["message"],
                        "redacted_fields": [],
                        "json_schema": {
                            "$schema": "https://json-schema.org/draft/2020-12/schema",
                            "type": "object",
                            "properties": {"message": {"type": "string"}},
                            "required": ["message"],
                            "additionalProperties": False,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["--config", str(config_path), "app", "install", str(manifest)]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["token"].startswith("hist_")
    assert main(["--config", str(config_path), "doctor"]) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["status"] == "ok"
    assert doctor["apps"] == 2


def test_serve_passes_configured_log_level(config_path, monkeypatch) -> None:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["log_level"] = "WARNING"
    payload["debug_enabled"] = True
    payload["debug_log_path"] = str(config_path.parent / "serve-debug.log")
    payload["resolver_debug_log_path"] = str(config_path.parent / "serve-resolver.log")
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    (config_path.parent / "serve-debug.log").write_text("stale\n", encoding="utf-8")
    captured = {}

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    assert main(["--config", str(config_path), "serve"]) == 0
    assert captured["log_level"] == "warning"
    assert "stale" not in (config_path.parent / "serve-debug.log").read_text(encoding="utf-8")


def test_init_cli_token_becomes_default_credential(config_path, tmp_path, capsys) -> None:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["cli_token_path"] = str(tmp_path / "cli-token")
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    assert main(["--config", str(config_path), "token", "init-cli"]) == 0
    created = json.loads(capsys.readouterr().out)
    token_path = tmp_path / "cli-token"
    assert created["scopes"] == ["events:read", "events:write", "query:nlp"]
    assert token_path.is_file()
    assert os.stat(token_path).st_mode & 0o777 == 0o600

    context = build_app(str(config_path))
    principal = context.store.authenticate(token_path.read_text(encoding="utf-8").strip())
    assert principal.app_id == "historian"
    assert principal.scopes == frozenset({"events:read", "events:write", "query:nlp"})

    assert main(["--config", str(config_path), "events", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["status"] == "ok"


def _template_text() -> str:
    return files("historian").joinpath("config.example.json").read_text(encoding="utf-8")


def test_config_init_writes_default_config(tmp_path, capsys) -> None:
    target = tmp_path / "config.json"
    assert main(["config", "init", "--path", str(target)]) == 0
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == _template_text()
    assert "Wrote config" in capsys.readouterr().out


def test_config_init_refuses_overwrite(tmp_path, capsys) -> None:
    target = tmp_path / "config.json"
    target.write_text("existing", encoding="utf-8")
    assert main(["config", "init", "--path", str(target)]) == 2
    assert "--force" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "existing"


def test_config_init_force_overwrites(tmp_path) -> None:
    target = tmp_path / "config.json"
    target.write_text("existing", encoding="utf-8")
    assert main(["config", "init", "--path", str(target), "--force"]) == 0
    assert target.read_text(encoding="utf-8") == _template_text()


def test_config_init_print_outputs_template(capsys) -> None:
    assert main(["config", "init", "--print"]) == 0
    assert capsys.readouterr().out == _template_text()


def test_config_init_print_does_not_write_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["config", "init", "--print"]) == 0
    assert not (tmp_path / "config.json").exists()


def test_config_path_prints_loaded_path(tmp_path, capsys) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"resolver_backend": "fake", "database_path": str(tmp_path / "db.db")}),
        encoding="utf-8",
    )
    assert main(["--config", str(config_path), "config", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(config_path.resolve())


def test_config_path_reports_none_when_no_config(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("HISTORIAN_CONFIG_PATH", raising=False)
    assert main(["config", "path"]) == 0
    assert "none" in capsys.readouterr().out
