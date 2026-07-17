# Plan: CLI --version Flag

> **Status:** Not started
> **Created:** 2026-07-17 · **Last updated:** 2026-07-17

---

## Overview

Add a minimal `scout/cli.py` module exposing a `--version` flag, backed by
a new `scout.__version__` constant. This is a throwaway feature whose real
purpose is to validate that the plan-standards skill produces spec/plan/
phase documents under `docs/plans/<slug>/` correctly. "Done" means
`python -m scout.cli --version` prints the version and a test confirms it.

## Acceptance Criteria

- [ ] `python -m scout.cli --version` prints `scout.__version__` and exits 0.
- [ ] A test in `tests/` exercises this and passes.
- [ ] No other CLI behavior is added.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| None identified | — | Feature is fully self-contained (one new constant, one new module, one shim); no dependency on unfinished stages (Tracker, Scorer, etc.) |

---

## Blast Radius

- **Code that will change:** `scout/__init__.py`, `scout/cli.py` (new), `scout/__main__.py` (new), `tests/test_cli.py` (new)
- **Existing behaviour that could break:** None — `scout/__init__.py` is currently empty, and no other module imports from it.
- **Off-limits:** Do not modify anything outside the files above without flagging it first.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | CLI version flag | [phase-1-cli-version-flag.md](phase-1-cli-version-flag.md) | Not started |

---

## Testing Strategy

- **Unit:** `tests/test_cli.py` covers `--version` output via per-task TDD in phase 1.
- **Integration:** N/A — single-phase, self-contained feature.
- **Manual:** Run `python -m scout.cli --version` in a terminal and confirm the printed version.

---

## Key Decisions & Constraints

- Use stdlib `argparse`, not `click` — avoids a new dependency for one flag (per spec's Alternatives Considered).
- `scout.__version__` is the single source of truth for the version string; nothing else hardcodes it.
- ⚠️ **One-way doors:** None — this is new, isolated code with no consumers yet.

## Out of Scope

- Any CLI flag other than `--version`.
- Wiring the CLI into `docker-compose.yaml`, `Dockerfile`, or any entry-point script.

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] Feature verified manually in a running environment
- [ ] Docs / README updated where behaviour changed
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
