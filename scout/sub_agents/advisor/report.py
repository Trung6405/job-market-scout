from __future__ import annotations

from pathlib import Path

import asyncpg
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from markupsafe import Markup

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
    has_profile: bool = False,
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
        has_profile=has_profile,
        prev_run=prev_run,
        next_run=next_run,
    )
    dashboard_path = run_dir / "dashboard.html"
    dashboard_path.write_text(dashboard_html, encoding="utf-8")
    paths["dashboard"] = dashboard_path

    job_detail_template = _env.get_template("job-detail.html.jinja")
    for detail in details:
        job_detail_html = job_detail_template.render(
            run=run, detail=detail, has_profile=has_profile
        )
        job_detail_path = run_dir / f"job-detail-{detail.run_listing_id}.html"
        job_detail_path.write_text(job_detail_html, encoding="utf-8")
        paths[f"job_detail_{detail.run_listing_id}"] = job_detail_path

    return paths


async def render_history(
    conn: asyncpg.Connection,
    settings: Settings,
    limit: int = 30,
    has_profile: bool = False,
) -> Path:
    summaries = await get_run_summaries(conn, limit)
    days = [{"run": summary.run, "stats": summary.stats} for summary in summaries]

    history_template = _env.get_template("history.html.jinja")
    history_html = history_template.render(days=days, has_profile=has_profile)

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
