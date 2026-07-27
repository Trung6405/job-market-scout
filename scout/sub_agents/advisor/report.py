from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from markupsafe import Markup, escape

from scout.config import Settings
from scout.shared.db import (
    get_adjacent_runs,
    get_run,
    get_run_details,
    get_run_summaries,
)
from scout.shared.schemas import Listing, Profile, RunListingDetail

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Job descriptions arrive as Markdown (JobSpy's default --description_format),
# complete with backslash escapes like ``C\+\+`` and ``\|``. Render them to HTML
# so the advisor page shows formatted text rather than raw Markdown syntax.
# ``html=False`` escapes any raw HTML in the scraped source, so untrusted markup
# can't inject tags (the commonmark preset would otherwise pass it through).
_MARKDOWN = MarkdownIt("commonmark", {"breaks": True, "html": False})

_BAND_INFO = {
    "strong_match": ("Strong-match", "strong"),
    "competitive": ("Competitive", "comp"),
    "reach": ("Reach", "reach"),
}


def _band_label(band: str) -> str:
    return _BAND_INFO.get(band, (band, ""))[0]


def _band_css(band: str) -> str:
    return _BAND_INFO.get(band, (band, ""))[1]


def _render_markdown(text: str | None) -> Markup:
    if not text:
        return Markup("")
    return Markup(_MARKDOWN.render(text))


# Deliberately identical to the pattern in ``scout/sub_agents/coach/grounding.py``.
# That module decides which URLs may be *stored*; this one decides which are
# *clickable*, and the two stay independent in policy — but they must agree on
# where a URL starts and ends. If this found a different span, a URL the
# validator approved and stored could fail to render as a link, or render as a
# fragment of itself. Excluding brackets from the class rather than balancing
# them afterwards is also what makes ``[label](url)`` yield a clean URL.
_URL_PATTERN = re.compile(r"https?://[^\s<>\"'()\[\]]+")

# Trailing sentence punctuation is prose, never part of the URL — same
# reasoning, and same set, as the validator's.
_TRAILING_PUNCTUATION = ".,;:!?"


def _iter_urls(text: str) -> list[tuple[int, int, str]]:
    """Every URL in a tip as an ``(start, end, url)`` span of ``text``.

    Spans index the *raw* string so ``_linkify`` can splice on them and escape
    each piece itself. Locating URLs before escaping also keeps the spans
    identical to the validator's: matching escaped text would shift them, and a
    URL ending in ``&`` would escape to ``&amp;``, whose trailing ``;`` the
    punctuation trim would then eat.
    """
    spans: list[tuple[int, int, str]] = []
    for match in _URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if url:
            spans.append((match.start(), match.start() + len(url), url))
    return spans


# A Markdown citation's ``[label](`` opener, anchored so it must sit flush
# against the URL that follows. The coach's validator rewrites this syntax only
# for URLs it *strips*, so a surviving citation keeps its brackets verbatim in
# ``listing_tips.tip`` and arrives here intact.
_MARKDOWN_LABEL = re.compile(r"\[([^\[\]]*)\]\($")


def _link_label(url: str) -> str:
    """A citation's visible text: host and path, without the ceremony.

    Readers scan for *what* is being recommended, not for its scheme or query
    string, so ``https://www.example.com/x?tab=readme`` shows as
    ``example.com/x``. The full URL stays in the ``href``.
    """
    parts = urlsplit(url)
    host = parts.netloc.removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


def _linkify(text: str, limit: int) -> Markup:
    """Render a tip's prose with its first ``limit`` distinct URLs linked.

    Escaping is this function's own responsibility: returning ``Markup`` opts
    the value out of Jinja's autoescape, so nothing downstream will do it. The
    prose is escaped piecewise and the anchors are assembled last, which means
    every character passes through ``escape`` exactly once and escaping cannot
    destroy a link it has already inserted.
    """
    if not text:
        return Markup("")

    out: list[str] = []
    cursor = 0
    for start, end, url in _iter_urls(text):
        markdown = _MARKDOWN_LABEL.search(text, cursor, start)
        if markdown is not None and text[end : end + 1] == ")":
            # Swallow the whole ``[label](url)`` construct, not just the URL,
            # so no bracket debris is left around the anchor.
            start = markdown.start()
            end += 1
            label = markdown.group(1) or _link_label(url)
        else:
            label = _link_label(url)

        out.append(str(escape(text[cursor:start])))
        out.append(
            f'<a href="{escape(url)}" target="_blank" rel="noopener noreferrer">'
            f"{escape(label)}</a>"
        )
        cursor = end
    out.append(str(escape(text[cursor:])))
    return Markup("".join(out))


def _format_salary(listing: Listing) -> str:
    if listing.salary_min and listing.salary_max:
        return f"${listing.salary_min:,.0f}–{listing.salary_max:,.0f}"
    if listing.salary_min:
        return f"${listing.salary_min:,.0f}+"
    if listing.salary_max:
        return f"up to ${listing.salary_max:,.0f}"
    return "salary n/a"


def _get_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "jinja"]),
    )
    env.filters["band_label"] = _band_label
    env.filters["band_css"] = _band_css
    env.filters["format_salary"] = _format_salary
    env.filters["markdown"] = _render_markdown
    return env


