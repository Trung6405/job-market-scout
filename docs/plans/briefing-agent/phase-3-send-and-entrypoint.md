# Phase 3: Send & Entry Point

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 1 and Phase 2 complete (`select_top_matches`, `summarize_matches`, `build_email`)

---

## Goal

Build the Send step (Gmail SMTP via `smtplib`, fail-fast on missing config or auth/send failure) and the single entry point `run_briefing` that wires Join → Select → Summarize → Build → Send together, matching how `track_listings`/`build_scorer_agent` are each independently callable. Done when `run_briefing` is fully unit-tested with the LLM/SMTP seams mocked, and has been exercised once manually against a live DeepSeek key and Gmail app password.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** Yes — `notification.send_email` makes a real SMTP connection with a real password when actually invoked. All unit tests in this phase monkeypatch `smtplib.SMTP_SSL`, so no test opens a real connection; the real send is exercised only in Manual Verification below, once, by a human with their own Gmail app password.
- **Contains a one-way door (schema, public API shape, new dependency)?** No.

---

## Tasks

### Task 1: Notification (SMTP send)

- **Files:** `scout/sub_agents/briefing/notification.py` (new), `tests/test_briefing_notification.py` (new)
- **Gate:** none
- **Steps:**
  - [x] Write failing tests in `tests/test_briefing_notification.py`:
    ```python
    from __future__ import annotations

    from email.message import EmailMessage

    import pytest

    from scout.config import Settings
    from scout.sub_agents.briefing.notification import send_email


    class _FakeSmtp:
        instances: list["_FakeSmtp"] = []

        def __init__(self, host, port):
            self.host = host
            self.port = port
            self.login_calls = []
            self.sent_messages = []
            _FakeSmtp.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def login(self, address, password):
            self.login_calls.append((address, password))

        def send_message(self, message):
            self.sent_messages.append(message)


    @pytest.fixture(autouse=True)
    def _reset_fake_smtp():
        _FakeSmtp.instances = []
        yield
        _FakeSmtp.instances = []


    def test_send_email_raises_when_gmail_address_missing(monkeypatch):
        monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSmtp)
        settings = Settings(gmail_address="", gmail_app_password="secret")

        with pytest.raises(ValueError):
            send_email(EmailMessage(), settings)

        assert _FakeSmtp.instances == []


    def test_send_email_raises_when_app_password_missing(monkeypatch):
        monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSmtp)
        settings = Settings(gmail_address="scout@example.com", gmail_app_password="")

        with pytest.raises(ValueError):
            send_email(EmailMessage(), settings)

        assert _FakeSmtp.instances == []


    def test_send_email_logs_in_and_sends(monkeypatch):
        monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSmtp)
        settings = Settings(gmail_address="scout@example.com", gmail_app_password="secret")
        message = EmailMessage()

        send_email(message, settings)

        smtp = _FakeSmtp.instances[0]
        assert smtp.login_calls == [("scout@example.com", "secret")]
        assert smtp.sent_messages == [message]


    def test_send_email_propagates_smtp_failures(monkeypatch):
        class _FailingSmtp(_FakeSmtp):
            def login(self, address, password):
                raise RuntimeError("auth failed")

        monkeypatch.setattr("smtplib.SMTP_SSL", _FailingSmtp)
        settings = Settings(gmail_address="scout@example.com", gmail_app_password="secret")

        with pytest.raises(RuntimeError):
            send_email(EmailMessage(), settings)
    ```
  - [x] Verify it fails: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_notification.py -v` — expect `ModuleNotFoundError`
  - [x] Implement `scout/sub_agents/briefing/notification.py`:
    ```python
    from __future__ import annotations

    import smtplib
    from email.message import EmailMessage

    from scout.config import Settings

    _SMTP_HOST = "smtp.gmail.com"
    _SMTP_PORT = 465


    def send_email(message: EmailMessage, settings: Settings) -> None:
        if not settings.gmail_address or not settings.gmail_app_password:
            raise ValueError(
                "GMAIL_ADDRESS and GMAIL_APP_PASSWORD must both be set to send a "
                "briefing email"
            )
        with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT) as smtp:
            smtp.login(settings.gmail_address, settings.gmail_app_password)
            smtp.send_message(message)
    ```
  - [x] Verify it passes: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_notification.py -v` — expect `4 passed`
  - [x] Commit: `feat(scout): add briefing SMTP notification`

### Task 2: Entry point

