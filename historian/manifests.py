"""Manifest parsing and built-in schema loading."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .errors import ValidationError
from .models import AppManifest, SchemaDefinition


VALID_SCOPES = {"events:write", "events:read", "query:nlp"}
VALID_RECORD_FAMILIES = {
    "event",
    "transcript",
    "summary",
    "user_fact",
    "app_preference",
    "error",
    "status",
    "internal",
}


def load_manifest(path: Path) -> AppManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Could not read manifest {path}: {exc}") from exc
    return parse_manifest(payload)


def load_builtin_manifest() -> AppManifest:
    payload = json.loads(files("historian").joinpath("builtin_manifest.json").read_text(encoding="utf-8"))
    return parse_manifest(payload)


def parse_manifest(payload: Any) -> AppManifest:
    if not isinstance(payload, dict):
        raise ValidationError("Manifest must be a JSON object.")
    allowed = {"app_id", "description", "default_scopes", "schemas"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValidationError(f"Unknown manifest fields: {', '.join(unknown)}")
    app_id = _identifier(payload.get("app_id"), "app_id")
    description = _nonempty(payload.get("description"), "description")
    scopes = payload.get("default_scopes", [])
    if not isinstance(scopes, list) or any(scope not in VALID_SCOPES for scope in scopes):
        raise ValidationError(f"default_scopes must contain only: {', '.join(sorted(VALID_SCOPES))}")
    raw_schemas = payload.get("schemas")
    if not isinstance(raw_schemas, list) or not raw_schemas:
        raise ValidationError("Manifest schemas must be a non-empty array.")

    schemas: list[SchemaDefinition] = []
    seen: set[tuple[str, int]] = set()
    for raw in raw_schemas:
        schema = _parse_schema(raw)
        key = (schema.event_type, schema.version)
        if key in seen:
            raise ValidationError(f"Duplicate schema {schema.event_type} v{schema.version}.")
        seen.add(key)
        schemas.append(schema)
    return AppManifest(app_id=app_id, description=description, default_scopes=list(dict.fromkeys(scopes)), schemas=schemas)


def _parse_schema(payload: Any) -> SchemaDefinition:
    if not isinstance(payload, dict):
        raise ValidationError("Each schema must be an object.")
    allowed = {
        "event_type",
        "version",
        "record_family",
        "description",
        "json_schema",
        "searchable_fields",
        "redacted_fields",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValidationError(f"Unknown schema fields: {', '.join(unknown)}")
    event_type = _event_type(payload.get("event_type"))
    version = payload.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValidationError(f"Schema {event_type} version must be a positive integer.")
    family = payload.get("record_family")
    if family not in VALID_RECORD_FAMILIES:
        raise ValidationError(f"Schema {event_type} has invalid record_family.")
    description = _nonempty(payload.get("description"), f"{event_type}.description")
    json_schema = payload.get("json_schema")
    if not isinstance(json_schema, dict):
        raise ValidationError(f"Schema {event_type} json_schema must be an object.")
    try:
        Draft202012Validator.check_schema(json_schema)
    except Exception as exc:  # jsonschema exposes several schema-error subclasses.
        raise ValidationError(f"Schema {event_type} is not valid JSON Schema: {exc}") from exc
    searchable = _field_paths(payload.get("searchable_fields", []), "searchable_fields")
    redacted = _field_paths(payload.get("redacted_fields", []), "redacted_fields")
    return SchemaDefinition(event_type, version, family, description, json_schema, searchable, redacted)


def _identifier(value: Any, name: str) -> str:
    text = _nonempty(value, name)
    if not all(character.isalnum() or character in "._-" for character in text):
        raise ValidationError(f"{name} may contain only letters, digits, '.', '_', and '-'.")
    return text


def _event_type(value: Any) -> str:
    text = _identifier(value, "event_type")
    if "." not in text:
        raise ValidationError("event_type must be namespaced, for example music.playback.started.")
    return text


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _field_paths(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError(f"{name} must be an array of non-empty strings.")
    return list(dict.fromkeys(item.strip() for item in value))