_env = _get_env()


def _detail_stats(details: list[RunListingDetail]) -> dict:
    scored = len(details)
    return {
        "scored": scored,
        "strong": sum(1 for d in details if d.band == "strong_match"),
        "competitive": sum(1 for d in details if d.band == "competitive"),
        "reach": sum(1 for d in details if d.band == "reach"),
        "avg_score": round(sum(d.score for d in details) / scored) if scored else 0,
        "gaps": sum(len(d.gaps) for d in details),
    }


async def render_run(
    conn: asyncpg.Connection,
    run_id: int,
    settings: Settings,
) -> dict[str, Path]:
    run = await get_run(conn, run_id)
    details = await get_run_details(conn, run_id)
    prev_run, next_run = await get_adjacent_runs(conn, run.run_date)

    run_dir = Path(settings.report_output_dir) / str(run.run_date)
    run_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}

    dashboard_template = _env.get_template("dashboard.html.jinja")
    dashboard_html = dashboard_template.render(
        run=run,
        details=details,
        stats=_detail_stats(details),
        prev_run=prev_run,
        next_run=next_run,
        is_today=run.run_date == date.today(),
    )
    dashboard_path = run_dir / "dashboard.html"
    dashboard_path.write_text(dashboard_html, encoding="utf-8")
    paths["dashboard"] = dashboard_path

    job_detail_template = _env.get_template("job-detail.html.jinja")
    for detail in details:
        job_detail_html = job_detail_template.render(run=run, detail=detail)
        job_detail_path = run_dir / f"job-detail-{detail.run_listing_id}.html"
        job_detail_path.write_text(job_detail_html, encoding="utf-8")
        paths[f"job_detail_{detail.run_listing_id}"] = job_detail_path

    return paths


async def render_history(
    conn: asyncpg.Connection,
    settings: Settings,
    limit: int = 30,
) -> Path:
    summaries = await get_run_summaries(conn, limit)
    days = [{"run": summary.run, "stats": summary.stats} for summary in summaries]

    history_template = _env.get_template("history.html.jinja")
    history_html = history_template.render(days=days)

    output_dir = Path(settings.report_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    history_path = output_dir / "history.html"
    history_path.write_text(history_html, encoding="utf-8")
    return history_path


def render_profile(profile: Profile, settings: Settings) -> Path:
    profile_template = _env.get_template("profile.html.jinja")
    profile_html = profile_template.render(profile=profile)

    output_dir = Path(settings.report_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_path = output_dir / "profile.html"
    profile_path.write_text(profile_html, encoding="utf-8")
    return profile_path
