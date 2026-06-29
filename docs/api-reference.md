# API Reference

## HTTP and A2A Interfaces

- `POST /v1/events` and `POST /v1/events:batch`
- `POST /v1/search` and `GET /v1/events/{event_id}`
- A2A JSON-RPC at `/a2a` plus the SDK HTTP JSON routes
- Agent Cards at `/.well-known/agent-card.json` and `/.well-known/agent-card`
- `POST /v1/query` is a convenience adapter over the same query service for the CLI and non-A2A debugging

All routes except health and Agent Cards require bearer authentication.

## Event Ingestion

Applications send CloudEvents 1.0 JSON to `POST /v1/events` with `Authorization: Bearer hist_...`. `source` must equal or descend from `app://<authenticated-app-id>`. The tuple `(authenticated app, source, id)` is idempotent.

### Installing Application Manifests

An application ships a manifest containing its event schemas. The administrator installs it:

```console
uv run historian app install path/to/app.historian.json
```

During early development, if a producer changes an existing schema version and historical compatibility is not required, replace the installed definitions without rotating its token:

```console
uv run historian app sync-schemas path/to/app.historian.json
```

This intentionally bypasses schema immutability. Existing events are not migrated or revalidated, so production integrations should instead add a new schema version and update the producer.

For the full producer integration contract — event envelope, manifest schema, failure policy, recommended events per application, and acceptance checklist — see the [Integration Guide](integration.md).

## Python Client

The official Python client adds bounded retries:

```python
from historian.client import HistorianClient

client = HistorianClient("http://127.0.0.1:8760", token)
client.emit(event)
```

Failed delivery is explicit. V1 does not silently discard events or maintain a client-side disk spool.
