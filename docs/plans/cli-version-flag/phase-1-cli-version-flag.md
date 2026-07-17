# Phase 1: CLI version flag

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing

---

## Goal

Deliver a working `python -m scout.cli --version` command backed by a
`scout.__version__` constant, verified by an automated test.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** No.
- **Contains a one-way door (schema, public API shape, new dependency)?** No — stdlib only, no new dependency, no schema/API surface.

---

## Tasks

### Task 1: Add `scout.__version__` and the CLI module

- **Files:** `scout/__init__.py`, `scout/cli.py`, `scout/__main__.py`, `tests/test_cli.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_cli.py`:

    ```python
    import subprocess
    import sys

    from scout import __version__


    def test_version_flag_prints_version():
        result = subprocess.run(
            [sys.executable, "-m", "scout.cli", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == __version__
    ```

  - [ ] Verify it fails (`./.venv/Scripts/python.exe -m pytest tests/test_cli.py -v`)
    Expected: FAIL — `ModuleNotFoundError: No module named 'scout.cli'` (or `ImportError: cannot import name '__version__'`)
  - [ ] Implement `scout/__init__.py`:

    ```python
    __version__ = "0.1.0"
    ```

  - [ ] Implement `scout/cli.py`:

    ```python
    import argparse

    from scout import __version__


    def main() -> None:
        parser = argparse.ArgumentParser(prog="scout")
        parser.add_argument(
            "--version",
            action="version",
            version=__version__,
        )
        parser.parse_args()


    if __name__ == "__main__":
        main()
    ```

  - [ ] Implement `scout/__main__.py`:

    ```python
    from scout.cli import main

    main()
    ```

  - [ ] Verify it passes (`./.venv/Scripts/python.exe -m pytest tests/test_cli.py -v`)
    Expected: PASS
  - [ ] Commit:

    ```bash
    git add scout/__init__.py scout/cli.py scout/__main__.py tests/test_cli.py
    git commit -m "feat(cli): add --version flag"
    ```

---

## Verification

- [ ] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_cli.py -v`
- [ ] Manual check: run `./.venv/Scripts/python.exe -m scout.cli --version` in a terminal and confirm it prints `0.1.0` and exits 0.

## Rollback

Revert the commit from Task 1 (`git revert <sha>`) — the change is fully
isolated to three new files plus the previously-empty `scout/__init__.py`,
with no other code depending on them.

---

## Notes / Learnings

<Filled in during execution.>
