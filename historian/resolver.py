"""Local-model query planning and evidence synthesis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

import httpx

from .config import Settings
from .debug import QueryTranscript, get_logger
from .errors import ResolverError


_LOG = get_logger("resolver")


class QueryResolver(Protocol):
    def next_action(
        self,
        *,
        question: str,
        current_time: str,
        catalog: list[dict[str, Any]],
        history: list[dict[str, Any]],
        query_id: str,
        step: int,
    ) -> dict[str, Any]: ...


def reasoning_options(enabled: bool) -> dict[str, Any]:
    effort = "medium" if enabled else "none"
    return {"think": enabled, "reasoning_effort": effort, "reasoning": {"effort": effort}}


@dataclass(slots=True)
class OpenAICompatibleQueryResolver:
    settings: Settings
    transcript: QueryTranscript
    transport: httpx.BaseTransport | None = None

    def next_action(
        self,
        *,
        question: str,
        current_time: str,
        catalog: list[dict[str, Any]],
        history: list[dict[str, Any]],
        query_id: str,
        step: int,
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
        return self._ask_json(system, user, query_id=query_id, step=step)

    def _ask_json(
        self, system: str, user: dict[str, Any], *, query_id: str, step: int
    ) -> dict[str, Any]:
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
        endpoint = self.settings.resolver_base_url.rstrip("/") + "/chat/completions"
        user_message = json.dumps(user, ensure_ascii=True)
        http_status: int | None = None
        response_content: str | None = None
        reasoning_content: str | None = None
        try:
            with httpx.Client(
                timeout=self.settings.request_timeout_seconds,
                verify=self.settings.verify_tls,
                transport=self.transport,
            ) as client:
                response = client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                )
            http_status = response.status_code
            response_content = response.text
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            response_content = content if isinstance(content, str) else json.dumps(content, ensure_ascii=True)
            reasoning_content = self._extract_reasoning(body)
            result = json.loads(content) if isinstance(content, str) else content
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            elapsed_ms = round((perf_counter() - started) * 1000, 2)
            self.transcript.append_call(
                query_id=query_id,
                step=step,
                model=self.settings.resolver_model,
                endpoint=endpoint,
                system_prompt=system,
                user_message=user_message,
                elapsed_ms=elapsed_ms,
                http_status=http_status,
                response_content=response_content,
                reasoning_content=reasoning_content,
                error=f"{type(exc).__name__}: {exc}",
            )
            _LOG.exception(
                "query_id=%s step=%s model_call_failed elapsed_ms=%s http_status=%s",
                query_id,
                step,
                elapsed_ms,
                http_status,
            )
            raise ResolverError(f"Historian resolver failed: {exc}") from exc
        if not isinstance(result, dict):
            elapsed_ms = round((perf_counter() - started) * 1000, 2)
            error = "Historian resolver did not return an object."
            self.transcript.append_call(
                query_id=query_id,
                step=step,
                model=self.settings.resolver_model,
                endpoint=endpoint,
                system_prompt=system,
                user_message=user_message,
                elapsed_ms=elapsed_ms,
                http_status=http_status,
                response_content=response_content,
                reasoning_content=reasoning_content,
                error=error,
            )
            _LOG.error("query_id=%s step=%s model_response_not_object", query_id, step)
            raise ResolverError(error)
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        self.transcript.append_call(
            query_id=query_id,
            step=step,
            model=self.settings.resolver_model,
            endpoint=endpoint,
            system_prompt=system,
            user_message=user_message,
            elapsed_ms=elapsed_ms,
            http_status=http_status,
            response_content=response_content,
            reasoning_content=reasoning_content,
            error=None,
        )
        _LOG.debug(
            "query_id=%s step=%s model_call_complete elapsed_ms=%s http_status=%s response_chars=%s",
            query_id,
            step,
            elapsed_ms,
            http_status,
            len(response_content or ""),
        )
        return result

    def _extract_reasoning(self, body: dict[str, Any]) -> str | None:
        if not self.settings.resolver_include_reasoning:
            return None
        message = body.get("choices", [{}])[0].get("message", {})
        for key in ("reasoning", "reasoning_content", "thinking"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None


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
        query_id: str,
        step: int,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "question": question,
                "current_time": current_time,
                "catalog": catalog,
                "history": history,
                "query_id": query_id,
                "step": step,
            }
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
