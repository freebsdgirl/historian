# Historian Status And Roadmap

This document tracks what is implemented, what still needs operational validation, and what remains future work.

## Current State

Historian v1 is implemented as a Python 3.12 service with:

- FastAPI HTTP ingestion and raw-read APIs.
- A2A 1.0 natural-language queries through the official `a2a-sdk`.
- SQLite storage with WAL, foreign keys, indexed fields, and non-destructive migrations.
- Opaque bearer tokens, application identity, token scopes, rotation, and revocation.
- Immutable JSON Schema Draft 2020-12 application manifests.
- Idempotent single-event ingestion and atomic batch ingestion.
- Distinct provenance for literal user messages, assistant messages, and runtime/sidecar events.
- Structured record families for events, transcripts, summaries, user facts, application preferences, errors, statuses, and internal records.
- OpenAI-compatible local-model calls using strict JSON-schema output.
- An iterative query loop over timestamps, application IDs, event types, record families, exact fields, literal terms, exact phrases, and bounded regex.
- Citation validation: answers may cite only exact event IDs found during the query.
- Private self-logging of Historian queries without model reasoning.
- CLI administration, querying, raw inspection, and event emission.
- A synchronous Python client with bounded retries.

There is intentionally no vector search, embedding generation, semantic index, or semantic-search fallback.

The automated suite currently covers configuration, migrations, authentication, schema installation, ingestion, redaction, idempotency, atomic batches, transcript provenance, literal search, regex bounds, iterative queries, citation repair, A2A transport, HTTP transport, CLI behavior, and resolver wire format.

## Required To Operate Historian

These steps are needed before Historian is a continuously running, useful service:

1. Create a dedicated virtual environment and install the package:

   ```console
   python3.12 -m venv .venv
   .venv/bin/pip install -e '.[dev]'
   ```

2. Create `config.json` from `config.example.json`.

3. Confirm the live local-model configuration:

   - `resolver_base_url`, normally `http://localhost:11434/v1`
   - `resolver_model`, currently expected to be `gemma4:latest`
   - `resolver_api_key`, if the endpoint requires one
   - reasoning and raw-output logging settings

4. Run `.venv/bin/historian doctor --live` and verify the model endpoint responds.

5. Start Historian and verify:

   - `GET /healthz`
   - both Agent Card paths
   - authenticated ingestion
   - authenticated raw reads
   - an authenticated A2A question using a real local model

6. Exercise the real model against representative records. The search loop and structured output are implemented, but prompt behavior has only been tested with fake and mock resolvers. Tune the prompt or normalization if Gemma emits poor literal terms, invalid dates, excessive regex, or premature answers.

7. Install application manifests and retain the one-time tokens in each application's secret configuration.

8. Integrate real event producers. Until Vesper, Magpie, Luke, or another app emits events, Historian has no useful history to query.

9. Run Historian persistently. A user-level systemd unit is the expected Linux deployment shape, with:

   - a fixed config path
   - restart-on-failure
   - explicit working directory
   - environment or credential-file handling for model secrets
   - logs available through `journalctl`

10. Add backup and restore instructions for the SQLite database before it contains important history.

## Validation Still Needed

- A real listening-server smoke test outside the Codex sandbox. The sandbox rejected localhost port binding, although the complete HTTP/A2A stack passed through in-process ASGI tests.
- A real Ollama `/chat/completions` query using `gemma4:latest`.
- Installation from a clean virtual environment, including the required `regex` package. Tests used an existing sibling environment where `regex` was absent, so the standard-library fallback ran; installed Historian should exercise the configured regex execution-timeout path.
- Long-running concurrency behavior under simultaneous ingestion and queries.
- Database growth measurements with realistic Magpie and Vesper event volumes.
- Recovery behavior after abrupt termination during SQLite writes.
- Token provisioning and rotation in the real application configuration workflow.

## Integration Order

Recommended order:

1. Vesper, because its events are bounded and easy to inspect: playback, sessions, preferences, RPC failures, and worker status.
2. Magpie, including research runs, route decisions, fetch/source outcomes, synthesis completion, cache use, and failures.
3. Luke transcript ingestion, preserving literal user, assistant, and internal/runtime provenance.
4. Luke and sidecar A2A query access with a token containing `query:nlp`.
5. Other channel workers such as Bluesky, mail, reminders, and iMessage.

Each producer integration should follow `HISTORIAN_INTEGRATION.md`.

## Deferred Work

These are not required for initial operation:

- Automatic conversation summarization.
- Automatic durable-user-fact extraction.
- Automatic application-preference extraction.
- Summary/fact supersession and correction workflows.
- Client-side durable disk spooling.
- Retention, archival, compaction, and deletion policies.
- PostgreSQL storage.
- MCP.
- Multi-user or multi-tenant authorization.
- TLS termination and remote-network deployment.
- Push notifications or streaming A2A results.
- A web administration interface.
- Metrics and dashboards beyond Historian's own query/event history.

Vector or embedding retrieval is not deferred work. It is outside the design.

