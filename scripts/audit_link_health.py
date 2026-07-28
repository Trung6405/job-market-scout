"""Report the Coach corpus's link health without touching it.

Companion to `scripts/audit_rendered_citations.py`, for the same reason that
script exists: a stubbed test only proves the HTTP behaviour whoever wrote
the stub imagined, and what real hosts do to a `HEAD` request — anti-bot
403s, rate limiting, `HEAD`/`GET` disagreement — is exactly the class of
defect that class of test cannot see. This reads what the checker actually
recorded against the real corpus.

Read-only: it only ever `SELECT`s from `resources`. It never issues a link
check or writes a row, so it is safe to run against production at any time,
including between scheduled runs.

Usage: python -m scripts.audit_link_health
"""

from __future__ import annotations

import asyncio

from scout.config import settings as default_settings
from scout.shared.db import create_pool


def summarize(rows: list[dict]) -> dict[str, int]:
    """Turn resource rows into the health distribution the audit prints.

    `never_checked` and `failing` are both non-dead subsets of `live` —
    `live` is simply `total - dead`, so the three never need to add up to
    it. A resource killed by a `gone` verdict never had `last_verified` set
    (it was never a *successful* check), so `dead` is checked first and
    excludes a dead row from `never_checked` even though its `last_verified`
    is also NULL.
    """
    total = len(rows)
    dead = sum(1 for row in rows if row["dead_since"] is not None)
    never_checked = sum(
        1
        for row in rows
        if row["dead_since"] is None and row["last_verified"] is None
    )
    failing = sum(
        1
        for row in rows
        if row["dead_since"] is None and row["consecutive_failures"] > 0
    )
    return {
        "total": total,
        "live": total - dead,
        "dead": dead,
        "never_checked": never_checked,
        "failing": failing,
    }


async def audit() -> None:
    pool = await create_pool(default_settings)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT url, last_verified, dead_since, consecutive_failures, "
                "last_check_error FROM resources"
            )
    finally:
        await pool.close()

    if not rows:
        print("No resources in the corpus — nothing to audit.")
        return

    counts = summarize([dict(row) for row in rows])
    print(f"total resources        {counts['total']}")
    print(f"live                   {counts['live']}")
    print(f"dead                   {counts['dead']}")
    print(f"never checked          {counts['never_checked']}")
    print(f"failing (not yet dead) {counts['failing']}")

    dead_rows = [row for row in rows if row["dead_since"] is not None]
    if dead_rows:
        print("\ndead resources:")
        for row in dead_rows:
            print(
                f"  {row['url']}  dead_since={row['dead_since']}  "
                f"reason={row['last_check_error']}"
            )


def main() -> None:
    asyncio.run(audit())


if __name__ == "__main__":
    main()
