from __future__ import annotations

from scout.shared.schemas import LinkVerdict

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
