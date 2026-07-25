# Phase 2: Candidate gathering & tagging

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 1 complete (`Resource`/`ResourceTags` schemas,
> `github_pat`/`coach_top_n_per_skill`/`coach_awesome_lists` settings)

---

## Goal

Give Phase 3's runner four standalone, independently-testable building
blocks: `search_candidates`/`fetch_readme` (GitHub), `harvest_awesome_list`
(bootstrap), `tag_readme` (LLM tagging), and `embed` (local embedding).
Each is tested with its external dependency (`requests`, `complete_json`,
`SentenceTransformer`) mocked — no live network or model download in this
phase's test run.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — `github_search.py` makes authenticated `requests` calls to the
  GitHub REST/Search API using `settings.github_pat`. Failure handling:
  `response.raise_for_status()` surfaces non-2xx errors to the caller
  (Phase 3's runner decides whether to let one skill's failure abort the
  whole run — see Phase 3); a 404 on the README endpoint is treated as
  "no README" (not an error), matching the spec's has-a-README filter.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Yes — `sentence-transformers` (pulls in `torch`) is added to
  `requirements.txt` in this phase's Task 4, since that's the first task
  that imports it. Already flagged and pre-accepted in `plan.md` → Key
  Decisions (umbrella PRS D-CC-4); no additional gate here.

---

## Tasks

### Task 1: `github_search.py` — search + README fetch

- **Files:**
  - Create: `scout/sub_agents/coach/__init__.py` (empty)
  - Create: `scout/sub_agents/coach/github_search.py`
  - Test: `tests/test_coach_github_search.py`
- **Gate:** none.
- **Interfaces:**
  - Consumes: `Settings.github_pat`, `Settings.coach_top_n_per_skill`
    (Phase 1).
  - Produces: `search_candidates(skill: str, settings: Settings) ->
    list[str]` (repo URLs, filtered by stars/archived via the search query
    itself and by pushed-within-18-months client-side, capped at
    `coach_top_n_per_skill`) and `fetch_readme(repo_url: str, settings:
    Settings) -> str | None` (`None` on a 404, i.e. no README). Phase 2's
    `bootstrap.py` (Task 2) and Phase 3's `runner.py` rely on exactly these
    two names and signatures.

- [ ] **Step 1: Write the failing test**

Create `tests/test_coach_github_search.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests

from scout.config import Settings
from scout.sub_agents.coach.github_search import fetch_readme, search_candidates


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def _settings(**overrides) -> Settings:
    return Settings(github_pat="test-pat", **overrides)


def _repo(name: str, days_old: int) -> dict:
    pushed_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    return {
        "html_url": f"https://github.com/org/{name}",
        "pushed_at": pushed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def test_search_candidates_filters_stale_repos(monkeypatch):
    items = [_repo("fresh", days_old=30), _repo("stale", days_old=600)]
    monkeypatch.setattr(
        "scout.sub_agents.coach.github_search.requests.get",
        lambda *a, **k: _FakeResponse(json_data={"items": items}),
    )
    candidates = search_candidates("kubernetes", _settings())
    assert candidates == ["https://github.com/org/fresh"]


def test_search_candidates_caps_at_top_n(monkeypatch):
    items = [_repo(f"repo{i}", days_old=1) for i in range(10)]
    monkeypatch.setattr(
        "scout.sub_agents.coach.github_search.requests.get",
        lambda *a, **k: _FakeResponse(json_data={"items": items}),
    )
    candidates = search_candidates("kubernetes", _settings(coach_top_n_per_skill=3))
    assert len(candidates) == 3


def test_search_candidates_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        "scout.sub_agents.coach.github_search.requests.get",
        lambda *a, **k: _FakeResponse(status_code=403),
    )
    with pytest.raises(requests.HTTPError):
        search_candidates("kubernetes", _settings())


def test_fetch_readme_returns_text(monkeypatch):
    monkeypatch.setattr(
        "scout.sub_agents.coach.github_search.requests.get",
        lambda *a, **k: _FakeResponse(text="# Kubernetes\n\nContainer orchestration."),
    )
    readme = fetch_readme("https://github.com/kubernetes/kubernetes", _settings())
    assert readme == "# Kubernetes\n\nContainer orchestration."


def test_fetch_readme_returns_none_on_404(monkeypatch):
    monkeypatch.setattr(
        "scout.sub_agents.coach.github_search.requests.get",
        lambda *a, **k: _FakeResponse(status_code=404),
    )
    readme = fetch_readme("https://github.com/no/readme", _settings())
    assert readme is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_github_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named
'scout.sub_agents.coach.github_search'`.

