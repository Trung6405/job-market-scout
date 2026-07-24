# Phase 2: Model-call token cap & timeout

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing (independent of Phase 1)

---

## Goal

Give the model call a configurable output-token ceiling and request timeout
so batches truncate less often and one hung call can't stall the concurrent
stage. Confirmed by config tests (defaults + overrides) and an `llm` test
asserting both are forwarded to `litellm.acompletion`.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — it shapes the outbound model call. New values are ints with safe
  defaults; no new secret or input path.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No.

---

## Tasks

### Task 1: Add settings for token cap and timeout

- **Files:** `scout/config.py`, `tests/test_config.py`, `scout/.env.example`
- **Gate:** none
- **Steps:**
  - [x] Write failing test in `tests/test_config.py`:
    ```python
    def test_settings_uses_model_call_defaults_when_env_unset(monkeypatch):
        for var in ("MODEL_MAX_TOKENS", "MODEL_TIMEOUT_SECONDS"):
            monkeypatch.delenv(var, raising=False)
        settings = Settings()
        assert settings.model_max_tokens == 8000
        assert settings.model_timeout_seconds == 120

    def test_settings_reads_model_call_env_overrides(monkeypatch):
        monkeypatch.setenv("MODEL_MAX_TOKENS", "4096")
        monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "60")
        settings = Settings()
        assert settings.model_max_tokens == 4096
        assert settings.model_timeout_seconds == 60
    ```
  - [x] Verify it fails (`pytest tests/test_config.py -k model_call -v`) — expect FAIL (attributes missing).
  - [x] Add two fields to `Settings` (near `model_concurrency`):
    ```python
    # Output-token ceiling per model call. Headroom below deepseek-chat's
    # 8192 output cap so a batch response is less likely to truncate mid-JSON.
    model_max_tokens: int = field(
        default_factory=partial(_env_int, "MODEL_MAX_TOKENS", 8000)
    )
    # Per-request timeout (seconds). Bounds a hung provider call so it can't
    # stall the whole asyncio.gather fan-out of a stage.
    model_timeout_seconds: int = field(
        default_factory=partial(_env_int, "MODEL_TIMEOUT_SECONDS", 120)
    )
    ```
  - [x] Add both vars with their defaults to `scout/.env.example`.
  - [x] Verify tests pass (`pytest tests/test_config.py -v`).
  - [x] Commit: `feat(config): add MODEL_MAX_TOKENS and MODEL_TIMEOUT_SECONDS`

### Task 2: Forward token cap and timeout in complete_json

- **Files:** `scout/shared/llm.py`, `tests/test_shared_llm.py`
- **Gate:** none
- **Interfaces:**
  - Consumes: `settings.model_max_tokens: int`, `settings.model_timeout_seconds: int` (Task 1).
- **Steps:**
  - [x] Write failing test in `tests/test_shared_llm.py` (extends the
        existing kwarg-capture pattern):
    ```python
    async def test_complete_json_forwards_max_tokens_and_timeout(monkeypatch):
        seen: dict = {}

        async def _fake_acompletion(**kwargs):
            seen.update(kwargs)
            return _fake_response('{"value": 1}')

        monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)
        settings = Settings()
        await llm.complete_json("prompt", _Toy, settings)
        assert seen["max_tokens"] == settings.model_max_tokens
        assert seen["timeout"] == settings.model_timeout_seconds
    ```
  - [x] Verify it fails (`pytest tests/test_shared_llm.py::test_complete_json_forwards_max_tokens_and_timeout -v`) — expect FAIL (kwargs absent).
  - [x] In `complete_json`, pass to `litellm.acompletion`:
        `max_tokens=settings.model_max_tokens,` and
        `timeout=settings.model_timeout_seconds,`.
  - [x] Verify tests pass (`pytest tests/test_shared_llm.py -v`).
  - [x] Commit: `feat(llm): cap output tokens and set a request timeout`

---

## Verification

- [x] Phase tests pass: `pytest tests/test_config.py tests/test_shared_llm.py -v`

## Rollback

Revert the two commits; the call reverts to no explicit cap/timeout and the
settings disappear. No state involved.

---

## Notes / Learnings

Went exactly to plan. No adjustment needed to the settings shape or the
`complete_json` kwargs.
