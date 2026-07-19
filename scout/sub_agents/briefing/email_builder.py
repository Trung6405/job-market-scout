from __future__ import annotations

from email.message import EmailMessage
from html import escape

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
    message.set_content("\n".join(text_lines))
    message.add_alternative(
        f"<p>{escape(intro)}</p><ul>{''.join(html_items)}</ul>", subtype="html"
    )
    return message
