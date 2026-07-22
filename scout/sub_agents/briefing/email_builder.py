from __future__ import annotations

from email.message import EmailMessage
from html import escape
from pathlib import Path

from scout.config import Settings
from scout.shared.schemas import BriefingProse, MatchResult

_FALLBACK_TAKEAWAY_TEMPLATE = "Worth a look — scored {score}/100 against your resume."


def _index_takeaways(prose: BriefingProse | None) -> dict[tuple[str, str], str]:
    if prose is None:
        return {}
    return {
        (takeaway.source, takeaway.external_id): takeaway.takeaway
        for takeaway in prose.takeaways
    }


def _report_uri(report_path: Path, settings: Settings) -> str | None:
    """Build a valid, clickable file:// URI pointing at the report on the host.

    The app runs inside a container where ``report_path`` only resolves to a
    path inside that (ephemeral) container's filesystem — meaningless once
    opened on the host. Only when the user has told us where ``./reports``
    lives on the host machine (``settings.report_host_dir``) can we build a
    link that will actually resolve when clicked. Otherwise return ``None``
    so callers fall back to showing a plain, non-clickable path.

    ``Path.as_uri()`` requires an absolute path, and on Windows
    ``str(Path(...))`` uses backslashes which are not valid in a URI.
    Resolving first sidesteps both issues on Windows and POSIX alike.
    """
    if not settings.report_host_dir:
        return None
    relative = report_path.relative_to(settings.report_output_dir)
    host_path = Path(settings.report_host_dir) / relative
    return host_path.resolve().as_uri()


def _report_link_html(report_path: Path, settings: Settings) -> str:
    report_uri = _report_uri(report_path, settings)
    if report_uri is None:
        return f"<p>Full report: {escape(str(report_path))}</p>"
    return (
        f'<p>Full report: <a href="{escape(report_uri)}">'
        f"{escape(str(report_path))}</a></p>"
    )


def _takeaway_for(
    match: MatchResult, takeaways_by_key: dict[tuple[str, str], str]
) -> str:
    key = (match.listing.source, match.listing.external_id)
    if key in takeaways_by_key:
        return takeaways_by_key[key]
    return _FALLBACK_TAKEAWAY_TEMPLATE.format(score=match.score)


def build_email(
    top_matches: list[MatchResult],
    prose: BriefingProse | None,
    settings: Settings,
    report_path: Path | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.gmail_address
    message["To"] = settings.gmail_recipient or settings.gmail_address

    if not top_matches:
        message["Subject"] = "Job Market Scout: no strong matches today"
        text = "No listings met your match-score threshold today."
        html = f"<p>{escape(text)}</p>"
        if report_path is not None:
            text += f"\n\nFull report: {report_path}"
            html += _report_link_html(report_path, settings)
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        return message

    count = len(top_matches)
    message["Subject"] = (
        f"Job Market Scout: {count} match{'es' if count != 1 else ''} today"
    )

    intro = prose.intro if prose is not None else ""
    takeaways_by_key = _index_takeaways(prose)
    text_lines = [intro, ""]
    html_items = []
    for match in top_matches:
        listing = match.listing
        takeaway = _takeaway_for(match, takeaways_by_key)
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
    if report_path is not None:
        text_lines += [f"Full report: {report_path}", ""]
    text = "\n".join(text_lines)

    html = f"<p>{escape(intro)}</p><ul>{''.join(html_items)}</ul>"
    if report_path is not None:
        html += _report_link_html(report_path, settings)

    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message
