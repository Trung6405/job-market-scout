from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineEvent:
    """One status line emitted by a pipeline stage.

    Replaces ADK's ``Event``. The pipeline never needed invocation ids,
    branches or multi-part content — only an author and a line of text
    for the entrypoint to log.
    """

    author: str
    text: str
