from __future__ import annotations

from conftest import event


def _search_action() -> dict:
    return {
        "action": "search",
        "search": {
            "record_families": ["event"],
            "apps": ["vesper"],
            "event_types": ["music.playback.started"],
            "occurred_after": "2026-06-17T00:00:00-07:00",
            "occurred_before": "2026-06-17T12:00:00-07:00",
            "required_terms": ["playback"],
            "exact_phrases": ["Morning Song"],
            "field_predicates": {},
            "regex_patterns": [],
            "order": "desc",
            "limit": 10,
        },
        "event_ids": [],
        "status": None,
        "answer": None,
        "cited_event_ids": [],
    }


def _answer(event_ids: list[str]) -> dict:
    return {
        "action": "answer",
        "search": None,
        "event_ids": [],
        "status": "ok",
        "answer": "Vesper started Morning Song.",
        "cited_event_ids": event_ids,
    }


def test_iterative_query_searches_and_cites(context, resolver, vesper_token) -> None:
    principal = context.store.authenticate(vesper_token)
    context.service.ingest(principal, event())
    resolver.actions.extend([_search_action(), _answer(["event-1"])])
    result = context.service.query(principal, "What did Vesper do this morning?")
    assert result.status == "ok"
    assert result.cited_event_ids == ["event-1"]
    assert result.events[0].event_id == "event-1"
    assert len(resolver.calls) == 2
    query_event = context.store.get_event(result.query_id)
    assert query_event is not None
    assert query_event.event_type == "historian.query.completed"
    assert query_event.data["question"] == "What did Vesper do this morning?"


def test_invalid_citation_gets_one_repair(context, resolver, vesper_token) -> None:
    principal = context.store.authenticate(vesper_token)
    context.service.ingest(principal, event())
    resolver.actions.extend([_search_action(), _answer(["invented"]), _answer(["event-1"])])
    result = context.service.query(principal, "What happened?")
    assert result.status == "ok"
    assert len(resolver.calls) == 3
    assert resolver.calls[-1]["history"][-1]["action"] == "citation_error"


def test_no_evidence_is_explicit(context, resolver, vesper_token) -> None:
    principal = context.store.authenticate(vesper_token)
    resolver.actions.append(
        {
            "action": "answer",
            "search": None,
            "event_ids": [],
            "status": "insufficient_evidence",
            "answer": "No stored record establishes that Vesper was running.",
            "cited_event_ids": [],
        }
    )
    result = context.service.query(principal, "Is Vesper running?")
    assert result.status == "insufficient_evidence"

