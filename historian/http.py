"""Authenticated FastAPI and A2A transports."""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import asdict
from typing import Any

from a2a.helpers import new_data_part, new_task, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
    create_rest_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    Message,
    Role,
    SecurityRequirement,
    SecurityScheme,
    StringList,
    TaskState,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH, PROTOCOL_VERSION_1_0, TransportProtocol
from a2a.utils.errors import InternalError, InvalidParamsError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict

from .app import AppContext
from .errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    HistorianError,
    ValidationError,
)
from .models import AuthPrincipal, SearchSpec, to_jsonable


_request_principal: contextvars.ContextVar[AuthPrincipal | None] = contextvars.ContextVar(
    "historian_request_principal", default=None
)
_PUBLIC_PATHS = {"/healthz", "/.well-known/agent-card", "/.well-known/agent-card.json"}


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("Authorization: Bearer token is required.")
    return token.strip()


def build_agent_card(base_url: str) -> AgentCard:
    bearer = SecurityScheme(
        http_auth_security_scheme=HTTPAuthSecurityScheme(
            description="Opaque token created by the Historian CLI.",
            scheme="bearer",
            bearer_format="historian-token",
        )
    )
    requirement = SecurityRequirement(schemes={"historian_bearer": StringList(list=[])})
    return AgentCard(
        name="Historian",
        description="Query registered application events, transcripts, summaries, facts, preferences, errors, and status history.",
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url.rstrip('/')}/a2a",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_1_0,
            ),
            AgentInterface(
                url=base_url.rstrip("/"),
                protocol_binding=TransportProtocol.HTTP_JSON.value,
                protocol_version=PROTOCOL_VERSION_1_0,
            ),
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False, extended_agent_card=False),
        security_schemes={"historian_bearer": bearer},
        security_requirements=[requirement],
        default_input_modes=["text/plain"],
        default_output_modes=["application/json", "text/plain"],
        skills=[
            AgentSkill(
                id="historian-query",
                name="Natural-language history query",
                description="Ask literal, evidence-bounded questions about registered application and conversation history.",
                tags=["history", "events", "logs", "memory", "observability"],
                examples=["What did Vesper do this morning?", "What was Magpie's last error?"],
                input_modes=["text/plain"],
                output_modes=["application/json", "text/plain"],
                security_requirements=[requirement],
            )
        ],
    )


class HistorianAgentExecutor(AgentExecutor):
    def __init__(self, context: AppContext):
        self.context = context

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        principal = _request_principal.get()
        if principal is None:
            raise InternalError("Authenticated principal was not propagated to A2A execution.")
        if context.message is None:
            raise InvalidParamsError("SendMessageRequest.message is required.")
        if not context.task_id or not context.context_id:
            raise InternalError("Request context did not include task identifiers.")
        question = context.get_user_input().strip()
        if not question:
            raise InvalidParamsError("A non-empty text question is required.")
        task = new_task(
            task_id=context.task_id,
            context_id=context.context_id,
            state=TaskState.TASK_STATE_SUBMITTED,
            history=[context.message],
        )
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=context.task_id, context_id=context.context_id)
        await updater.start_work()
        result = self.context.service.query(principal, question)
        payload = to_jsonable(result)
        message = Message(
            role=Role.ROLE_AGENT,
            message_id=str(uuid.uuid4()),
            task_id=context.task_id,
            context_id=context.context_id,
            parts=[
                new_text_part(result.answer, media_type="text/plain"),
                new_data_part(payload, media_type="application/json"),
            ],
        )
        await updater.add_artifact(
            parts=[new_data_part(payload, media_type="application/json")],
            name="historian-query-result",
        )
        if result.status == "error":
            await updater.failed(message)
        else:
            await updater.complete(message)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if not context.task_id or not context.context_id:
            raise InternalError("Cancellation request did not include task identifiers.")
        updater = TaskUpdater(event_queue=event_queue, task_id=context.task_id, context_id=context.context_id)
        await updater.update_status(TaskState.TASK_STATE_CANCELED)