- [ ] **Step 3: Write minimal implementation**

Create `scout/sub_agents/coach/__init__.py` (empty file).

Create `scout/sub_agents/coach/github_search.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from scout.config import Settings

_SEARCH_URL = "https://api.github.com/search/repositories"
# The Search API has no relative-date query operator, so "pushed within
# ~18 months" (spec) is filtered client-side against this cutoff.
_STALE_AFTER = timedelta(days=548)


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"token {settings.github_pat}",
        "Accept": "application/vnd.github+json",
    }


def search_candidates(skill: str, settings: Settings) -> list[str]:
    """Return up to `coach_top_n_per_skill` candidate repo URLs for `skill`."""
    response = requests.get(
        _SEARCH_URL,
        headers=_headers(settings),
        params={
            "q": f"{skill} in:readme,description stars:>200 archived:false",
            "sort": "stars",
            "order": "desc",
            "per_page": 30,
        },
        timeout=10,
    )
    response.raise_for_status()
    cutoff = datetime.now(timezone.utc) - _STALE_AFTER
    candidates: list[str] = []
    for repo in response.json().get("items", []):
        if len(candidates) >= settings.coach_top_n_per_skill:
            break
        pushed_at = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
        if pushed_at < cutoff:
            continue
        candidates.append(repo["html_url"])
    return candidates


def fetch_readme(repo_url: str, settings: Settings) -> str | None:
    """Fetch a repo's README as plain text, or None if it has none.

    Doubles as the "has a README" filter (a 404 here means "drop this
    candidate") and as the text tagging.py tags — one fetch per surviving
    candidate, not two.
    """
    owner_repo = repo_url.removeprefix("https://github.com/").rstrip("/")
    response = requests.get(
        f"https://api.github.com/repos/{owner_repo}/readme",
        headers={**_headers(settings), "Accept": "application/vnd.github.raw+json"},
        timeout=10,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_github_search.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scout/sub_agents/coach/__init__.py scout/sub_agents/coach/github_search.py \
        tests/test_coach_github_search.py
git commit -m "feat(coach): add GitHub search and README fetch

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 2: `bootstrap.py` — awesome-list link harvesting

- **Files:**
  - Create: `scout/sub_agents/coach/bootstrap.py`
  - Test: `tests/test_coach_bootstrap.py`
- **Gate:** none.
- **Interfaces:**
  - Consumes: `fetch_readme` (Task 1).
  - Produces: `harvest_awesome_list(list_url: str, settings: Settings) ->
    list[str]` (distinct repo URLs linked from the list's README, in
    first-seen order, excluding a self-link back to `list_url`). Phase 3's
    `runner.py` relies on this name/signature.

- [ ] **Step 1: Write the failing test**

Create `tests/test_coach_bootstrap.py`:

```python
from __future__ import annotations

from scout.config import Settings
from scout.sub_agents.coach.bootstrap import harvest_awesome_list


def _settings() -> Settings:
    return Settings(github_pat="test-pat")


def test_harvest_awesome_list_extracts_repo_links(monkeypatch):
    readme = """
# Awesome Python

- [Django](https://github.com/django/django) - A web framework.
- [Flask](https://github.com/pallets/flask) - A microframework.
- Self-reference: [this list](https://github.com/vinta/awesome-python)
"""
    monkeypatch.setattr(
        "scout.sub_agents.coach.bootstrap.fetch_readme",
        lambda list_url, settings: readme,
    )
    candidates = harvest_awesome_list(
        "https://github.com/vinta/awesome-python", _settings()
    )
    assert candidates == [
        "https://github.com/django/django",
        "https://github.com/pallets/flask",
    ]


