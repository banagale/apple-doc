# apple-doc - offline search of Apple's developer documentation

**File note:** `CLAUDE.md` is a symlink to this file (`AGENTS.md`). Always edit `AGENTS.md` directly.

## Project Overview

`apple-doc` is a single-command CLI that searches the copy of Apple's developer documentation
that macOS downloads for Xcode (a SQLite file under `/System/Library/AssetsV2/`). It keeps its
own small FTS5 keyword index in `~/Library/Caches/apple-doc/` and reads page text back from
Apple's database at query time. No network, no Xcode process, no sudo.

Design commitments that changes must keep:

- **Zero runtime dependencies.** Python 3.11+ standard library only (argparse, sqlite3, json).
  Do not add click, rich or anything else to `dependencies`.
- **Read-only on Apple's asset.** Open it with `mode=ro&immutable=1`; never write next to it.
- **Ships no Apple content.** Tests and fixtures use invented pages, never text copied from the
  real asset.
- **Small, ranked output.** Results are sized for an AI agent's context window: default 3 hits,
  60-line cap. Ranking changes need a test that shows the intended order.

## Layout

```
src/apple_doc/
  cli.py      argparse entry point, --doctor, JSON output, exit-code mapping
  index.py    locate the asset, build the FTS5 index, detect a stale index
  search.py   query terms, candidate query + re-ranking, --full page lookup
  render.py   markdown cleanup, availability string, excerpt selection
  errors.py   exit codes and AppleDocError
tests/        pytest; builds a fake asset DB in tmp_path
```

## CLI Structure

```bash
apple-doc QUERY... [-f FRAMEWORK] [-n N] [--lines N] [--any-platform] [--max-lines N] [--json]
apple-doc --full URI [--json]   # one page or section
apple-doc --build               # (re)build the keyword index
apple-doc --doctor              # check asset + index
```

Exit codes are part of the interface (documented in `--help` and the README):
0 ok, 1 no hits, 2 usage, 3 asset not found, 4 index missing/unreadable (stale for `--doctor`),
5 page not found. Keep them stable.

## Quick Commands

```bash
uv sync
uv run apple-doc --help
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv tool install -e .            # local install for manual use
```

## Testing

- Tests must pass on a machine without Apple's documentation asset. Point the tool at a fake
  asset with `APPLE_DOC_ASSET_GLOB` and at a temp index with `APPLE_DOC_INDEX` (see
  `tests/conftest.py`).
- Tests that need the real asset are marked `@pytest.mark.real_asset` and skip when it is absent.
- Run the CLI as a subprocess (`python -m apple_doc`) when the test is about exit codes or
  stdout/stderr.

## Fixture and Content Hygiene

Use role placeholders in docs, tests and fixtures: `/path/to/x`, `user@example.test`, invented
framework pages. No personal paths, machine names, internal hostnames or tracker IDs.

## Commit Guidelines

- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Keep commits atomic; no AI attribution lines.

## Git Workflow

Agents working in this repository commit directly to `main` and push. Never open or suggest a
pull request, even when a generic delivery workflow defaults to one. Releases are cut as an
annotated tag (`vX.Y.Z`) after bumping `version` in `pyproject.toml` and `src/apple_doc/__init__.py`.

## Working Files

Scratch files go to `/tmp/`, not the repo.
