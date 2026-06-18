from __future__ import annotations

import json

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

