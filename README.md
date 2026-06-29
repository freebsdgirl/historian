# Historian

[![CI](https://github.com/randileeharper/historian/actions/workflows/ci.yml/badge.svg)](https://github.com/randileeharper/historian/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/tag/randileeharper/historian?label=version)](https://github.com/randileeharper/historian/tags)

Historian is a local event, transcript, and operational-history service for small agent applications. Apps emit registered structured events over HTTP. Agents ask evidence-bounded natural-language questions over A2A.

Historian preserves raw provenance underneath every derived view. Literal user messages, assistant messages, and private runtime/sidecar events are distinct record types. A runtime may render an internal event as a user-shaped `/chat/completions` message, but Historian never rewrites it as something the user literally said.

## Setup

```console
uv sync
uv run historian config init
uv run historian app install examples/vesper.historian.json
uv run historian serve
```

`historian config init` writes the packaged template to `~/.config/historian/config.json`
(use `--path` for a custom location, `--force` to overwrite, or `--print` to output the
template to stdout without writing a file). `historian config path` prints the config
file Historian loaded from (or `none` if using built-in defaults).

Configuration discovery order is `--config`, `HISTORIAN_CONFIG_PATH`, `./config.json`, then `${XDG_CONFIG_HOME:-~/.config}/historian/config.json`. Environment variables use the `HISTORIAN_` prefix.

## Basic Usage

`app install` prints a token once. Put it in the application's secret configuration:

```console
export HISTORIAN_TOKEN=hist_...
uv run historian emit examples/vesper-playback-event.json
uv run historian ask "What did Vesper do this morning?"
```

Create a private all-access credential for local CLI administration once:

```console
uv run historian token init-cli
```

This stores an owner-only token at `~/.config/historian/cli-token` by default. Commands such as `historian events list` and `historian ask ...` use it automatically. Explicit `--token` and `HISTORIAN_TOKEN` values still take precedence.

## Documentation

- [Architecture](docs/architecture.md) — design principles, storage and retrieval model, NLP query pipeline, and record families.
- [API Reference](docs/api-reference.md) — HTTP and A2A endpoints, event ingestion, manifest installation, and the Python client.
- [Debugging](docs/debugging.md) — debug mode configuration, operational and resolver logs, known limitations, and diagnostic commands.
- [Integration Guide](docs/integration.md) — full producer integration contract: event envelope, manifest schema, failure policy, recommended events per application, and acceptance checklist.
- [`ROADMAP.md`](ROADMAP.md) — what is implemented, what still requires live operational validation, the recommended integration order, and deferred work.
