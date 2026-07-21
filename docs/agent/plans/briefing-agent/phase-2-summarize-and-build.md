# Phase 2: Summarize & Build

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 1 complete (`select_top_matches`, `BriefingProse`/`BriefingTakeaway`, `briefing_max_matches`)

---

## Goal

Build the Summarize step (an `LlmAgent` that writes intro + per-listing takeaway prose for the selected top matches, invoked via `google.adk.runners.InMemoryRunner` and parsed into `BriefingProse`) and the Build step (a deterministic function that merges real listing fields with that prose, or the zero-matches template, into a multipart HTML+text `EmailMessage`). Done when both steps are fully unit-tested without any live DeepSeek call, and `build_email`'s output is proven to reproduce listing facts verbatim regardless of what the LLM prose contains.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** Yes — `build_briefing_agent`/`summarize_matches` construct and would invoke a live DeepSeek call via LiteLLM at runtime. All unit tests in this phase monkeypatch the runner-invocation seam (`_run_briefing_agent`), so no test makes a real network call; the real call is exercised only in Phase 3's Manual Verification.
- **Contains a one-way door (schema, public API shape, new dependency)?** No.

---

## Tasks

### Task 1: Briefing prompt

- **Files:** `scout/prompts.py`, `tests/test_prompts.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing tests in `tests/test_prompts.py` (append):
    ```python
    from datetime import datetime, timezone

    from scout.shared.schemas import Listing, MatchResult
    from scout.prompts import build_briefing_instruction


    def _make_match(external_id: str, title: str, score: int) -> MatchResult:
        listing = Listing(
            source="linkedin",
            external_id=external_id,
            title=title,
            company="Acme Corp",
            location="Remote",
            is_remote=True,
            url=f"https://www.linkedin.com/jobs/view/{external_id}",
            description="Build backend systems.",
            scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
        return MatchResult(listing=listing, score=score, reasoning="Good fit.")


    def test_build_briefing_instruction_includes_resume_and_top_match_titles():
        settings = Settings()
        matches = [_make_match("1", "Platform Engineer", 88)]

        instruction = build_briefing_instruction(settings, matches)

        assert settings.resume_text in instruction
        assert "Platform Engineer" in instruction
        assert "88" in instruction


    def test_build_briefing_instruction_excludes_listing_url_and_description():
        settings = Settings()
        matches = [_make_match("1", "Platform Engineer", 88)]

        instruction = build_briefing_instruction(settings, matches)

        assert "linkedin.com/jobs/view" not in instruction
        assert "Build backend systems." not in instruction
    ```
    Note: `Settings` is already imported in this file from the scraper/scorer test additions — reuse it, don't re-import.
  - [x] Verify it fails: `./.venv/Scripts/python.exe -m pytest tests/test_prompts.py -v` — expect `ImportError: cannot import name 'build_briefing_instruction'`
  - [x] Implement: append to `scout/prompts.py`:
    ```python
    def _project_match_for_briefing(match: MatchResult) -> dict:
        return {
            "source": match.listing.source,
            "external_id": match.listing.external_id,
            "title": match.listing.title,
            "company": match.listing.company,
            "score": match.score,
        }


    def build_briefing_instruction(
        settings: Settings, top_matches: list[MatchResult]
    ) -> str:
        matches_json = json.dumps(
            [_project_match_for_briefing(match) for match in top_matches], indent=2
        )
        return f"""\
    You are the briefing writer for Job Market Scout. Write a short, upbeat
    intro paragraph (2-3 sentences) for today's job matches, then one
    one-line takeaway per listing explaining why it's worth a look, based
    only on the title, company, and score given. Do not invent facts about
    any listing beyond what is given, and do not call any tool.

    Resume:
    {settings.resume_text}

    Today's top matches:
    {matches_json}

    Return a single JSON object with two keys: "intro" (string) and
    "takeaways" (a list of objects, each with "source" and "external_id"
    copied exactly from the match, and "takeaway", one short sentence).
    Return only the JSON object, no commentary.
    """
    ```
    Add `MatchResult` to the existing `from scout.shared.schemas import Listing` line at the top of `scout/prompts.py` if it isn't already imported.
  - [x] Verify it passes: `./.venv/Scripts/python.exe -m pytest tests/test_prompts.py -v`
  - [x] Commit: `feat(scout): add briefing prompt`

### Task 2: Briefing LlmAgent

- **Files:** `scout/sub_agents/briefing/agent.py` (currently empty), `tests/test_briefing_agent.py` (new)
- **Gate:** none
- **Steps:**
  - [x] Write failing tests in `tests/test_briefing_agent.py` (mirror `tests/test_scorer_agent.py`'s structure):
    ```python
    from datetime import datetime, timezone

    from google.adk.agents import LlmAgent
    from google.adk.models.lite_llm import LiteLlm

    from scout.config import Settings
    from scout.shared.schemas import Listing, MatchResult
    from scout.sub_agents.briefing.agent import build_briefing_agent


    def _make_match(external_id: str, title: str, score: int) -> MatchResult:
        listing = Listing(
            source="linkedin",
            external_id=external_id,
            title=title,
            company="Acme Corp",
            location="Remote",
            is_remote=True,
            url=f"https://www.linkedin.com/jobs/view/{external_id}",
            description="Build backend systems.",
            scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
        return MatchResult(listing=listing, score=score, reasoning="Good fit.")


    def test_build_briefing_agent_uses_configured_model():
        settings = Settings(deepseek_model="deepseek/deepseek-reasoner")

        agent = build_briefing_agent([_make_match("1", "Platform Engineer", 88)], settings)

        assert isinstance(agent, LlmAgent)
        assert isinstance(agent.model, LiteLlm)
        assert agent.model.model == "deepseek/deepseek-reasoner"


    def test_build_briefing_agent_has_no_output_schema():
        agent = build_briefing_agent([_make_match("1", "Platform Engineer", 88)], Settings())

        assert agent.output_schema is None


    def test_build_briefing_agent_registers_no_tools():
        agent = build_briefing_agent([_make_match("1", "Platform Engineer", 88)], Settings())

        assert agent.tools == []


    def test_build_briefing_agent_instruction_includes_match_title():
        agent = build_briefing_agent([_make_match("1", "Platform Engineer", 88)], Settings())

        assert "Platform Engineer" in agent.instruction
    ```
  - [x] Verify it fails: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_agent.py -v` — expect a collection error (empty module, no `build_briefing_agent`)
  - [x] Implement `scout/sub_agents/briefing/agent.py`:
    ```python
    from __future__ import annotations

    from google.adk.agents import LlmAgent
    from google.adk.models.lite_llm import LiteLlm

    from scout.config import Settings
    from scout.config import settings as default_settings
    from scout.prompts import build_briefing_instruction
    from scout.shared.schemas import MatchResult


    def build_briefing_agent(
        top_matches: list[MatchResult], settings: Settings | None = None
    ) -> LlmAgent:
        active_settings = settings or default_settings
        return LlmAgent(
            name="briefing",
            model=LiteLlm(model=active_settings.deepseek_model, temperature=0.3),
            instruction=build_briefing_instruction(active_settings, top_matches),
        )
    ```
    `output_schema` is deliberately omitted — see plan.md's Key Decisions for why a `BaseModel`-shaped `output_schema` isn't used here. `temperature=0.3` (not `0` like the Scorer) because this step is prose, not a reproducible numeric score — implementation-time judgment, adjust freely if manual verification reads oddly.
  - [x] Verify it passes: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_agent.py -v` — expect `4 passed`
  - [x] Commit: `feat(scout): add briefing LlmAgent`

### Task 3: Summarize step (Runner invocation + parsing)

- **Files:** `scout/sub_agents/briefing/summarize.py` (new), `tests/test_briefing_summarize.py` (new)
- **Gate:** none
- **Steps:**
  - [x] Write failing tests in `tests/test_briefing_summarize.py`:
    ```python
    from __future__ import annotations

    import json

    import pytest

    from scout.config import Settings
    from scout.shared.schemas import BriefingProse
    from scout.sub_agents.briefing.summarize import (
        parse_briefing_prose,
        summarize_matches,
    )
    from tests.test_briefing_agent import _make_match


    def test_parse_briefing_prose_valid_json():
        raw = json.dumps(
            {
                "intro": "Nice matches today.",
                "takeaways": [
                    {"source": "linkedin", "external_id": "1", "takeaway": "Great fit."}
                ],
            }
        )

        prose = parse_briefing_prose(raw)

        assert prose.intro == "Nice matches today."
        assert prose.takeaways[0].external_id == "1"


    def test_parse_briefing_prose_rejects_non_json():
        with pytest.raises(Exception):
            parse_briefing_prose("not json")


    @pytest.mark.asyncio
    async def test_summarize_matches_returns_parsed_prose(monkeypatch):
        raw = json.dumps(
            {
                "intro": "Nice matches today.",
                "takeaways": [
                    {"source": "linkedin", "external_id": "1", "takeaway": "Great fit."}
                ],
            }
        )

        async def _fake_run(agent):
            return raw

        monkeypatch.setattr(
            "scout.sub_agents.briefing.summarize._run_briefing_agent", _fake_run
        )

        prose = await summarize_matches(
            [_make_match("1", "Platform Engineer", 88)], Settings()
        )

        assert isinstance(prose, BriefingProse)
        assert prose.takeaways[0].takeaway == "Great fit."
    ```
  - [x] Verify it fails: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_summarize.py -v` — expect `ModuleNotFoundError: No module named 'scout.sub_agents.briefing.summarize'`
  - [x] Implement `scout/sub_agents/briefing/summarize.py`:
    ```python
    from __future__ import annotations

    import json

    from google.adk.agents import LlmAgent
    from google.adk.runners import InMemoryRunner
    from google.genai import types as genai_types

    from scout.config import Settings
    from scout.config import settings as default_settings
    from scout.shared.schemas import BriefingProse, MatchResult
    from scout.sub_agents.briefing.agent import build_briefing_agent

    _APP_NAME = "briefing"
    _USER_ID = "briefing"
    _SESSION_ID = "briefing"


    def parse_briefing_prose(raw_text: str) -> BriefingProse:
        return BriefingProse.model_validate(json.loads(raw_text))


    async def _run_briefing_agent(agent: LlmAgent) -> str:
        runner = InMemoryRunner(agent=agent, app_name=_APP_NAME)
        await runner.session_service.create_session(
            app_name=_APP_NAME, user_id=_USER_ID, session_id=_SESSION_ID
        )
        message = genai_types.Content(
            role="user", parts=[genai_types.Part(text="Generate the briefing.")]
        )
        final_text: str | None = None
        async for event in runner.run_async(
            user_id=_USER_ID, session_id=_SESSION_ID, new_message=message
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = event.content.parts[0].text
        if final_text is None:
            raise ValueError("briefing agent produced no final response")
        return final_text


    async def summarize_matches(
        top_matches: list[MatchResult], settings: Settings | None = None
    ) -> BriefingProse:
        active_settings = settings or default_settings
        agent = build_briefing_agent(top_matches, active_settings)
        raw_text = await _run_briefing_agent(agent)
        return parse_briefing_prose(raw_text)
    ```
  - [x] Verify it passes: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_summarize.py -v` — expect `3 passed`
  - [x] Commit: `feat(scout): add briefing summarize step`

### Task 4: Build step (email construction)

- **Files:** `scout/sub_agents/briefing/email_builder.py` (new), `tests/test_briefing_email_builder.py` (new)
- **Gate:** none
- **Steps:**
  - [x] Write failing tests in `tests/test_briefing_email_builder.py`:
    ```python
    from __future__ import annotations

    from scout.config import Settings
    from scout.shared.schemas import BriefingProse, BriefingTakeaway
    from scout.sub_agents.briefing.email_builder import build_email
    from tests.test_briefing_agent import _make_match


    def _settings():
        return Settings(gmail_address="scout@example.com", gmail_recipient="me@example.com")


    def test_build_email_zero_matches_uses_template():
        message = build_email([], None, _settings())

        assert "no strong matches" in message["Subject"].lower()
        assert message.get_body(preferencelist=("plain",)) is not None
        assert message.get_body(preferencelist=("html",)) is not None


    def test_build_email_reproduces_listing_fields_verbatim():
        match = _make_match("1", "Platform Engineer", 88)
        prose = BriefingProse(
            intro="Nice matches.",
            takeaways=[
                BriefingTakeaway(source="linkedin", external_id="1", takeaway="Great fit.")
            ],
        )

        message = build_email([match], prose, _settings())

        text_body = message.get_body(preferencelist=("plain",)).get_content()
        assert match.listing.title in text_body
        assert match.listing.company in text_body
        assert str(match.listing.url) in text_body
        assert "88" in text_body


    def test_build_email_uses_fallback_line_when_takeaway_missing():
        match = _make_match("1", "Platform Engineer", 88)
        prose = BriefingProse(intro="Nice matches.", takeaways=[])

        message = build_email([match], prose, _settings())

        text_body = message.get_body(preferencelist=("plain",)).get_content()
        assert "88" in text_body
        assert "Platform Engineer" in text_body


    def test_build_email_escapes_html_special_characters():
        match = _make_match("1", "<script>alert(1)</script>", 88)
        prose = BriefingProse(intro="Nice matches.", takeaways=[])

        message = build_email([match], prose, _settings())

        html_body = message.get_body(preferencelist=("html",)).get_content()
        assert "<script>alert(1)</script>" not in html_body
    ```
  - [x] Verify it fails: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_email_builder.py -v` — expect `ModuleNotFoundError`
  - [x] Implement `scout/sub_agents/briefing/email_builder.py`:
    ```python
    from __future__ import annotations

    from email.message import EmailMessage
    from html import escape

    from scout.config import Settings
    from scout.shared.schemas import BriefingProse, MatchResult

    _FALLBACK_TAKEAWAY_TEMPLATE = "Worth a look — scored {score}/100 against your resume."


    def _takeaway_for(match: MatchResult, prose: BriefingProse | None) -> str:
        if prose is not None:
            for takeaway in prose.takeaways:
                if (
                    takeaway.source == match.listing.source
                    and takeaway.external_id == match.listing.external_id
                ):
                    return takeaway.takeaway
        return _FALLBACK_TAKEAWAY_TEMPLATE.format(score=match.score)


    def build_email(
        top_matches: list[MatchResult],
        prose: BriefingProse | None,
        settings: Settings,
    ) -> EmailMessage:
        message = EmailMessage()
        message["From"] = settings.gmail_address
        message["To"] = settings.gmail_recipient or settings.gmail_address

        if not top_matches:
            message["Subject"] = "Job Market Scout: no strong matches today"
            text = "No listings met your match-score threshold today."
            message.set_content(text)
            message.add_alternative(f"<p>{escape(text)}</p>", subtype="html")
            return message

        count = len(top_matches)
        message["Subject"] = f"Job Market Scout: {count} match{'es' if count != 1 else ''} today"

        intro = prose.intro if prose is not None else ""
        text_lines = [intro, ""]
        html_items = []
        for match in top_matches:
            listing = match.listing
            takeaway = _takeaway_for(match, prose)
            text_lines += [
                f"{listing.title} at {listing.company} — {match.score}/100",
                str(listing.url),
                takeaway,
                "",
            ]
            html_items.append(
                "<li>"
                f'<a href="{escape(str(listing.url))}">{escape(listing.title)}</a> '
                f"at {escape(listing.company)} — {match.score}/100<br>"
                f"{escape(takeaway)}"
                "</li>"
            )
        message.set_content("\n".join(text_lines))
        message.add_alternative(
            f"<p>{escape(intro)}</p><ul>{''.join(html_items)}</ul>", subtype="html"
        )
        return message
    ```
  - [x] Verify it passes: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_email_builder.py -v` — expect `4 passed`
  - [x] Commit: `feat(scout): add briefing email builder`

---

## Verification

- [x] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_prompts.py tests/test_briefing_agent.py tests/test_briefing_summarize.py tests/test_briefing_email_builder.py -v`
- [x] Full suite still green: `./.venv/Scripts/python.exe -m pytest -v`

## Observability

No logging is added in this phase — `run_briefing` (Phase 3) is the natural place for a single start/end log line once the whole pipeline exists; adding partial logging here would be premature since Summarize/Build aren't independently invoked by anything yet.

## Rollback

Revert the four commits above. `scout/sub_agents/briefing/agent.py` reverts to its empty-stub state; no other module in the codebase imports from it yet, so nothing else breaks.

---

## Notes / Learnings

Executed exactly as planned. `_run_briefing_agent`'s monkeypatch seam
(Task 3) worked cleanly for isolating `summarize_matches` from a real
`InMemoryRunner`/DeepSeek call — no test in this phase touches the network.
Code matched the plan's snippets verbatim; no design changes needed.
