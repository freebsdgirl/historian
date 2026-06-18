from __future__ import annotations

import json
from pathlib import Path

import pytest

from historian.app import build_app
from historian.manifests import parse_manifest
from historian.resolver import FakeQueryResolver


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "database_path": str(tmp_path / "historian.db"),
                "resolver_backend": "fake",
                "public_base_url": "http://testserver",
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def resolver() -> FakeQueryResolver:
    return FakeQueryResolver()


@pytest.fixture
def context(config_path: Path, resolver: FakeQueryResolver):
    return build_app(str(config_path), resolver=resolver)


@pytest.fixture
def vesper_manifest():
    return parse_manifest(
        {
            "app_id": "vesper",
            "description": "Music agent.",
            "default_scopes": ["events:write", "events:read", "query:nlp"],
            "schemas": [
                {
                    "event_type": "music.playback.started",
                    "version": 1,
                    "record_family": "event",
                    "description": "Playback started.",
                    "searchable_fields": ["request", "track", "artist", "secret"],
                    "redacted_fields": ["secret"],
                    "json_schema": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "properties": {
                            "request": {"type": "string"},
                            "track": {"type": "string"},
                            "artist": {"type": "string"},
                            "secret": {"type": "string"},
                        },
                        "required": ["request", "track", "artist", "secret"],
                        "additionalProperties": False,
                    },
                }
            ],
        }
    )


@pytest.fixture
def vesper_token(context, vesper_manifest) -> str:
    return context.store.install_app(vesper_manifest)


def event(
    event_id: str = "event-1",
    *,
    occurred_at: str = "2026-06-17T08:00:00-07:00",
    track: str = "Morning Song",
) -> dict:
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": "app://vesper/playback",
        "type": "music.playback.started",
        "time": occurred_at,
        "schemaversion": 1,
        "correlationid": "morning-session",
        "data": {
            "request": "play upbeat morning music",
            "track": track,
            "artist": "Test Artist",
            "secret": "do-not-store",
        },
    }

