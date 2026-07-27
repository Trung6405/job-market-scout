from __future__ import annotations

import pytest
from pydantic import ValidationError

from scout.shared.schemas import RetrievedResource, Resource, ResourceTags


def test_resource_accepts_minimal_fields():
    resource = Resource(
        url="https://github.com/kubernetes/kubernetes",
        title="kubernetes/kubernetes",
        resource_type="repo",
        skills=["kubernetes"],
        source="github",
    )
    assert resource.level is None
    assert resource.summary is None
    assert str(resource.url) == "https://github.com/kubernetes/kubernetes"


def test_resource_rejects_invalid_resource_type():
    with pytest.raises(ValidationError):
        Resource(
            url="https://github.com/kubernetes/kubernetes",
            title="kubernetes/kubernetes",
            resource_type="video",
            skills=["kubernetes"],
            source="github",
        )


def test_resource_tags_accepts_minimal_fields():
    tags = ResourceTags(
        skills=["kubernetes", "helm"],
        resource_type="repo",
        summary="A Helm chart repository for Kubernetes deployments.",
    )
    assert tags.level is None


def test_resource_tags_rejects_invalid_level():
    with pytest.raises(ValidationError):
        ResourceTags(
            skills=["kubernetes"],
            resource_type="repo",
            level="guru",
            summary="A Helm chart repository.",
        )


def test_retrieved_resource_carries_similarity():
    retrieved = RetrievedResource(
        url="https://github.com/kubernetes/kubernetes",
        title="kubernetes/kubernetes",
        resource_type="repo",
        skills=["kubernetes"],
        summary="Container orchestration platform.",
        similarity=0.87,
    )
    assert retrieved.similarity == 0.87
    assert retrieved.level is None


def test_retrieved_resource_requires_similarity():
    """A result without a score can't be told apart from a marginal match."""
    with pytest.raises(ValidationError):
        RetrievedResource(
            url="https://github.com/kubernetes/kubernetes",
            title="kubernetes/kubernetes",
            resource_type="repo",
            skills=["kubernetes"],
            summary="Container orchestration platform.",
        )
