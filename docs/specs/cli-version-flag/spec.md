# Spec: CLI --version Flag

> **Status:** Approved
> **Created:** 2026-07-17 · **Approved:** 2026-07-17
> **Implementation plan:** [plan.md](../../plans/cli-version-flag/plan.md) *(created after approval)*

---

## Problem

This spec exists to validate that the plan-standards skill is correctly
wired into this repo and into the global CLAUDE.md: that spec/plan/phase
documents land under `docs/plans/<feature-slug>/` using the plan-standards
templates instead of the superpowers default location and format. The
feature itself — a `--version` flag — is a deliberately trivial,
throwaway vehicle for that test; it has no product motivation.

## Success Criteria

- `docs/plans/cli-version-flag/spec.md` and `plan.md` exist, following the
  plan-standards templates verbatim.
- Running `python -m scout.cli --version` prints the package version and
  exits 0.
- A test verifies the printed output matches `scout.__version__`.

---

## Requirements

### Must have

- `scout/__init__.py` defines `__version__ = "0.1.0"` as the single
  source of truth for the version string.
- `scout/cli.py` defines a `main()` function that parses `--version` via
  `argparse` and prints `scout.__version__`.
- `scout/__main__.py` allows invocation as `python -m scout.cli`.
- One test exercises the `--version` flag and asserts the output.

### Should have

- (none — scope is intentionally minimal)

### Won't have

- Any other CLI flags or subcommands — out of scope for this test; the
  CLI module exists solely to host `--version`.
- A CLI framework dependency (e.g. `click`) — stdlib `argparse` is
  sufficient for one flag.

---

## Proposed Approach

Add a minimal `scout/cli.py` module with a `main()` entry point built on
`argparse`. The single `--version` argument, when passed, prints the
value of `scout.__version__` (a new constant added to the currently-empty
`scout/__init__.py`) and exits. A thin `scout/__main__.py` shim
(`from scout.cli import main; main()`) makes the module runnable via
`python -m scout.cli`. No other stages or modules are touched.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Use `click` for the CLI | Adds a new dependency for a one-flag CLI; project has no existing CLI framework precedent to justify it. |
| Do nothing (skip the test) | Wouldn't verify the plan-standards wiring produces documents in the right location/format. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| (none) | — | — |

---

## Amendments *(only after approval — never silently edit approved content)*

- (none yet)
