"""Spike: does a byte-identical prompt prefix let the second call hit
DeepSeek's automatic prefix cache and reduce billed tokens?

Sends the same listings payload twice: once with the payload last, once
with it first so both calls share a long byte-identical prefix. Reads
response.usage for a cached/prompt split.

The shipped pipeline now places listings *last* (invariant instructions
and profile first) per docs/agent/specs/llm-call-efficiency/spec.md — this
spike remains a throwaway for later live measurement of the cache
reduction; it was not itself updated to match the new prompt shape.

Throwaway — not part of the shipped pipeline. See
docs/agent/plans/pipeline-efficiency/phase-1-model-layer.md Task 9.
"""

from __future__ import annotations

import asyncio
import json

import litellm

from scout.config import settings

# Large enough that a cache hit would be visible against typical minimum
# cacheable-prefix thresholds; small enough to run cheaply as a spike.
_LISTINGS_PAYLOAD = json.dumps(
    [
        {
            "source": "indeed",
            "external_id": str(i),
            "title": f"Backend Engineer {i}",
            "company": "Acme Corp",
            "location": "Melbourne VIC",
            "is_remote": False,
            "salary_min": None,
            "salary_max": None,
            "description": (
                "We are looking for a backend engineer with experience in "
                "Python, PostgreSQL, and distributed systems. " * 20
            ),
        }
        for i in range(15)
    ],
    indent=2,
)

_INSTRUCTIONS = (
    "You are a job-match scorer. Score each listing from 0 to 100 based on "
    "fit. Return a JSON object with a single key 'scores'."
)


def _print_usage(label: str, response) -> None:
    usage = getattr(response, "usage", None)
    print(f"--- {label} ---")
    print("usage:", usage)
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        print("prompt_tokens_details:", details)


async def _call(prompt: str, label: str) -> None:
    response = await litellm.acompletion(
        model=settings.deepseek_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
        api_key=settings.deepseek_api_key or None,
    )
    _print_usage(label, response)


_SCORER_SUFFIX = (
    "You are a job-match scorer. Score each listing from 0 to 100 based on "
    "fit. Return a JSON object with a single key 'scores'."
)
_EXTRACTOR_SUFFIX = (
    "You are a requirements extractor. Extract must_have and nice_to_have "
    "requirements from each listing. Return a JSON object with a single "
    "key 'requirements'."
)


async def main() -> None:
    listings_last = f"{_SCORER_SUFFIX}\n\nListings:\n{_LISTINGS_PAYLOAD}"
    listings_first = f"Listings:\n{_LISTINGS_PAYLOAD}\n\n{_SCORER_SUFFIX}"

    # Same full prompt twice, back to back: upper bound on what caching can do.
    await _call(listings_first, "identical prompt, call 1 (cold)")
    await _call(listings_first, "identical prompt, call 2 (should hit cache)")
    await _call(listings_last, "listings-last (today's shape, for comparison)")

    # The scenario that actually matters: Scorer and Extractor share the
    # listings-first prefix but differ in their trailing instructions, the
    # way the real pipeline's two calls would if reordered.
    scorer_prompt = f"Listings:\n{_LISTINGS_PAYLOAD}\n\n{_SCORER_SUFFIX}"
    extractor_prompt = f"Listings:\n{_LISTINGS_PAYLOAD}\n\n{_EXTRACTOR_SUFFIX}"
    await _call(scorer_prompt, "shared-prefix scorer call (primes cache)")
    await _call(
        extractor_prompt,
        "shared-prefix extractor call (different suffix, same listings prefix)",
    )


if __name__ == "__main__":
    asyncio.run(main())
