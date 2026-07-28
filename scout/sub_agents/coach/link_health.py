from __future__ import annotations

import asyncio
import logging
import time

import requests

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.db import create_pool, get_resources_to_check, record_link_check
from scout.shared.schemas import LinkCheck, LinkHealthSummary, LinkVerdict

logger = logging.getLogger("scout.coach.link_health")

_GONE_CODES = frozenset({404, 410})
# Bounds what lands in resources.last_check_error — a stack-trace-length
# message would bloat the column for no diagnostic benefit.
_MAX_REASON_LENGTH = 300
# Sequential, like the aggregator's GitHub Search throttle — the corpus is
# GitHub-heavy today, and this keeps one run from bursting requests at it.
_CHECK_THROTTLE_SECONDS = 1.0
# One keep-alive session for the whole batch — per-call requests.head/get
# would pay a fresh TCP+TLS handshake per request, including between the
# HEAD and its follow-up GET to the very same URL.
_session = requests.Session()


def classify_status(status_code: int) -> LinkVerdict:
    """Map an HTTP status code to a link-health verdict.

    Only 404/410 count as permanently `gone`. Everything else that isn't a
    clean success — including 401/403/405/429/5xx and any unrecognised
    code — is `transient`: hosts return 403 for anti-bot and rate-limit
    reasons far more often than because a resource is genuinely gone, and an
    unexpected status is not evidence of removal either. Only repeated
    transient failures should cost a resource its place in retrieval.
    """
    if status_code in _GONE_CODES:
        return "gone"
    if 200 <= status_code < 400:
        return "healthy"
    return "transient"


def _reason(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    return message[:_MAX_REASON_LENGTH]


def check_url(url: str, settings: Settings) -> LinkCheck:
    """Check whether `url` still resolves.

    `HEAD` is tried first since it costs nothing to download; any result
    that isn't `healthy` is re-checked with a streamed, body-unread `GET`,
    since some hosts answer `HEAD` differently (or refuse it) without the
    resource actually being gone. The `GET`'s verdict is authoritative.

    A network-level failure (timeout, DNS/connection error, redirect loop)
    at either step is never allowed to raise out of this function — it is
    exactly the kind of ambiguous, possibly-transient failure the verdict
    system exists to tolerate, so it is folded into `transient` like any
    other non-permanent failure.
    """
    timeout = settings.coach_link_health_timeout_seconds
    try:
        head_response = _session.head(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return LinkCheck(verdict="transient", reason=_reason(exc))

    verdict = classify_status(head_response.status_code)
    if verdict == "healthy":
        return LinkCheck(verdict=verdict)

    try:
        get_response = _session.get(
            url, timeout=timeout, allow_redirects=True, stream=True
        )
    except requests.RequestException as exc:
        return LinkCheck(verdict="transient", reason=_reason(exc))

    get_response.close()
    get_verdict = classify_status(get_response.status_code)
    reason = None if get_verdict == "healthy" else f"HTTP {get_response.status_code}"
    return LinkCheck(verdict=get_verdict, reason=reason)


def _throttled_check(url: str, settings: Settings, throttle: bool) -> LinkCheck:
    """Pace and run one check in a worker thread.

    Both the inter-request sleep and the blocking HTTP calls run off the
    event loop, so an open asyncpg pool keeps getting serviced while a slow
    host times out.
    """
    if throttle:
        time.sleep(_CHECK_THROTTLE_SECONDS)
    return check_url(url, settings)


async def run_link_health(settings: Settings | None = None) -> LinkHealthSummary:
    """Check the next batch of due resources and record each verdict.

    A single URL's check is never allowed to abandon the rest of the
    batch — ``check_url`` already folds network failures into a
    ``transient`` verdict, but this loop also guards against anything else
    going wrong for one row (an unexpected exception), converting it to the
    same ``transient`` verdict rather than losing every check queued after
    it. An empty batch is a valid, successful, zero-count run.
    """
    active_settings = settings or default_settings
    pool = await create_pool(active_settings)
    try:
        async with pool.acquire() as conn:
            batch = await get_resources_to_check(
                conn, active_settings.coach_link_health_batch
            )

            tally = {
                "verified": 0,
                "recovered": 0,
                "newly_dead": 0,
                "still_dead": 0,
                "failing": 0,
            }
            for index, row in enumerate(batch):
                try:
                    check = await asyncio.to_thread(
                        _throttled_check, row["url"], active_settings, index > 0
                    )
                except Exception as exc:  # noqa: BLE001 - one row must not sink the batch
                    check = LinkCheck(verdict="transient", reason=_reason(exc))

                transition = await record_link_check(
                    conn,
                    row["id"],
                    check.verdict,
                    check.reason,
                    active_settings.coach_link_health_max_failures,
                )
                tally[transition] += 1

            return LinkHealthSummary(checked=len(batch), **tally)
    finally:
        await pool.close()
