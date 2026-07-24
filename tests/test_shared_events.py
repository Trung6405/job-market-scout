import dataclasses

import pytest

from scout.shared.events import PipelineEvent


def test_pipeline_event_carries_author_and_text():
    event = PipelineEvent(author="scout", text="Scraper: 3 listing(s) found")
    assert event.author == "scout"
    assert event.text == "Scraper: 3 listing(s) found"


def test_pipeline_event_is_frozen():
    event = PipelineEvent(author="scout", text="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.text = "y"
