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
    message["Subject"] = (
        f"Job Market Scout: {count} match{'es' if count != 1 else ''} today"
    )

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
