"""Application assembly."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .debug import QueryTranscript, configure_logging, get_logger
from .manifests import load_builtin_manifest
from .resolver import FakeQueryResolver, OpenAICompatibleQueryResolver, QueryResolver
from .service import HistorianService
from .storage import SQLiteHistorianStore


_LOG = get_logger("app")


@dataclass(slots=True)
class AppContext:
    settings: Settings
    store: SQLiteHistorianStore
    resolver: QueryResolver
    service: HistorianService
    transcript: QueryTranscript


def build_app(
    config_path: str | None = None,
    *,
    resolver: QueryResolver | None = None,
    clear_operational_log: bool = False,
) -> AppContext:
    settings = Settings.load(config_path)
    configure_logging(settings, clear_operational_log=clear_operational_log)
    _LOG.info(
        "application_build_started clear_operational_log=%s config=%s",
        clear_operational_log,
        settings.sanitized(),
    )
    transcript = QueryTranscript(settings)
    store = SQLiteHistorianStore(settings.expanded_database_path)
    store.initialize()
    store.ensure_manifest(load_builtin_manifest())
    if resolver is None:
        if settings.resolver_backend == "fake":
            resolver = FakeQueryResolver()
        else:
            resolver = OpenAICompatibleQueryResolver(settings, transcript)
    service = HistorianService(store, resolver, settings, transcript)
    _LOG.info(
        "application_build_complete resolver_backend=%s database=%s",
        settings.resolver_backend,
        settings.expanded_database_path,
    )
    return AppContext(settings, store, resolver, service, transcript)
