from __future__ import annotations

from scout.prompts import build_coach_tips_instruction
from scout.shared.schemas import RetrievedResource


def _resource(url: str, title: str) -> RetrievedResource:
    return RetrievedResource(
        url=url,
        title=title,
        resource_type="repo",
        skills=["kubernetes"],
        summary="Worked examples of core objects.",
        similarity=0.82,
    )


def test_prompt_includes_every_gap_and_resource(listing_factory):
    prompt = build_coach_tips_instruction(
        listing_factory(title="Platform Engineer"),
        {
            "Kubernetes": [_resource("https://github.com/k/examples", "k/examples")],
            "Terraform": [_resource("https://github.com/t/modules", "t/modules")],
        },
    )
    assert "Kubernetes" in prompt
    assert "Terraform" in prompt
    assert "https://github.com/k/examples" in prompt
    assert "https://github.com/t/modules" in prompt
    assert "Platform Engineer" in prompt


def test_prompt_forbids_uncited_resources(listing_factory):
    prompt = build_coach_tips_instruction(
        listing_factory(),
        {"Kubernetes": [_resource("https://github.com/k/examples", "k/examples")]},
    )
    assert "only" in prompt.lower()
    assert "invent" in prompt.lower()


def test_prompt_puts_variable_json_last(listing_factory):
    """Invariant instructions first so DeepSeek's automatic prefix cache
    can key on them — same rule as the Scorer and Extractor prompts."""
    prompt = build_coach_tips_instruction(
        listing_factory(),
        {"Kubernetes": [_resource("https://github.com/k/examples", "k/examples")]},
    )
    assert prompt.rstrip().endswith("}") or prompt.rstrip().endswith("]")
