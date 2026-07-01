from __future__ import annotations

import asyncio

import httpx
from a2a.helpers import new_text_part
from a2a.types import Message, Role, SendMessageRequest
from a2a.utils.constants import PROTOCOL_VERSION_1_0, VERSION_HEADER
from google.protobuf.json_format import MessageToDict

from historian.http import create_http_app

from conftest import event
from test_query import _answer, _search_action


async def _request(app, method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def test_public_health_and_card_declare_bearer(context) -> None:
    app = create_http_app(context)
    health = asyncio.run(_request(app, "GET", "/healthz"))
    card = asyncio.run(_request(app, "GET", "/.well-known/agent-card"))
    assert health.status_code == 200
    assert card.status_code == 200
    assert card.json()["securitySchemes"]["historian_bearer"]["httpAuthSecurityScheme"]["scheme"] == "bearer"


def test_event_api_requires_auth_and_ingests(context, vesper_token) -> None:
    app = create_http_app(context)
    denied = asyncio.run(_request(app, "POST", "/v1/events", json=event()))
    accepted = asyncio.run(
        _request(
            app,
            "POST",
            "/v1/events",
            headers={"Authorization": f"Bearer {vesper_token}"},
            json=event(),
        )
    )
    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["event"]["event_id"] == "event-1"


def test_get_event_list_uses_literal_filters(context, vesper_token) -> None:
    principal = context.store.authenticate(vesper_token)
    context.service.ingest(principal, event())
    app = create_http_app(context)
    response = asyncio.run(
        _request(
            app,
            "GET",
            "/v1/events?app=vesper&phrase=Morning%20Song&limit=5",
            headers={"Authorization": f"Bearer {vesper_token}"},
        )
    )
    assert response.status_code == 200
    assert [item["event_id"] for item in response.json()["events"]] == ["event-1"]


def test_a2a_query_is_authenticated_and_returns_answer(context, resolver, vesper_token) -> None:
    principal = context.store.authenticate(vesper_token)
    context.service.ingest(principal, event())
    resolver.plans.append(_search_action())
    resolver.answers.append(_answer())
    app = create_http_app(context)
    message = Message(
        role=Role.ROLE_USER,
        message_id="question-1",
        parts=[new_text_part("What did Vesper do this morning?", media_type="text/plain")],
    )
    envelope = {
        "jsonrpc": "2.0",
        "id": "request-1",
        "method": "SendMessage",
        "params": MessageToDict(
            SendMessageRequest(message=message),
            preserving_proto_field_name=False,
        ),
    }
    response = asyncio.run(
        _request(
            app,
            "POST",
            "/a2a",
            headers={
                "Authorization": f"Bearer {vesper_token}",
                VERSION_HEADER: PROTOCOL_VERSION_1_0,
            },
            json=envelope,
        )
    )
    assert response.status_code == 200
    task = response.json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    data = task["artifacts"][0]["parts"][0]["data"]
    assert data["answer"] == "Vesper started Morning Song."
    assert "cited_event_ids" not in data
    assert "events" not in data


def test_batch_endpoint_ingests_valid_batch(context, vesper_token) -> None:
    """POST /v1/events:batch accepts a valid batch and returns results with duplicate flags."""
    app = create_http_app(context)
    batch = {
        "events": [
            event(event_id="batch-1"),
            event(event_id="batch-2", track="Evening Song"),
        ]
    }
    response = asyncio.run(
        _request(
            app,
            "POST",
            "/v1/events:batch",
            headers={"Authorization": f"Bearer {vesper_token}"},
            json=batch,
        )
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert len(body["events"]) == 2
    assert [e["event"]["event_id"] for e in body["events"]] == ["batch-1", "batch-2"]
    assert all("duplicate" in e for e in body["events"])


def test_batch_endpoint_rejects_missing_events_array(context, vesper_token) -> None:
    """POST /v1/events:batch rejects a body without an events array with 422."""
    app = create_http_app(context)
    response = asyncio.run(
        _request(
            app,
            "POST",
            "/v1/events:batch",
            headers={"Authorization": f"Bearer {vesper_token}"},
            json={"not_events": []},
        )
    )
    assert response.status_code == 422
    assert response.json()["status"] == "error"


def test_search_endpoint_filters_by_fields(context, vesper_token) -> None:
    """POST /v1/search accepts SearchSpec fields and returns matching events."""
    principal = context.store.authenticate(vesper_token)
    context.service.ingest(principal, event(event_id="search-1", track="Morning Song"))
    context.service.ingest(principal, event(event_id="search-2", track="Evening Song"))
    app = create_http_app(context)
    response = asyncio.run(
        _request(
            app,
            "POST",
            "/v1/search",
            headers={"Authorization": f"Bearer {vesper_token}"},
            json={"apps": ["vesper"], "exact_phrases": ["Morning Song"], "limit": 10},
        )
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert [e["event_id"] for e in body["events"]] == ["search-1"]


def test_search_endpoint_rejects_invalid_spec(context, vesper_token) -> None:
    """POST /v1/search rejects an invalid search spec with 422."""
    app = create_http_app(context)
    response = asyncio.run(
        _request(
            app,
            "POST",
            "/v1/search",
            headers={"Authorization": f"Bearer {vesper_token}"},
            json={"bogus_field": "invalid"},
        )
    )
    assert response.status_code == 422
    assert response.json()["status"] == "error"