- **Files:** `scout/sub_agents/briefing/briefing.py` (new), `tests/test_briefing_entrypoint.py` (new)
- **Gate:** none
- **Steps:**
  - [x] Write failing tests in `tests/test_briefing_entrypoint.py`:
    ```python
    from __future__ import annotations

    from email.message import EmailMessage

    import pytest

    from scout.config import Settings
    from scout.shared.schemas import BriefingProse
    from scout.sub_agents.briefing.briefing import run_briefing
    from tests.test_briefing_agent import _make_match


    def _listing_and_score(match):
        from scout.shared.schemas import ListingScore

        return match.listing, ListingScore(
            source=match.listing.source,
            external_id=match.listing.external_id,
            score=match.score,
            reasoning=match.reasoning,
        )


    @pytest.mark.asyncio
    async def test_run_briefing_summarizes_and_sends_when_matches_qualify(monkeypatch):
        match = _make_match("1", "Platform Engineer", 88)
        listing, score = _listing_and_score(match)
        settings = Settings(min_match_score=60, gmail_address="scout@example.com")

        summarize_calls = []
        build_calls = []
        send_calls = []

        async def _fake_summarize(top_matches, active_settings):
            summarize_calls.append(top_matches)
            return BriefingProse(intro="Nice matches.", takeaways=[])

        def _fake_build(top_matches, prose, active_settings):
            build_calls.append((top_matches, prose))
            return EmailMessage()

        def _fake_send(message, active_settings):
            send_calls.append(message)

        monkeypatch.setattr(
            "scout.sub_agents.briefing.briefing.summarize_matches", _fake_summarize
        )
        monkeypatch.setattr(
            "scout.sub_agents.briefing.briefing.build_email", _fake_build
        )
        monkeypatch.setattr(
            "scout.sub_agents.briefing.briefing.send_email", _fake_send
        )

        await run_briefing([listing], [score], settings)

        assert len(summarize_calls) == 1
        assert [m.listing.external_id for m in summarize_calls[0]] == ["1"]
        assert len(build_calls) == 1
        assert len(send_calls) == 1


    @pytest.mark.asyncio
    async def test_run_briefing_skips_summarize_when_no_matches_qualify(monkeypatch):
        match = _make_match("1", "Platform Engineer", 10)
        listing, score = _listing_and_score(match)
        settings = Settings(min_match_score=60, gmail_address="scout@example.com")

        summarize_calls = []
        build_calls = []

        async def _fake_summarize(top_matches, active_settings):
            summarize_calls.append(top_matches)
            return BriefingProse(intro="", takeaways=[])

        def _fake_build(top_matches, prose, active_settings):
            build_calls.append((top_matches, prose))
            return EmailMessage()

        def _fake_send(message, active_settings):
            pass

        monkeypatch.setattr(
            "scout.sub_agents.briefing.briefing.summarize_matches", _fake_summarize
        )
        monkeypatch.setattr(
            "scout.sub_agents.briefing.briefing.build_email", _fake_build
        )
        monkeypatch.setattr(
            "scout.sub_agents.briefing.briefing.send_email", _fake_send
        )

        await run_briefing([listing], [score], settings)

        assert summarize_calls == []
        assert build_calls == [([], None)]
    ```
  - [x] Verify it fails: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_entrypoint.py -v` — expect `ModuleNotFoundError`
  - [x] Implement `scout/sub_agents/briefing/briefing.py`:
    ```python
    from __future__ import annotations

    from email.message import EmailMessage

    from scout.config import Settings
    from scout.config import settings as default_settings
    from scout.shared.schemas import Listing, ListingScore
    from scout.sub_agents.briefing.email_builder import build_email
    from scout.sub_agents.briefing.notification import send_email
    from scout.sub_agents.briefing.select import select_top_matches
    from scout.sub_agents.briefing.summarize import summarize_matches
    from scout.sub_agents.scorer.results import join_match_results


    async def run_briefing(
        listings: list[Listing],
        scores: list[ListingScore],
        settings: Settings | None = None,
    ) -> EmailMessage:
        active_settings = settings or default_settings
        matches = join_match_results(listings, scores)
        top_matches = select_top_matches(matches, active_settings)
        prose = (
            await summarize_matches(top_matches, active_settings)
            if top_matches
            else None
        )
        message = build_email(top_matches, prose, active_settings)
        send_email(message, active_settings)
        return message
    ```
  - [x] Verify it passes: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_entrypoint.py -v` — expect `2 passed`
  - [x] Commit: `feat(scout): add briefing entry point`

---

## Verification

- [x] All phase tests pass: `./.venv/Scripts/python.exe -m pytest tests/test_briefing_notification.py tests/test_briefing_entrypoint.py -v`
- [x] Full suite green: `./.venv/Scripts/python.exe -m pytest -v`

## Observability

`run_briefing` has no logging today, consistent with `track_listings`/`build_scorer_agent` having none either — this is a single-user CLI-invoked tool, not a service; a failure surfaces as an uncaught exception in whatever invokes `run_briefing`; no additional observability is being introduced here (YAGNI, matches project precedent).

## Rollback

Revert the two commits above. Nothing outside `scout/sub_agents/briefing/` calls into `run_briefing` or `notification.send_email` yet, so reverting is isolated.

---

## Notes / Learnings

Executed exactly as planned. Full automated suite after this phase and
across the whole plan: 77 passed, 12 skipped (pre-existing DB tests that
need a live Postgres — unaffected by this work). **Manual Verification
below has not been run yet** — it needs a live `DEEPSEEK_API_KEY` and a
real Gmail app password, neither of which is available in this session.

---

## Manual Verification (post-plan, not part of TDD loop)

The tasks above are fully unit-testable without a live DeepSeek key or Gmail app password. Before relying on Briefing for a real daily email:

1. Set `DEEPSEEK_API_KEY`, `GMAIL_ADDRESS`, and `GMAIL_APP_PASSWORD` (a Gmail [app password](https://myaccount.google.com/apppasswords), not the account password) in `scout/.env`. Leave `GMAIL_RECIPIENT` unset to send to yourself, or set it to a different address.
2. In a Python shell, build a small `list[Listing]` and matching `list[ListingScore]` (or use real output from the Scraper/Scorer stages), and `await run_briefing(listings, scores)`.
3. Confirm the received email's title/company/link/score for each listing match the input data exactly, and that the intro/takeaway prose reads sensibly and doesn't contradict the facts.
4. Re-run with `scores` that don't clear `min_match_score` (or an empty list) and confirm the "no strong matches today" email arrives with no DeepSeek call made (no new usage on the DeepSeek dashboard).
5. Deliberately set `GMAIL_APP_PASSWORD` to an invalid value and confirm `run_briefing` raises rather than failing silently.

This step needs a live DeepSeek key and Gmail app password, so it isn't part of the automated task loop above — do it once after Task 2.
