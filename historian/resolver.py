"""Local-model query planning and evidence synthesis."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import httpx

from .config import Settings
from .errors import ResolverError


_DEBUG_LOG_LOCK = threading.Lock()


class QueryResolver(Protocol):
    def next_action(
        self,
        *,
        question: str,
        current_time: str,
        catalog: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]: ...


def reasoning_options(enabled: bool) -> dict[str, Any]:
    effort = "medium" if enabled else "none"
    return {"think": enabled, "reasoning_effort": effort, "reasoning": {"effort": effort}}


@dataclass(slots=True)
class OpenAICompatibleQueryResolver:
    settings: Settings
    transport: httpx.BaseTransport | None = None

    def next_action(
        self,
        *,
        question: str,
        current_time: str,
        catalog: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        system = (
            "You operate the Historian record search loop. Return exactly one JSON object. "
            "You may choose action=search, action=fetch_events, or action=answer. "
            "Historian performs parameterized SQL and bounded regex; you never write SQL. "
            "Search language is literal, not semantic. Choose terms and exact phrases that must actually occur in records. "
            "Do not use vibes-based paraphrases or broad descriptive phrases. "
            "Prefer timestamp, app, record-family, event-type, and exact searchable-field constraints before text. "
            "Use regex only when literal terms cannot express the necessary pattern. "
            "Search result entries are compact evidence and include exact event IDs. "
            "Fetch full events only when their payload detail is needed. "
            "An answer must cite only event IDs shown or fetched in history. "
            "If the records do not support an answer after reasonable searches, answer with status=insufficient_evidence. "
            "Never guess and never include hidden reasoning."
        )
        user = {
            "question": question,
            "current_time": current_time,
            "available_records": catalog,
            "search_history": history,
        }
        return self._ask_json(system, user)

    def _ask_json(self, system: str, user: dict[str, Any]) -> dict[str, Any]:
        action_schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "fetch_events", "answer"]},
                "search": {
                    "type": ["object", "null"],
                    "properties": {
                        "record_families": {"type": "array", "items": {"type": "string"}},
                        "apps": {"type": "array", "items": {"type": "string"}},
                        "event_types": {"type": "array", "items": {"type": "string"}},
                        "occurred_after": {"type": ["string", "null"]},
                        "occurred_before": {"type": ["string", "null"]},
                        "required_terms": {"type": "array", "items": {"type": "string"}},
                        "exact_phrases": {"type": "array", "items": {"type": "string"}},
                        "field_predicates": {"type": "object"},
                        "regex_patterns": {"type": "array", "items": {"type": "string"}},
                        "order": {"type": "string", "enum": ["asc", "desc"]},
                        "limit": {"type": "integer", "minimum": 1}
                    },
                    "additionalProperties": False,
                },
                "event_ids": {"type": "array", "items": {"type": "string"}},
                "status": {
                    "type": ["string", "null"],
                    "enum": ["ok", "partial", "insufficient_evidence", None],
                },
                "answer": {"type": ["string", "null"]},
                "cited_event_ids": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["action", "search", "event_ids", "status", "answer", "cited_event_ids"],
            "additionalProperties": False,
        }
        payload = {
            "model": self.settings.resolver_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=True)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "historian_query_action", "strict": True, "schema": action_schema},
            },
            **reasoning_options(self.settings.resolver_include_reasoning),
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.resolver_api_key:
            headers["Authorization"] = f"Bearer {self.settings.resolver_api_key}"
        started = perf_counter()
        try:
            with httpx.Client(
                timeout=self.settings.request_timeout_seconds,
                verify=self.settings.verify_tls,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self.settings.resolver_base_url.rstrip("/") + "/chat/completions",
                    json=payload,
                    headers=headers,
                )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            result = json.loads(content) if isinstance(content, str) else content
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._append_debug(system, user, None, round((perf_counter() - started) * 1000, 2), str(exc))
            raise ResolverError(f"Historian resolver failed: {exc}") from exc
        if not isinstance(result, dict):
            raise ResolverError("Historian resolver did not return an object.")
        self._append_debug(
            system,
            user,
            content if self.settings.resolver_include_raw_output else None,
            round((perf_counter() - started) * 1000, 2),
            None,
        )
        return result

    def _append_debug(
        self,
        system: str,
        user: dict[str, Any],
        raw_output: Any,
        elapsed_ms: float,
        error: str | None,
    ) -> None:
        path = Path(self.settings.resolver_debug_log_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "elapsed_ms": elapsed_ms,
            "system": system,
            "user": user,
            "raw_output": raw_output,
            "error": error,
        }
        with _DEBUG_LOG_LOCK, path.open("a", encoding="utf-8", errors="backslashreplace") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")


@dataclass(slots=True)
class FakeQueryResolver:
    actions: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def next_action(
        self,
        *,
        question: str,
        current_time: str,
        catalog: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.calls.append(
            {"question": question, "current_time": current_time, "catalog": catalog, "history": history}
        )
        if not self.actions:
            return {
                "action": "answer",
                "search": None,
                "event_ids": [],
                "status": "insufficient_evidence",
                "answer": "No configured fake query action.",
                "cited_event_ids": [],
            }
        return self.actions.pop(0)
