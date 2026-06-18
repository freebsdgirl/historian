from __future__ import annotations

import json

import httpx

from historian.config import Settings
from historian.debug import QueryTranscript
from historian.resolver import OpenAICompatibleQueryResolver


def test_resolver_uses_json_schema_and_reasoning_toggle(tmp_path) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "answer",
                                    "search": None,
                                    "event_ids": [],
                                    "status": "insufficient_evidence",
                                    "answer": "No records.",
                                    "cited_event_ids": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    settings = Settings(
        resolver_model="test-model",
        resolver_include_reasoning=False,
        debug_enabled=True,
        resolver_debug_log_path=str(tmp_path / "resolver.log"),
        debug_log_path=str(tmp_path / "debug.log"),
    )
    transcript = QueryTranscript(settings)
    transcript.start(query_id="query-1", caller_app_id="test", question="What happened?")
    resolver = OpenAICompatibleQueryResolver(
        settings, transcript, transport=httpx.MockTransport(handler)
    )
    action = resolver.next_action(
        question="What happened?",
        current_time="2026-06-17T12:00:00Z",
        catalog=[],
        history=[],
        query_id="query-1",
        step=1,
    )
    resolver.next_action(
        question="What happened?",
        current_time="2026-06-17T12:00:01Z",
        catalog=[],
        history=[{"action": "search_result", "count": 0}],
        query_id="query-1",
        step=2,
    )
    assert action["status"] == "insufficient_evidence"
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["think"] is False
    assert captured["reasoning_effort"] == "none"
    assert captured["reasoning"] == {"effort": "none"}
    log = (tmp_path / "resolver.log").read_text(encoding="utf-8")
    assert "SYSTEM PROMPT" in log
    assert "USER MESSAGE" in log
    assert "What happened?" in log
    assert "RESPONSE" in log
    assert '"status": "insufficient_evidence"' in log
    assert "=== MODEL CALL 1 ===" in log
    assert "=== MODEL CALL 2 ===" in log


def test_resolver_transcript_captures_http_error_response(tmp_path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="model exploded")

    settings = Settings(
        resolver_model="test-model",
        debug_enabled=True,
        resolver_debug_log_path=str(tmp_path / "resolver.log"),
        debug_log_path=str(tmp_path / "debug.log"),
    )
    transcript = QueryTranscript(settings)
    transcript.start(query_id="query-error", caller_app_id="test", question="Break?")
    resolver = OpenAICompatibleQueryResolver(
        settings, transcript, transport=httpx.MockTransport(handler)
    )
    try:
        resolver.next_action(
            question="Break?",
            current_time="2026-06-17T12:00:00Z",
            catalog=[],
            history=[],
            query_id="query-error",
            step=1,
        )
    except Exception:
        pass
    log = (tmp_path / "resolver.log").read_text(encoding="utf-8")
    assert "http_status: 500" in log
    assert "model exploded" in log
    assert "ERROR" in log
