from __future__ import annotations

import json

import httpx

from historian.config import Settings
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
        resolver_debug_log_path=str(tmp_path / "resolver.log"),
    )
    resolver = OpenAICompatibleQueryResolver(settings, transport=httpx.MockTransport(handler))
    action = resolver.next_action(
        question="What happened?",
        current_time="2026-06-17T12:00:00Z",
        catalog=[],
        history=[],
    )
    assert action["status"] == "insufficient_evidence"
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["think"] is False
    assert captured["reasoning_effort"] == "none"
    assert captured["reasoning"] == {"effort": "none"}

