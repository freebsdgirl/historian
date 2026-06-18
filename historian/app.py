"""Application assembly."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .manifests import load_builtin_manifest
from .resolver import FakeQueryResolver, OpenAICompatibleQueryResolver, QueryResolver
from .service import HistorianService
from .storage import SQLiteHistorianStore


@dataclass(slots=True)
class AppContext:
    settings: Settings
    store: SQLiteHistorianStore
    resolver: QueryResolver
    service: HistorianService


def build_app(config_path: str | None = None, *, resolver: QueryResolver | None = None) -> AppContext:
    settings = Settings.load(config_path)
    store = SQLiteHistorianStore(settings.expanded_database_path)
    store.initialize()
    store.ensure_manifest(load_builtin_manifest())
    if resolver is None:
        if settings.resolver_backend == "fake":
            resolver = FakeQueryResolver()
        else:
            resolver = OpenAICompatibleQueryResolver(settings)
    service = HistorianService(store, resolver, settings)
    return AppContext(settings, store, resolver, service)

