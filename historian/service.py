"""Historian domain services."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from typing import Any

from .config import Settings
from .errors import AuthorizationError, QueryError, ValidationError
from .models import AuthPrincipal, EventEnvelope, QueryResult, SearchSpec, StoredEvent, utc_now
from .resolver import QueryResolver
from .storage import SQLiteHistorianStore


class HistorianService:
    def __init__(self, store: SQLiteHistorianStore, resolver: QueryResolver, settings: Settings):
        self.store = store
        self.resolver = resolver
        self.settings = settings

    @staticmethod
    def require_scope(principal: AuthPrincipal, scope: str) -> None:
        if scope not in principal.scopes:
            raise AuthorizationError(f"Token for {principal.app_id} lacks scope {scope}.")

    def ingest(self, principal: AuthPrincipal, payload: dict[str, Any]) -> tuple[StoredEvent, bool]:
        self.require_scope(principal, "events:write")
        event = self.parse_event(payload)
        encoded_size = len(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
        if encoded_size > self.settings.max_event_bytes:
            raise ValidationError(f"Event exceeds max_event_bytes ({self.settings.max_event_bytes}).")
        return self.store.ingest(principal, event)

    def ingest_batch(
        self, principal: AuthPrincipal, payloads: list[dict[str, Any]]
    ) -> list[tuple[StoredEvent, bool]]:
        self.require_scope(principal, "events:write")
        if not payloads or len(payloads) > self.settings.max_batch_events:
            raise ValidationError(f"Batch must contain 1-{self.settings.max_batch_events} events.")
        events: list[EventEnvelope] = []
        for payload in payloads:
            encoded_size = len(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
            if encoded_size > self.settings.max_event_bytes:
                raise ValidationError(f"Event exceeds max_event_bytes ({self.settings.max_event_bytes}).")
            events.append(self.parse_event(payload))
        return self.store.ingest_batch(principal, events)

    def raw_search(self, principal: AuthPrincipal, spec: SearchSpec) -> list[StoredEvent]:
        self.require_scope(principal, "events:read")
        normalized = self._normalize_search(spec)
        return self.store.search(
            normalized,
            max_regex_candidates=self.settings.max_regex_candidates,
            regex_timeout_seconds=self.settings.regex_timeout_seconds,
        )

    def get_event(self, principal: AuthPrincipal, event_id: str) -> StoredEvent | None:
        self.require_scope(principal, "events:read")
        return self.store.get_event(event_id)

    def query(self, principal: AuthPrincipal, question: str) -> QueryResult:
        self.require_scope(principal, "query:nlp")
        question = question.strip()
        if not question:
            raise ValidationError("Question cannot be empty.")
        query_id = str(uuid.uuid4())
        started = time.perf_counter()
        history: list[dict[str, Any]] = []
        searches: list[dict[str, Any]] = []
        evidence: dict[str, StoredEvent] = {}
        invalid_citation_repairs = 0
        result: QueryResult | None = None

        try:
            for _ in range(self.settings.max_query_steps):
                action = self.resolver.next_action(
                    question=question,
                    current_time=utc_now(),
                    catalog=self.store.search_catalog(),
                    history=history,
                )
                kind = str(action.get("action", "")).strip()
                if kind == "search":
                    raw_spec = action.get("search")
                    if not isinstance(raw_spec, dict):
                        raise QueryError("Resolver search action omitted search controls.")
                    spec = self._normalize_search(SearchSpec(**raw_spec))
                    matches = self.store.search(
                        spec,
                        max_regex_candidates=self.settings.max_regex_candidates,
                        regex_timeout_seconds=self.settings.regex_timeout_seconds,
                    )
                    for event in matches:
                        evidence[event.event_id] = event
                    summary = {
                        "action": "search_result",
                        "search": asdict(spec),
                        "count": len(matches),
                        "events": [self._compact_event(event) for event in matches],
                    }
                    searches.append({"search": asdict(spec), "count": len(matches)})
                    history.append(summary)
                    self._trim_history(history)
                    continue
                if kind == "fetch_events":
                    ids = [str(item) for item in action.get("event_ids", [])][
                        : self.settings.max_full_event_fetches
                    ]
                    fetched: list[StoredEvent] = []
                    for event_id in ids:
                        event = self.store.get_event(event_id)
                        if event and event_id in evidence:
                            fetched.append(event)
                    history.append(
                        {
                            "action": "fetch_result",
                            "events": [asdict(event) for event in fetched],
                        }
                    )
                    self._trim_history(history)
                    continue
                if kind == "answer":
                    status = action.get("status")
                    answer = str(action.get("answer") or "").strip()
                    citations = list(dict.fromkeys(str(item) for item in action.get("cited_event_ids", [])))
                    invalid = [event_id for event_id in citations if event_id not in evidence]
                    if invalid and invalid_citation_repairs < 1:
                        invalid_citation_repairs += 1
                        history.append(
                            {
                                "action": "citation_error",
                                "invalid_event_ids": invalid,
                                "allowed_event_ids": sorted(evidence),
                            }
                        )
                        continue
                    if invalid:
                        raise QueryError(f"Resolver cited events outside query evidence: {', '.join(invalid)}")
                    if status not in {"ok", "partial", "insufficient_evidence"}:
                        raise QueryError("Resolver answer status is invalid.")
                    if not answer:
                        raise QueryError("Resolver answer is empty.")
                    result = QueryResult(
                        status=status,
                        answer=answer,
                        query_id=query_id,
                        cited_event_ids=citations,
                        searches=searches,
                        events=[evidence[event_id] for event_id in citations],
                    )
                    break
                raise QueryError(f"Resolver returned unsupported action {kind!r}.")
            if result is None:
                result = QueryResult(
                    status="insufficient_evidence",
                    answer="Historian could not establish an answer from stored records within the search-step limit.",
                    query_id=query_id,
                    cited_event_ids=[],
                    searches=searches,
                    events=[],
                )
            return result
        except Exception as exc:
            result = QueryResult(
                status="error",
                answer="Historian could not complete the query.",
                query_id=query_id,
                cited_event_ids=[],
                searches=searches,
                events=[],
                message=str(exc),
            )
            return result
        finally:
            if result is not None:
                self._record_query(principal, question, result, started)

    def _record_query(
        self, principal: AuthPrincipal, question: str, result: QueryResult, started: float
    ) -> None:
        payload = {
            "specversion": "1.0",
            "id": result.query_id,
            "source": "app://historian/query",
            "type": "historian.query.completed",
            "time": utc_now(),
            "schemaversion": 1,
            "visibility": "private",
            "data": {
                "caller_app_id": principal.app_id,
                "question": question,
                "status": result.status,
                "searches": result.searches,
                "cited_event_ids": result.cited_event_ids,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "answer": result.answer,
            },
        }
        try:
            self.store.ingest_internal(self.parse_event(payload))
        except Exception:
            # Query logging must not erase an otherwise valid answer.
            return

    def _normalize_search(self, spec: SearchSpec) -> SearchSpec:
        spec.limit = max(1, min(int(spec.limit), self.settings.max_search_results))
        if spec.order not in {"asc", "desc"}:
            spec.order = "desc"
        spec.required_terms = self._literal_list(spec.required_terms, 12, 128)
        spec.exact_phrases = self._literal_list(spec.exact_phrases, 8, 256)
        spec.regex_patterns = self._literal_list(
            spec.regex_patterns, self.settings.max_regex_patterns, self.settings.max_regex_length
        )
        spec.apps = self._literal_list(spec.apps, 20, 128)
        spec.event_types = self._literal_list(spec.event_types, 20, 256)
        spec.record_families = self._literal_list(spec.record_families, 8, 64)
        if not any(
            (
                spec.record_families,
                spec.apps,
                spec.event_types,
                spec.occurred_after,
                spec.occurred_before,
                spec.required_terms,
                spec.exact_phrases,
                spec.field_predicates,
            )
        ) and spec.regex_patterns:
            raise ValidationError("Regex search requires at least one non-regex bounding constraint.")
        return spec

    @staticmethod
    def _literal_list(values: list[str], max_items: int, max_length: int) -> list[str]:
        result: list[str] = []
        for value in values[:max_items]:
            text = str(value).strip()
            if text and len(text) <= max_length and text not in result:
                result.append(text)
        return result

    def _trim_history(self, history: list[dict[str, Any]]) -> None:
        while len(json.dumps(history, ensure_ascii=True)) > self.settings.max_evidence_characters:
            if not history:
                break
            first = history[0]
            events = first.get("events")
            if isinstance(events, list) and len(events) > 1:
                events.pop()
            else:
                history.pop(0)

    @staticmethod
    def _compact_event(event: StoredEvent) -> dict[str, Any]:
        text = event.canonical_text
        return {
            "event_id": event.event_id,
            "app": event.producer_app_id,
            "type": event.event_type,
            "family": event.record_family,
            "occurred_at": event.occurred_at,
            "text": text[:2000],
        }

    @staticmethod
    def parse_event(payload: dict[str, Any]) -> EventEnvelope:
        if not isinstance(payload, dict):
            raise ValidationError("Event must be an object.")
        required = {"specversion", "id", "source", "type", "time", "schemaversion", "data"}
        missing = sorted(required - set(payload))
        if missing:
            raise ValidationError(f"Event is missing fields: {', '.join(missing)}")
        if payload["specversion"] != "1.0":
            raise ValidationError("Only CloudEvents specversion 1.0 is supported.")
        if not isinstance(payload["data"], dict):
            raise ValidationError("Event data must be an object.")
        visibility = str(payload.get("visibility", "private"))
        if visibility not in {"private", "shared"}:
            raise ValidationError("visibility must be private or shared.")
        return EventEnvelope(
            specversion="1.0",
            event_id=str(payload["id"]).strip(),
            source=str(payload["source"]).strip(),
            event_type=str(payload["type"]).strip(),
            occurred_at=str(payload["time"]).strip(),
            schema_version=int(payload["schemaversion"]),
            data=payload["data"],
            subject=str(payload["subject"]).strip() if payload.get("subject") is not None else None,
            correlation_id=str(payload["correlationid"]).strip() if payload.get("correlationid") else None,
            causation_id=str(payload["causationid"]).strip() if payload.get("causationid") else None,
            session_id=str(payload["sessionid"]).strip() if payload.get("sessionid") else None,
            visibility=visibility,
        )
