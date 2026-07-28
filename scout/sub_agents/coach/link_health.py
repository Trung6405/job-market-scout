from __future__ import annotations

import requests

from scout.config import Settings
from scout.shared.schemas import LinkCheck, LinkVerdict

_GONE_CODES = frozenset({404, 410})
# Bounds what lands in resources.last_check_error — a stack-trace-length
# message would bloat the column for no diagnostic benefit.
_MAX_REASON_LENGTH = 300


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
        head_response = requests.head(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return LinkCheck(verdict="transient", reason=_reason(exc))

    verdict = classify_status(head_response.status_code)
    if verdict == "healthy":
        return LinkCheck(verdict=verdict)

    try:
        get_response = requests.get(
            url, timeout=timeout, allow_redirects=True, stream=True
        )
    except requests.RequestException as exc:
        return LinkCheck(verdict="transient", reason=_reason(exc))

    get_response.close()
    get_verdict = classify_status(get_response.status_code)
    reason = None if get_verdict == "healthy" else f"HTTP {get_response.status_code}"
    return LinkCheck(verdict=get_verdict, reason=reason)
