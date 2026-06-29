# Contributing to Historian

Contributions are welcome from anyone engaging with the project. Whether you
write code by hand or work with AI assistance, what matters is that there is a
person behind the submission — someone who has read the code, formed a
judgment about it, and is willing to discuss and iterate on the result.

## What this means in practice

Most of Historian's code was written with AI assistance, and that is fine. An
AI-assisted contribution from someone who understands the change and can defend
it is exactly as welcome as a hand-written one.

What is **not** welcome are automated submissions generated without human
review — for example, a bot scanning issues and opening pull requests with no
one reading the code or taking responsibility for the result. These will be
closed. Open source depends on people showing up, not pipelines emitting
output.

If you are not sure whether your workflow fits, open an issue or draft PR and
ask.

## Getting started

See [AGENTS.md](AGENTS.md) for the local workflow, design principles, testing,
and provider protocols.

To set up a development environment:

```bash
git clone https://github.com/randileeharper/historian.git
cd historian
uv sync
uv run historian config init
```

Verify the environment:

```bash
uv run historian doctor --live
```

## Before opening a pull request

- Create a dedicated branch for your change.
- Run the test suite: `uv run pytest -q`
- Run the compile check: `uv run python -m compileall historian tests`
- Keep unrelated local files out of commits (especially scratch directories
  like `tmp/`).
- In the PR description, include a concise summary and the exact test commands
  you ran.

If your change addresses an open issue, mention `Closes #NNN` in the commit or
PR body so the issue is linked and closed on merge.

## Review expectations

Be prepared to discuss the "why" behind a change, not just the "what." A PR
that passes tests but cannot be explained by its author may be asked for
clarification. This applies equally to hand-written and AI-assisted work — the
bar is understanding, not origin.