def create_http_app(context: AppContext) -> FastAPI:
    card = build_agent_card(context.settings.public_base_url)
    app = FastAPI(title="Historian", version="0.1.0")

    @app.middleware("http")
    async def authenticate_request(request: Request, call_next):
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)
        try:
            principal = context.store.authenticate(_bearer_token(request))
        except AuthenticationError as exc:
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=401)
        token = _request_principal.set(principal)
        request.state.principal = principal
        try:
            return await call_next(request)
        finally:
            _request_principal.reset(token)

    @app.exception_handler(AuthorizationError)
    async def authorization_error(_: Request, exc: AuthorizationError):
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=403)

    @app.exception_handler(ValidationError)
    async def validation_error(_: Request, exc: ValidationError):
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=422)

    @app.exception_handler(ConflictError)
    async def conflict_error(_: Request, exc: ConflictError):
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=409)

    @app.exception_handler(HistorianError)
    async def historian_error(_: Request, exc: HistorianError):
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/.well-known/agent-card")
    @app.get("/.well-known/agent-card.json")
    async def agent_card_alias() -> JSONResponse:
        return JSONResponse(MessageToDict(card, preserving_proto_field_name=False))

    @app.post("/v1/events")
    async def ingest_event(request: Request) -> dict[str, Any]:
        event, duplicate = context.service.ingest(request.state.principal, await request.json())
        return {"status": "ok", "duplicate": duplicate, "event": to_jsonable(event)}

    @app.post("/v1/events:batch")
    async def ingest_batch(request: Request) -> dict[str, Any]:
        body = await request.json()
        events = body.get("events") if isinstance(body, dict) else None
        if not isinstance(events, list):
            raise ValidationError("Batch body must contain an events array.")
        results = context.service.ingest_batch(request.state.principal, events)
        return {
            "status": "ok",
            "events": [
                {"duplicate": duplicate, "event": to_jsonable(event)} for event, duplicate in results
            ],
        }

    @app.post("/v1/search")
    async def search_events(request: Request) -> dict[str, Any]:
        body = await request.json()
        try:
            spec = SearchSpec(**body)
        except TypeError as exc:
            raise ValidationError(f"Invalid search fields: {exc}") from exc
        events = context.service.raw_search(request.state.principal, spec)
        return {"status": "ok", "events": [to_jsonable(event) for event in events]}

    @app.get("/v1/events")
    async def list_events(request: Request) -> dict[str, Any]:
        query = request.query_params
        try:
            limit = int(query.get("limit", "50"))
        except ValueError as exc:
            raise ValidationError("limit must be an integer.") from exc
        spec = SearchSpec(
            apps=query.getlist("app"),
            event_types=query.getlist("type"),
            record_families=query.getlist("family"),
            occurred_after=query.get("after"),
            occurred_before=query.get("before"),
            required_terms=query.getlist("term"),
            exact_phrases=query.getlist("phrase"),
            regex_patterns=query.getlist("regex"),
            order=query.get("order", "desc"),
            limit=limit,
        )
        events = context.service.raw_search(request.state.principal, spec)
        return {"status": "ok", "events": [to_jsonable(event) for event in events]}

    @app.get("/v1/events/{event_id}")
    async def get_event(event_id: str, request: Request) -> dict[str, Any]:
        event = context.service.get_event(request.state.principal, event_id)
        if event is None:
            return {"status": "not_found", "event": None}
        return {"status": "ok", "event": to_jsonable(event)}

    @app.post("/v1/query")
    async def structured_query(request: Request) -> dict[str, Any]:
        body = await request.json()
        question = str(body.get("question", "")) if isinstance(body, dict) else ""
        return to_jsonable(context.service.query(request.state.principal, question))

    handler = DefaultRequestHandlerV2(
        agent_executor=HistorianAgentExecutor(context),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card, card_url=AGENT_CARD_WELL_KNOWN_PATH),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a"),
        rest_routes=create_rest_routes(handler),
    )
    return app
