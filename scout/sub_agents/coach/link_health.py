from __future__ import annotations

import requests

from scout.config import Settings
from scout.shared.schemas import LinkCheck, LinkVerdict

_GONE_CODES = frozenset({404, 410})


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


def check_url(url: str, settings: Settings) -> LinkCheck:
    """Check whether `url` still resolves.

    `HEAD` is tried first since it costs nothing to download; any result
    that isn't `healthy` is re-checked with a streamed, body-unread `GET`,
    since some hosts answer `HEAD` differently (or refuse it) without the
    resource actually being gone. The `GET`'s verdict is authoritative.
    """
    timeout = settings.coach_link_health_timeout_seconds
    head_response = requests.head(url, timeout=timeout, allow_redirects=True)
    verdict = classify_status(head_response.status_code)
    if verdict == "healthy":
        return LinkCheck(verdict=verdict)

    get_response = requests.get(
        url, timeout=timeout, allow_redirects=True, stream=True
    )
    get_response.close()
    return LinkCheck(verdict=classify_status(get_response.status_code))
