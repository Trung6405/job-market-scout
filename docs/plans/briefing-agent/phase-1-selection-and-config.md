# Phase 1: Selection & Config

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing

---

## Goal

Add the config and shared schema pieces Briefing needs (`briefing_max_matches`, Gmail settings, `BriefingTakeaway`/`BriefingProse`), then implement the deterministic Select step (`select_top_matches`) that turns `join_match_results`'s output into the day's capped, thresholded, sorted top matches. Done when `select_top_matches` is fully unit-tested and `Settings()` still constructs successfully everywhere else in the codebase without any new required argument.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** No — this phase only adds config fields and a pure selection function; Gmail credentials are read here as plain fields but not used or validated yet (Phase 3 does that).
- **Contains a one-way door (schema, public API shape, new dependency)?** No — additive dataclass fields and additive pydantic models only, no new dependency.

---

## Tasks

### Task 1: Briefing config fields

- **Files:** `scout/config.py`, `scout/.env.example`, `tests/test_config.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing tests in `tests/test_config.py` (append below the existing scorer/database tests, following the file's existing `_make_listing`-free style — plain `Settings()` construction):
    ```python
    def test_settings_uses_briefing_defaults_when_env_unset(monkeypatch):
        for var in (
            "BRIEFING_MAX_MATCHES",
            "GMAIL_ADDRESS",
            "GMAIL_APP_PASSWORD",
            "GMAIL_RECIPIENT",
        ):
            monkeypatch.delenv(var, raising=False)

        settings = Settings()

        assert settings.briefing_max_matches == 5
        assert settings.gmail_address == ""
        assert settings.gmail_app_password == ""
        assert settings.gmail_recipient == ""


    def test_settings_reads_briefing_env_overrides(monkeypatch):
        monkeypatch.setenv("BRIEFING_MAX_MATCHES", "3")
        monkeypatch.setenv("GMAIL_ADDRESS", "scout@example.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
        monkeypatch.setenv("GMAIL_RECIPIENT", "me@example.com")

        settings = Settings()

        assert settings.briefing_max_matches == 3
        assert settings.gmail_address == "scout@example.com"
        assert settings.gmail_app_password == "app-password"
        assert settings.gmail_recipient == "me@example.com"
    ```
  - [ ] Verify it fails: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v` — expect `AttributeError: 'Settings' object has no attribute 'briefing_max_matches'`
  - [ ] Implement: append to the `Settings` dataclass body in `scout/config.py` (after the existing `database_url` field, before `resume_text`):
    ```python
        briefing_max_matches: int = field(
            default_factory=lambda: int(os.getenv("BRIEFING_MAX_MATCHES", "5"))
        )
        gmail_address: str = field(
            default_factory=lambda: os.getenv("GMAIL_ADDRESS", "")
        )
        gmail_app_password: str = field(
            default_factory=lambda: os.getenv("GMAIL_APP_PASSWORD", "")
        )
        gmail_recipient: str = field(
            default_factory=lambda: os.getenv("GMAIL_RECIPIENT", "")
        )
    ```
    Append to `scout/.env.example` (below the existing `DATABASE_URL` line):
    ```
    BRIEFING_MAX_MATCHES=5
    GMAIL_ADDRESS=
    GMAIL_APP_PASSWORD=
    GMAIL_RECIPIENT=
    ```
  - [ ] Verify it passes: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v` — expect all tests including the 2 new ones to pass
  - [ ] Commit: `feat(scout): add briefing config fields`

### Task 2: Briefing prose schemas

- **Files:** `scout/shared/schemas.py`, `tests/test_schemas.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing tests in `tests/test_schemas.py` (append below the existing `ListingScore` tests):
    ```python
    from scout.shared.schemas import BriefingProse, BriefingTakeaway


    def test_briefing_takeaway_accepts_valid_data():
        takeaway = BriefingTakeaway(
            source="linkedin", external_id="123", takeaway="Strong Python overlap."
        )
        assert takeaway.external_id == "123"


    def test_briefing_prose_accepts_valid_data():
        prose = BriefingProse(
            intro="Here are today's top matches.",
            takeaways=[
                BriefingTakeaway(
                    source="linkedin", external_id="123", takeaway="Strong overlap."
                )
            ],
        )
        assert prose.intro == "Here are today's top matches."
        assert len(prose.takeaways) == 1


    def test_briefing_prose_allows_empty_takeaways():
        prose = BriefingProse(intro="No matches today.", takeaways=[])
        assert prose.takeaways == []
    ```
    Note: add the `BriefingProse, BriefingTakeaway` import to the existing `from scout.shared.schemas import ...` line at the top rather than a second import line, if one already exists after Task 1's edits land — check current imports first.
  - [ ] Verify it fails: `./.venv/Scripts/python.exe -m pytest tests/test_schemas.py -v` — expect `ImportError: cannot import name 'BriefingProse'`
  - [ ] Implement: append to `scout/shared/schemas.py` (below `ListingScore`):
    ```python
    class BriefingTakeaway(BaseModel):
        source: str
        external_id: str
        takeaway: str


    class BriefingProse(BaseModel):
        intro: str
        takeaways: list[BriefingTakeaway]
    ```
  - [ ] Verify it passes: `./.venv/Scripts/python.exe -m pytest tests/test_schemas.py -v` — expect all tests including the 3 new ones to pass
  - [ ] Commit: `feat(scout): add BriefingTakeaway and BriefingProse schemas`

### Task 3: Select step

- **Files:** `scout/sub_agents/briefing/select.py` (new), `tests/test_briefing_select.py` (new)
- **Gate:** none
- **Steps:**
  - [ ] Write failing tests in `tests/test_briefing_select.py`:
    ```python
    from datetime import datetime, timezone

    from scout.config import Settings
    from scout.shared.schemas import Listing, MatchResult
    from scout.sub_agents.briefing.select import select_top_matches


    def _make_match(external_id: str, score: int) -> MatchResult:
        listing = Listing(
            source="linkedin",
            external_id=external_id,
            title="Backend Engineer",
            company="Acme Corp",
            location="Remote",
            is_remote=True,
            url=f"https://www.linkedin.com/jobs/view/{external_id}",
            description="Build backend systems.",
            scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
        return MatchResult(listing=listing, score=score, reasoning="Good fit.")


    def test_select_top_matches_drops_below_threshold():
        settings = Settings(min_match_score=60, briefing_max_matches=5)
        matches = [_make_match("1", 80), _make_match("2", 40)]

        result = select_top_matches(matches, settings)

        assert [m.listing.external_id for m in result] == ["1"]


    def test_select_top_matches_sorts_descending():
        settings = Settings(min_match_score=0, briefing_max_matches=5)
        matches = [_make_match("1", 50), _make_match("2", 90), _make_match("3", 70)]

        result = select_top_matches(matches, settings)

        assert [m.listing.external_id for m in result] == ["2", "3", "1"]


    def test_select_top_matches_caps_to_max():
        settings = Settings(min_match_score=0, briefing_max_matches=2)
        matches = [_make_match("1", 90), _make_match("2", 80), _make_match("3", 70)]

        result = select_top_matches(matches, settings)

        assert [m.listing.external_id for m in result] == ["1", "2"]


    def test_select_top_matches_returns_empty_when_none_qualify():
        settings = Settings(min_match_score=90, briefing_max_matches=5)
        matches = [_make_match("1", 50)]

        result = select_top_matches(matches, settings)

        assert result == []
    ```
  - [ ] Verify it fails: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_select.py -v` — expect `ModuleNotFoundError: No module named 'scout.sub_agents.briefing.select'`
  - [ ] Implement `scout/sub_agents/briefing/select.py`:
    ```python
    from __future__ import annotations

    from scout.config import Settings
    from scout.shared.schemas import MatchResult


    def select_top_matches(
        matches: list[MatchResult], settings: Settings
    ) -> list[MatchResult]:
        qualifying = [m for m in matches if m.score >= settings.min_match_score]
        qualifying.sort(key=lambda m: m.score, reverse=True)
        return qualifying[: settings.briefing_max_matches]
    ```
  - [ ] Verify it passes: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_select.py -v` — expect `4 passed`
  - [ ] Commit: `feat(scout): add briefing select step`

---

## Verification

- [ ] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_schemas.py tests/test_briefing_select.py -v`
- [ ] Full suite still green: `./.venv/Scripts/python.exe -m pytest -v` (confirms the new `Settings` fields didn't break any existing Scraper/Scorer/Tracker test)

## Rollback

Revert the three commits above; all changes are additive fields/files with no callers elsewhere yet, so reverting is a plain `git revert` with no data or config cleanup needed.

---

## Notes / Learnings

<Filled in during execution — anything that should inform later phases.>