def test_harvest_awesome_list_dedupes_repeated_links(monkeypatch):
    readme = (
        "[Django](https://github.com/django/django) "
        "and again [Django](https://github.com/django/django)"
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.bootstrap.fetch_readme",
        lambda list_url, settings: readme,
    )
    candidates = harvest_awesome_list(
        "https://github.com/vinta/awesome-python", _settings()
    )
    assert candidates == ["https://github.com/django/django"]


def test_harvest_awesome_list_returns_empty_when_no_readme(monkeypatch):
    monkeypatch.setattr(
        "scout.sub_agents.coach.bootstrap.fetch_readme",
        lambda list_url, settings: None,
    )
    candidates = harvest_awesome_list("https://github.com/dead/list", _settings())
    assert candidates == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_bootstrap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named
'scout.sub_agents.coach.bootstrap'`.

- [ ] **Step 3: Write minimal implementation**

Create `scout/sub_agents/coach/bootstrap.py`:

```python
from __future__ import annotations

import re

from scout.config import Settings
from scout.sub_agents.coach.github_search import fetch_readme

# Matches a bare github.com/owner/repo URL as it appears inside markdown
# link syntax `[text](url)` or as a raw link, stopping at the first
# character that can't be part of a repo path segment.
_GITHUB_LINK_RE = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:[)\s#>\]]|$)")


def harvest_awesome_list(list_url: str, settings: Settings) -> list[str]:
    """Extract distinct repo URLs linked from an awesome-list's README."""
    readme = fetch_readme(list_url, settings)
    if readme is None:
        return []
    seen: set[str] = set()
    candidates: list[str] = []
    for owner, repo in _GITHUB_LINK_RE.findall(readme):
        url = f"https://github.com/{owner}/{repo}"
        if url == list_url or url in seen:
            continue
        seen.add(url)
        candidates.append(url)
    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_bootstrap.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add scout/sub_agents/coach/bootstrap.py tests/test_coach_bootstrap.py
git commit -m "feat(coach): add awesome-list bootstrap harvesting

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 3: `tagging.py` — LLM README tagging

- **Files:**
  - Create: `scout/sub_agents/coach/tagging.py`
  - Modify: `scout/prompts.py`
  - Test: `tests/test_coach_tagging.py`
- **Gate:** none.
- **Interfaces:**
  - Consumes: `complete_json(prompt, schema, settings)`
    (`scout/shared/llm.py`, unchanged), `ResourceTags` (Phase 1).
  - Produces: `tag_readme(readme_text: str, settings: Settings) ->
    ResourceTags` and `build_coach_tagging_instruction(readme_text: str) ->
    str` (`scout/prompts.py`, following the existing
    `build_scorer_instruction`/`build_requirements_instruction`
    convention). Phase 3's `runner.py` relies on `tag_readme`'s
    name/signature.

- [ ] **Step 1: Write the failing test**

Create `tests/test_coach_tagging.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_tagging.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named
'scout.sub_agents.coach.tagging'`.

- [ ] **Step 3: Write minimal implementation**

In `scout/prompts.py`, append:

```python
def build_coach_tagging_instruction(readme_text: str) -> str:
    return f"""\
You are the resource tagger for Job Market Scout's Career Coach.

Read the README below and identify:
- "skills": the specific technical skills, tools, frameworks, or
  languages this repository is about or teaches (e.g. ["kubernetes",
  "helm"]). Use canonical names — no version numbers or punctuation
  decoration.
- "resource_type": always "repo" for a GitHub repository README.
- "level": the intended audience level, exactly one of "beginner",
  "intermediate", or "advanced", if the README states or clearly implies
  one, else null.
- "summary": one sentence (max ~30 words) describing what this
  repository is and why it is useful to learn from.

Only use what the README actually says. Do not invent skills not
evidenced in the text, and do not call any tool.

Return a JSON object with exactly these four keys: "skills" (list of
strings), "resource_type" (string), "level" (string or null), "summary"
(string). Return only the JSON object, no commentary.

README:
{readme_text[:4000]}
"""
```

