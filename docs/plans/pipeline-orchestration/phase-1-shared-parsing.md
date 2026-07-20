# Phase 1: Shared Parsing Helper

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing

---

## Goal

Extract the markdown-code-fence-stripping logic that `briefing/summarize.py`
already has into `scout/shared/parsing.py`, so Phase 2's scraper/scorer
runners can reuse it instead of duplicating it a second and third time.
Done when `strip_code_fence` has its own test coverage and
`briefing/summarize.py` uses it with all existing briefing tests still
green.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** No.
- **Contains a one-way door (schema, public API shape, new dependency)?** No.

---

## Tasks

### Task 1: Add `scout/shared/parsing.py`

- **Files:** `scout/shared/parsing.py`, `tests/test_shared_parsing.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_shared_parsing.py`:

    ```python
    from __future__ import annotations

    from scout.shared.parsing import strip_code_fence


    def test_strip_code_fence_returns_plain_text_unchanged():
        assert strip_code_fence('{"a": 1}') == '{"a": 1}'


    def test_strip_code_fence_strips_json_fence():
        raw = '```json\n{"a": 1}\n```'
        assert strip_code_fence(raw) == '{"a": 1}'


    def test_strip_code_fence_strips_bare_fence():
        raw = '```\n{"a": 1}\n```'
        assert strip_code_fence(raw) == '{"a": 1}'


    def test_strip_code_fence_strips_surrounding_whitespace():
        assert strip_code_fence('  \n{"a": 1}\n  ') == '{"a": 1}'
    ```

  - [ ] Verify it fails (`pytest tests/test_shared_parsing.py -v`)
    Expected: `ModuleNotFoundError: No module named 'scout.shared.parsing'`
  - [ ] Implement `scout/shared/parsing.py`:

    ```python
    from __future__ import annotations

    import re

    _CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


    def strip_code_fence(raw_text: str) -> str:
        stripped = raw_text.strip()
        match = _CODE_FENCE_RE.match(stripped)
        return match.group(1).strip() if match else stripped
    ```

  - [ ] Verify it passes (`pytest tests/test_shared_parsing.py -v`)
    Expected: 4 passed
  - [ ] Commit: `feat(shared): add strip_code_fence parsing helper`

### Task 2: Switch `briefing/summarize.py` to the shared helper

- **Files:** `scout/sub_agents/briefing/summarize.py`, `tests/test_briefing_summarize.py` (no changes — existing tests are the regression check)
- **Gate:** none
- **Steps:**
  - [ ] Run the existing suite first to confirm the baseline is green:
    `pytest tests/test_briefing_summarize.py -v`
    Expected: all tests pass
  - [ ] Edit `scout/sub_agents/briefing/summarize.py`: remove the local
    `_CODE_FENCE_RE` pattern and `_strip_code_fence` function; add
    `from scout.shared.parsing import strip_code_fence`; change
    `parse_briefing_prose` to call `strip_code_fence(raw_text)` instead of
    `_strip_code_fence(raw_text)`.
  - [ ] Verify it still passes (`pytest tests/test_briefing_summarize.py -v`)
    Expected: same tests, all pass, no behavior change
  - [ ] Commit: `refactor(briefing): reuse shared strip_code_fence helper`

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_shared_parsing.py tests/test_briefing_summarize.py -v`
- [ ] No other module still defines its own copy of the code-fence regex: `grep -rn "CODE_FENCE_RE" scout/` should show only `scout/shared/parsing.py`

## Rollback

Revert both commits; `briefing/summarize.py` returns to its inline helper. No data or schema involved.

---

## Notes / Learnings

<Filled in during execution — anything that should inform later phases.>
