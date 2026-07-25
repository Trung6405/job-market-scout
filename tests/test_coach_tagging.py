from __future__ import annotations

import pytest

from scout.config import Settings
from scout.shared.schemas import ResourceTags
from scout.sub_agents.coach.tagging import tag_readme


@pytest.mark.asyncio
async def test_tag_readme_returns_resource_tags(monkeypatch):
    expected = ResourceTags(
        skills=["kubernetes", "helm"],
        resource_type="repo",
        level="intermediate",
        summary="A Helm chart repository for Kubernetes deployments.",
    )
    captured_prompts: list[str] = []

    async def _fake_complete_json(prompt, schema, settings):
        captured_prompts.append(prompt)
        assert schema is ResourceTags
        return expected

    monkeypatch.setattr(
        "scout.sub_agents.coach.tagging.complete_json", _fake_complete_json
    )
    readme = "# Helm\n\nA package manager for Kubernetes."
    result = await tag_readme(readme, Settings())

    assert result == expected
    assert readme in captured_prompts[0]