Create `scout/sub_agents/coach/tagging.py`:

```python
from __future__ import annotations

from scout.config import Settings
from scout.prompts import build_coach_tagging_instruction
from scout.shared.llm import complete_json
from scout.shared.schemas import ResourceTags


async def tag_readme(readme_text: str, settings: Settings) -> ResourceTags:
    return await complete_json(
        build_coach_tagging_instruction(readme_text),
        ResourceTags,
        settings,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_tagging.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add scout/prompts.py scout/sub_agents/coach/tagging.py tests/test_coach_tagging.py
git commit -m "feat(coach): add LLM README tagging pass

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 4: `embeddings.py` — local summary embedding

- **Files:**
  - Create: `scout/sub_agents/coach/embeddings.py`
  - Modify: `requirements.txt` (add `sentence-transformers`)
  - Test: `tests/test_coach_embeddings.py`
- **Gate:** none — the dependency addition is a Key Decision already
  recorded in `plan.md`, not a fresh decision requiring sign-off here.
- **Interfaces:**
  - Produces: `embed(text: str) -> list[float]` (a 384-dim vector, from a
    lazily-initialized module-level `SentenceTransformer` singleton).
    Phase 3's `runner.py` relies on this name/signature and the 384
    dimensionality (matches `resources.embedding VECTOR(384)`, P0).

- [ ] **Step 1: Write the failing test**

Create `tests/test_coach_embeddings.py`:

```python
from __future__ import annotations

from scout.sub_agents.coach import embeddings


class _FakeEncoded:
    def __init__(self, values: list[float]):
        self._values = values

    def tolist(self) -> list[float]:
        return self._values


class _FakeModel:
    instances = 0

    def __init__(self, name: str):
        _FakeModel.instances += 1
        self.name = name

    def encode(self, text: str, normalize_embeddings: bool = True):
        return _FakeEncoded([0.1] * 384)


def test_embed_returns_384_dim_list(monkeypatch):
    _FakeModel.instances = 0
    embeddings._model = None
    monkeypatch.setattr(embeddings, "SentenceTransformer", _FakeModel)
    result = embeddings.embed("a summary")
    assert len(result) == 384
    assert all(isinstance(x, float) for x in result)


def test_embed_loads_model_once(monkeypatch):
    _FakeModel.instances = 0
    embeddings._model = None
    monkeypatch.setattr(embeddings, "SentenceTransformer", _FakeModel)
    embeddings.embed("first")
    embeddings.embed("second")
    assert _FakeModel.instances == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_embeddings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named
'scout.sub_agents.coach.embeddings'`.

- [ ] **Step 3: Write minimal implementation**

In `requirements.txt`, add a new line (alphabetical position, between
`rpds-py==2026.6.3` and `shellingham==1.5.4`):

```
sentence-transformers==3.3.1
```

Then: `pip install -r requirements.txt` to install it locally before running
the test.

Create `scout/sub_agents/coach/embeddings.py`:

```python
from __future__ import annotations

from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def embed(text: str) -> list[float]:
    return _get_model().encode(text, normalize_embeddings=True).tolist()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_embeddings.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add requirements.txt scout/sub_agents/coach/embeddings.py \
        tests/test_coach_embeddings.py
git commit -m "feat(coach): add local sentence-transformers embedding

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_coach_github_search.py tests/test_coach_bootstrap.py tests/test_coach_tagging.py tests/test_coach_embeddings.py -v`
- [ ] Full regression: `pytest` (no existing test regresses; confirms the
  new `sentence-transformers` dependency doesn't break collection/imports
  elsewhere).

## Rollback

Revert the four feat commits. `github_search.py`/`bootstrap.py`/
`tagging.py`/`embeddings.py` have no caller yet outside their own tests
(Phase 3 wires them up), so reverting any subset is safe. If only the
dependency needs undoing without the code, drop the `sentence-transformers`
line from `requirements.txt` and `pip uninstall sentence-transformers`.

---

## Notes / Learnings

<Filled in during execution.>
