"""Audit how the job-detail pages actually render the Coach stage's tips.

Reproduces the end-to-end check that closed P4, and the measurement that
overturned one of its decisions. P4 originally capped how many citations a
page could link, leaving the rest as plain text. Every fixture-based test
passed. Re-rendering the real corpus showed the assumption underneath the cap
was wrong — most generated tips cite two or three resources, so the cap left
more than half of all citations as bare unclickable URLs sitting in prose
beside linked ones — and the cap was removed (see the 2026-07-28 amendment in
docs/agent/specs/career-coach-p4-report-surfacing/spec.md).

Keeping this runnable matters because that class of defect is invisible to the
test suite by construction: seeded tips are written by whoever writes the test,
so they carry the citation habits the author imagined rather than the ones the
model actually has. This reads what the model really produced.

Reads only — it renders into a temporary directory and never touches the
configured report output. Requires a database with stored tips; it reports and
exits cleanly if there are none rather than pretending an empty corpus passed.

Usage: python -m scripts.audit_rendered_citations
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path

from scout.config import settings as default_settings
from scout.shared.db import create_pool, list_runs
from scout.sub_agents.advisor.report import _iter_urls, render_run

_TIP_MARKUP = re.compile(r'<p class="tip">(.*?)</p>', re.S)
_ANCHOR = re.compile(r"<a [^>]*>.*?</a>", re.S)
_EMPTY_STATE = "No verified learning resources for these gaps yet"
_RETIRED_SECTION = "How to position your application"

# Matches rerender.py: every stored run, not a recent window.
_ALL_RUNS_LIMIT = 10_000


def _audit_page(html: str) -> dict[str, int]:
    """Count what one rendered job-detail page shows."""
    tips = _TIP_MARKUP.findall(html)
    return {
        "tips": len(tips),
        "linked": sum(tip.count("<a href=") for tip in tips),
        # A URL still visible after the anchors are removed is one the reader
        # can see but not follow — the defect this script exists to catch.
        "bare_urls": sum(len(re.findall(r"https?://", _ANCHOR.sub("", tip))) for tip in tips),
        "empty_state": int(_EMPTY_STATE in html),
        "retired_section": int(_RETIRED_SECTION in html),
    }


async def audit() -> int:
    pool = await create_pool(default_settings)
    try:
        async with pool.acquire() as conn:
            stored_tips = await conn.fetchval("SELECT count(*) FROM listing_tips")
            if not stored_tips:
                print("No tips stored — run the pipeline's Coach stage first.")
                return 1

            # Citations per tip as the model wrote them, before any rendering:
            # this is the distribution the removed cap was wrong about.
            per_tip = Counter(
                len({url for _s, _e, url in _iter_urls(row["tip"])})
                for row in await conn.fetch("SELECT tip FROM listing_tips")
            )

            with tempfile.TemporaryDirectory() as tmp:
                render_settings = replace(default_settings, report_output_dir=tmp)
                for run in await list_runs(conn, _ALL_RUNS_LIMIT):
                    await render_run(conn, run.id, render_settings)

                totals: Counter[str] = Counter()
                pages = list(Path(tmp).rglob("job-detail-*.html"))
                for page in pages:
                    totals.update(_audit_page(page.read_text(encoding="utf-8")))
    finally:
        await pool.close()

    multi = sum(count for cites, count in per_tip.items() if cites > 1)
    print(f"pages rendered        {len(pages)}")
    print(f"tips rendered         {totals['tips']} of {stored_tips} stored")
    print(f"citations linked      {totals['linked']}")
    print(f"bare unlinked URLs    {totals['bare_urls']}")
    print(f"empty-state pages     {totals['empty_state']}")
    print(f"pages with retired    {totals['retired_section']}")
    print(f"citations per tip     {dict(sorted(per_tip.items()))}")
    print(f"tips citing >1        {multi} of {stored_tips} ({round(multi * 100 / stored_tips)}%)")

    failures = []
    if totals["tips"] != stored_tips:
        failures.append(f"{stored_tips - totals['tips']} stored tip(s) did not render")
    if totals["bare_urls"]:
        failures.append(f"{totals['bare_urls']} citation(s) rendered as unclickable text")
    if totals["retired_section"]:
        failures.append(f"{totals['retired_section']} page(s) still show the retired section")
    for failure in failures:
        print(f"FAIL: {failure}")
    return 1 if failures else 0


def main() -> None:
    raise SystemExit(asyncio.run(audit()))


if __name__ == "__main__":
    main()
