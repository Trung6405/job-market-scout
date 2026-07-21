from __future__ import annotations

import re
from pathlib import Path

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


def test_build_email_zero_matches_includes_report_path_when_given():
    report_path = Path("reports/2026-07-21/dashboard.html")

    message = build_email([], None, _settings(), report_path=report_path)

    text_body = message.get_body(preferencelist=("plain",)).get_content()
    html_body = message.get_body(preferencelist=("html",)).get_content()
    assert str(report_path) in text_body
    assert str(report_path) in html_body


def test_build_email_with_matches_includes_report_path_when_given():
    report_path = Path("reports/2026-07-21/dashboard.html")
    match = _make_match("1", "Platform Engineer", 88)
    prose = BriefingProse(intro="Nice matches.", takeaways=[])

    message = build_email([match], prose, _settings(), report_path=report_path)

    text_body = message.get_body(preferencelist=("plain",)).get_content()
    html_body = message.get_body(preferencelist=("html",)).get_content()
    assert str(report_path) in text_body
    assert str(report_path) in html_body


def test_build_email_omits_report_path_reference_when_not_given():
    match = _make_match("1", "Platform Engineer", 88)
    prose = BriefingProse(intro="Nice matches.", takeaways=[])

    message = build_email([match], prose, _settings())

    text_body = message.get_body(preferencelist=("plain",)).get_content()
    html_body = message.get_body(preferencelist=("html",)).get_content()
    assert "Full report" not in text_body
    assert "Full report" not in html_body

    zero_match_message = build_email([], None, _settings())
    zero_text_body = zero_match_message.get_body(preferencelist=("plain",)).get_content()
    zero_html_body = zero_match_message.get_body(preferencelist=("html",)).get_content()
    assert "Full report" not in zero_text_body
    assert "Full report" not in zero_html_body


def test_build_email_report_path_href_is_valid_escaped_file_uri():
    report_path = Path("reports/2026-07-21/dashboard.html")
    match = _make_match("1", "Platform Engineer", 88)
    prose = BriefingProse(intro="Nice matches.", takeaways=[])

    message = build_email([match], prose, _settings(), report_path=report_path)

    html_body = message.get_body(preferencelist=("html",)).get_content()
    href_match = re.search(r'Full report: <a href="([^"]+)">', html_body)
    assert href_match is not None
    href = href_match.group(1)

    assert href.startswith("file:///")
    assert "\\" not in href
    # The href must be the escaped, resolved absolute URI — not a raw
    # interpolation of the (possibly relative, backslash-containing on
    # Windows) report_path.
    assert str(report_path) not in href
    assert href == report_path.resolve().as_uri()
