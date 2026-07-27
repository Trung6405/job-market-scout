# Phase 3: Generation Stage & Wiring

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 1 complete (`GroundedTip`, `record_listing_tips`),
> Phase 2 complete (`validate_grounding`), and P2's `retrieve_for_skills` on the
> branch this one is based on.

---

## Goal

Generate one tip per covered gap — one LLM call per listing, resources
retrieved once for the whole run — validate every tip against its own gap's
allowlist, and write the survivors inside the pipeline's run transaction. Done
when a real run fills `listing_tips` and logs its grounding violations, with
the job-detail template still untouched.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — this phase makes the LLM call. Failure handling is explicit: a listing
  with no retrieved resources is never called (Task 3), and a call that fails
  or returns unparseable JSON is logged and skipped by `run_batches` without
  failing the run. The model's output is untrusted and passes through Phase 2's
  validator before anything is stored (Task 4). No new secret is introduced —
  the existing DeepSeek key is reused.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. New `Settings` fields all carry defaults; no new dependency.

---

## Tasks

### Task 1: Tip-generation settings

- **Files:** `scout/config.py`, `scout/.env.example`, `tests/test_coach_config.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: both settings default, and both read their env var.

    ```python
    # append to tests/test_coach_config.py
    def test_coach_tips_settings_default():
        settings = Settings()
        assert settings.coach_tips_resources_per_gap == 3
        assert settings.coach_tips_max_gaps_per_listing == 5


    def test_coach_tips_settings_read_env(monkeypatch):
        monkeypatch.setenv("COACH_TIPS_RESOURCES_PER_GAP", "2")
        monkeypatch.setenv("COACH_TIPS_MAX_GAPS_PER_LISTING", "8")
        settings = Settings()
        assert settings.coach_tips_resources_per_gap == 2
        assert settings.coach_tips_max_gaps_per_listing == 8
    ```

  - [ ] Verify it fails (`pytest tests/test_coach_config.py -v`) — expected:
        `AttributeError: 'Settings' object has no attribute 'coach_tips_resources_per_gap'`
  - [ ] Implement: add both fields to `Settings` in `scout/config.py`, next to
        the existing `coach_top_k` / `coach_resource_max_age_days` fields.

    ```python
    #: Resources injected into the prompt per gap. Kept separate from
    #: ``coach_top_k`` so the prompt's size can be tuned without changing what
    #: the retriever returns to any other caller.
    coach_tips_resources_per_gap: int = field(
        default_factory=partial(_env_int, "COACH_TIPS_RESOURCES_PER_GAP", 3)
    )
    #: Gaps tipped per listing, must-haves first. Bounds prompt size on a
    #: listing that states twenty requirements the profile doesn't meet.
    coach_tips_max_gaps_per_listing: int = field(
        default_factory=partial(_env_int, "COACH_TIPS_MAX_GAPS_PER_LISTING", 5)
    )
    ```

  - [ ] Add both to `scout/.env.example` with their defaults, following the
        format of the existing `COACH_TOP_K` entry.
  - [ ] Verify it passes (`pytest tests/test_coach_config.py -v`)
  - [ ] Commit: `feat(coach): add tip-generation settings`

### Task 2: Generated-tip schemas and the prompt

- **Files:** `scout/shared/schemas.py`, `scout/prompts.py`,
  `tests/test_coach_tips_prompt.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: the prompt names every gap and every resource URL
        given, instructs the model to cite only those, and puts the variable
        JSON last (the prefix-cache convention from the llm-call-efficiency
        spec).

    ```python
    # tests/test_coach_tips_prompt.py
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
    ```

  - [ ] Verify it fails (`pytest tests/test_coach_tips_prompt.py -v`) —
        expected: `ImportError: cannot import name 'build_coach_tips_instruction'`
  - [ ] Implement the schemas in `scout/shared/schemas.py`, next to
        `GroundedTip`.

    ```python
    class GeneratedTip(BaseModel):
        """One tip as the model returned it — untrusted until validated.

        Deliberately distinct from `GroundedTip`: nothing constructs a
        `GroundedTip` except the validator, so an unvalidated tip cannot be
        passed to `record_listing_tips` by mistake.
        """

        gap_skill: str
        tip: str


    class GeneratedTips(BaseModel):
        tips: list[GeneratedTip]
    ```

  - [ ] Implement the prompt in `scout/prompts.py`, below
        `build_coach_tagging_instruction`.

    ```python
    def build_coach_tips_instruction(
        listing: Listing, resources_by_skill: dict[str, list[RetrievedResource]]
    ) -> str:
        gaps_json = json.dumps(
            {
                "role": listing.title,
                "company": listing.company,
                "gaps": [
                    {
                        "skill": skill,
                        "resources": [
                            {
                                "title": resource.title,
                                "url": str(resource.url),
                                "summary": resource.summary,
                                "type": resource.resource_type,
                            }
                            for resource in resources
                        ],
                    }
                    for skill, resources in resources_by_skill.items()
                ],
            },
            indent=2,
        )
        return f"""\
    You are the career coach for Job Market Scout. For each skill gap below,
    write one short, practical tip (2-3 sentences) telling the candidate how to
    start closing that gap using the learning resources provided for it.

    Rules:
    - Reference ONLY the resources listed under that same skill. Do not cite a
      resource listed under a different skill, and do not invent any URL,
      repository, book, or course that is not in the list.
    - Include the URL of at least one resource you reference, written in full.
    - Copy each "skill" value exactly as given — it is how the tip is matched
      back to the gap.
    - Be concrete about what to do with the resource, not just that it exists.
    - Do not call any tool.

    Return a JSON object with one key, "tips": a list of objects, each with
    "skill" (copied exactly) and "tip" (the text). Return only the JSON object,
    no commentary.

    Skill gaps and their resources:
    {gaps_json}
    """
    ```

    Add `RetrievedResource` to the `scout.shared.schemas` import at the top of
    `prompts.py`.

    Note the prompt says `"skill"` while `GeneratedTip` declares `gap_skill`;
    give the field an alias so the model's key maps cleanly:

    ```python
    class GeneratedTip(BaseModel):
        gap_skill: str = Field(alias="skill")
        tip: str

        model_config = ConfigDict(populate_by_name=True)
    ```

    Import `Field` and `ConfigDict` from `pydantic` in `schemas.py` if not
    already imported.

  - [ ] Verify it passes (`pytest tests/test_coach_tips_prompt.py -v`)
  - [ ] Commit: `feat(coach): add grounded-tip schemas and prompt`

### Task 3: Generation stage — retrieve once, one call per listing

- **Files:** `scout/sub_agents/coach/tips.py`, `tests/test_coach_tips.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: retrieval happens once for the union of gap skills;
        a listing whose gaps retrieve nothing is never sent to the model; only
        unmet skill-kind gaps are tipped; must-haves win the per-listing cap;
        every supplied match comes back, tipped or not.

    ```python
    # tests/test_coach_tips.py
    from __future__ import annotations

    import pytest

    from scout.config import Settings
    from scout.shared.schemas import (
        GeneratedTip,
        GeneratedTips,
        RetrievedResource,
        SkillGap,
    )
    from scout.sub_agents.coach import tips as tips_module

    pytestmark = pytest.mark.asyncio


    def _resource(url: str) -> RetrievedResource:
        return RetrievedResource(
            url=url,
            title="examples",
            resource_type="repo",
            skills=["kubernetes"],
            summary="Worked examples.",
            similarity=0.9,
        )


    @pytest.fixture
    def stub_llm(monkeypatch):
        """Record prompts and reply with one tip per requested skill."""
        calls = []

        async def _complete_json(prompt, schema, settings, **kwargs):
            calls.append(prompt)
            skills = [
                skill for skill in ("Kubernetes", "Terraform") if skill in prompt
            ]
            return GeneratedTips(
                tips=[
                    GeneratedTip(
                        gap_skill=skill,
                        tip=f"Start with https://github.com/k/examples for {skill}.",
                    )
                    for skill in skills
                ]
            )

        monkeypatch.setattr(tips_module, "complete_json", _complete_json)
        return calls


    @pytest.fixture
    def stub_retriever(monkeypatch):
        """Record retrieval calls; cover Kubernetes only."""
        calls = []

        async def _retrieve(conn, skills, settings=None, k=None):
            calls.append(list(skills))
            return {
                skill: (
                    [_resource("https://github.com/k/examples")]
                    if skill == "Kubernetes"
                    else []
                )
                for skill in skills
            }

        monkeypatch.setattr(tips_module, "retrieve_for_skills", _retrieve)
        return calls


    async def test_retrieval_runs_once_for_the_whole_run(
        stub_llm, stub_retriever, match_factory, listing_factory
    ):
        first = match_factory(listing=listing_factory(external_id="a"))
        second = match_factory(listing=listing_factory(external_id="b"))
        gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

        await tips_module.run_grounded_tips(
            None, [(first, [gap]), (second, [gap])], Settings()
        )

        assert len(stub_retriever) == 1
        assert len(stub_llm) == 2  # one call per listing


    async def test_listing_without_coverage_is_never_sent_to_the_model(
        stub_llm, stub_retriever, match_factory, listing_factory
    ):
        match = match_factory(listing=listing_factory(external_id="a"))
        gap = SkillGap(skill="Terraform", requirement_level="must_have", met=False)

        result = await tips_module.run_grounded_tips(None, [(match, [gap])], Settings())

        assert stub_llm == []
        assert result == [(match, [])]


    async def test_only_unmet_skill_gaps_are_tipped(
        stub_llm, stub_retriever, match_factory, listing_factory
    ):
        match = match_factory(listing=listing_factory(external_id="a"))
        checks = [
            SkillGap(skill="Kubernetes", requirement_level="must_have", met=False),
            SkillGap(skill="Terraform", requirement_level="must_have", met=True),
            SkillGap(
                skill="Bachelor's degree",
                requirement_level="must_have",
                met=False,
                kind="education",
            ),
        ]

        await tips_module.run_grounded_tips(None, [(match, checks)], Settings())

        assert stub_retriever == [["Kubernetes"]]


    async def test_must_have_gaps_win_the_per_listing_cap(
        stub_llm, stub_retriever, monkeypatch, match_factory, listing_factory
    ):
        # Settings is a frozen dataclass — build a capped one from the
        # environment rather than mutating an instance.
        monkeypatch.setenv("COACH_TIPS_MAX_GAPS_PER_LISTING", "1")
        match = match_factory(listing=listing_factory(external_id="a"))
        checks = [
            SkillGap(skill="Terraform", requirement_level="nice_to_have", met=False),
            SkillGap(skill="Kubernetes", requirement_level="must_have", met=False),
        ]

        await tips_module.run_grounded_tips(None, [(match, checks)], Settings())

        assert stub_retriever == [["Kubernetes"]]


    async def test_failed_call_skips_only_its_listing(
        stub_retriever, monkeypatch, match_factory, listing_factory
    ):
        async def _boom(prompt, schema, settings, **kwargs):
            if "listing-b" in prompt:
                raise ValueError("model returned no content")
            return GeneratedTips(
                tips=[
                    GeneratedTip(
                        gap_skill="Kubernetes",
                        tip="Read https://github.com/k/examples.",
                    )
                ]
            )

        monkeypatch.setattr(tips_module, "complete_json", _boom)
        good = match_factory(listing=listing_factory(external_id="a", title="listing-a"))
        bad = match_factory(listing=listing_factory(external_id="b", title="listing-b"))
        gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

        result = await tips_module.run_grounded_tips(
            None, [(good, [gap]), (bad, [gap])], Settings()
        )

        by_id = {m.listing.external_id: tips for m, tips in result}
        assert len(by_id["a"]) == 1
        assert by_id["b"] == []
    ```

  - [ ] Verify it fails (`pytest tests/test_coach_tips.py -v`) — expected:
        `ModuleNotFoundError: No module named 'scout.sub_agents.coach.tips'`
  - [ ] Implement `scout/sub_agents/coach/tips.py`. This task leaves
        `_to_grounded_tips` a thin pass-through; Task 4 replaces it with the
        validating version.

    ```python
    from __future__ import annotations

    import logging

    import asyncpg

    from scout.config import Settings
    from scout.config import settings as default_settings
    from scout.prompts import build_coach_tips_instruction
    from scout.shared.batching import batches, run_batches
    from scout.shared.llm import complete_json
    from scout.shared.schemas import (
        GeneratedTips,
        GroundedTip,
        MatchResult,
        RetrievedResource,
        SkillGap,
    )
    from scout.sub_agents.coach.retriever import retrieve_for_skills

    logger = logging.getLogger(__name__)


    def _tippable_gaps(checks: list[SkillGap], limit: int) -> list[SkillGap]:
        """Unmet skill gaps only, must-haves first, capped.

        Mirrors ``get_run_details``' definition of a gap: non-skill kinds pass
        through ``evaluate_requirements`` as met by construction, and the
        corpus holds nothing for a degree or a years-of-experience bar anyway.
        """
        gaps = [check for check in checks if check.kind == "skill" and not check.met]
        gaps.sort(key=lambda gap: gap.requirement_level != "must_have")
        return gaps[:limit]


    def _to_grounded_tips(
        match: MatchResult,
        resources_by_skill: dict[str, list[RetrievedResource]],
        generated: GeneratedTips,
    ) -> list[GroundedTip]:
        # Replaced by the validating implementation in Task 4.
        return [
            GroundedTip(gap_skill=item.gap_skill, tip=item.tip, cited_urls=[])
            for item in generated.tips
        ]


    async def run_grounded_tips(
        conn: asyncpg.Connection,
        gaps_by_match: list[tuple[MatchResult, list[SkillGap]]],
        settings: Settings | None = None,
    ) -> list[tuple[MatchResult, list[GroundedTip]]]:
        """Generate validated coaching tips for a run's listings.

        Returns an entry for **every** supplied match, with an empty list where
        nothing was generated — a listing with no corpus coverage, a failed
        call, or a reply whose tips were all ungrounded. Callers need the empty
        entries: ``record_listing_tips`` uses them to clear stale rows from an
        earlier run on the same day.
        """
        active_settings = settings or default_settings
        work = [
            (
                match,
                _tippable_gaps(checks, active_settings.coach_tips_max_gaps_per_listing),
            )
            for match, checks in gaps_by_match
        ]
        work = [(match, gaps) for match, gaps in work if gaps]
        if not work:
            return [(match, []) for match, _checks in gaps_by_match]

        # One retrieval for the whole run: the retriever dedupes and embeds
        # each distinct skill once, so a skill that is a gap on twenty
        # listings costs one embedding, not twenty.
        all_skills = [gap.skill for _match, gaps in work for gap in gaps]
        retrieved = await retrieve_for_skills(
            conn,
            all_skills,
            active_settings,
            k=active_settings.coach_tips_resources_per_gap,
        )

        callable_work: list[tuple[MatchResult, dict[str, list[RetrievedResource]]]] = []
        for match, gaps in work:
            covered = {
                gap.skill: retrieved.get(gap.skill, [])
                for gap in gaps
                if retrieved.get(gap.skill)
            }
            if covered:
                callable_work.append((match, covered))
            else:
                logger.info(
                    "coach tips: no corpus coverage for %s/%s, skipping",
                    match.listing.source,
                    match.listing.external_id,
                )

        async def _call(
            batch: list[tuple[MatchResult, dict[str, list[RetrievedResource]]]],
        ) -> list[tuple[MatchResult, list[GroundedTip]]]:
            match, covered = batch[0]
            generated = await complete_json(
                build_coach_tips_instruction(match.listing, covered),
                GeneratedTips,
                active_settings,
            )
            return [(match, _to_grounded_tips(match, covered, generated))]

        # Size-1 batches: one call per listing, with run_batches' existing
        # concurrency limit and skip-on-failure. A single-item batch that
        # fails is skipped directly rather than retried, which is what we
        # want — a listing's tips are not worth a second call.
        results = await run_batches(
            batches(callable_work, 1),
            _call,
            concurrency=active_settings.model_concurrency,
            label="coach tips",
        )

        tips_by_key = {
            (match.listing.source, match.listing.external_id): tips
            for match, tips in results
        }
        return [
            (
                match,
                tips_by_key.get(
                    (match.listing.source, match.listing.external_id), []
                ),
            )
            for match, _checks in gaps_by_match
        ]
    ```

  - [ ] Verify it passes (`pytest tests/test_coach_tips.py -v`)
  - [ ] Commit: `feat(coach): generate coaching tips per listing`

### Task 4: Validate every tip before it becomes a `GroundedTip`

- **Files:** `scout/sub_agents/coach/tips.py`, `tests/test_coach_tips.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a fabricated URL is stripped and logged; a URL
        retrieved for a *different* gap on the same listing is stripped; a tip
        left citing nothing is dropped; a tip for a skill that was never
        requested is dropped.

    ```python
    # append to tests/test_coach_tips.py
    import logging


    def _reply(*pairs):
        async def _complete_json(prompt, schema, settings, **kwargs):
            return GeneratedTips(
                tips=[GeneratedTip(gap_skill=skill, tip=tip) for skill, tip in pairs]
            )

        return _complete_json


    async def test_fabricated_url_is_stripped_and_logged(
        stub_retriever, monkeypatch, caplog, match_factory, listing_factory
    ):
        monkeypatch.setattr(
            tips_module,
            "complete_json",
            _reply(
                (
                    "Kubernetes",
                    "Read https://kubernetes.io/invented and "
                    "https://github.com/k/examples.",
                )
            ),
        )
        match = match_factory(listing=listing_factory(external_id="a"))
        gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

        with caplog.at_level(logging.WARNING):
            result = await tips_module.run_grounded_tips(
                None, [(match, [gap])], Settings()
            )

        tip = result[0][1][0]
        assert "invented" not in tip.tip
        assert tip.cited_urls == ["https://github.com/k/examples"]
        assert "https://kubernetes.io/invented" in caplog.text


    async def test_tip_left_citing_nothing_is_dropped(
        stub_retriever, monkeypatch, match_factory, listing_factory
    ):
        monkeypatch.setattr(
            tips_module,
            "complete_json",
            _reply(("Kubernetes", "Just read https://kubernetes.io/invented.")),
        )
        match = match_factory(listing=listing_factory(external_id="a"))
        gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

        result = await tips_module.run_grounded_tips(None, [(match, [gap])], Settings())

        assert result == [(match, [])]


    async def test_tip_for_unrequested_skill_is_dropped(
        stub_retriever, monkeypatch, match_factory, listing_factory
    ):
        monkeypatch.setattr(
            tips_module,
            "complete_json",
            _reply(("Rust", "Learn Rust at https://github.com/k/examples.")),
        )
        match = match_factory(listing=listing_factory(external_id="a"))
        gap = SkillGap(skill="Kubernetes", requirement_level="must_have", met=False)

        result = await tips_module.run_grounded_tips(None, [(match, [gap])], Settings())

        assert result == [(match, [])]


    async def test_cross_gap_url_is_stripped(
        monkeypatch, match_factory, listing_factory
    ):
        """Both gaps' resources share one prompt, so a real URL cited under the
        wrong skill is the cheapest hallucination available — and the one a
        per-listing allowlist would miss."""

        async def _retrieve(conn, skills, settings=None, k=None):
            return {
                "Kubernetes": [_resource("https://github.com/k/examples")],
                "Terraform": [_resource("https://github.com/t/modules")],
            }

        monkeypatch.setattr(tips_module, "retrieve_for_skills", _retrieve)
        monkeypatch.setattr(
            tips_module,
            "complete_json",
            _reply(
                (
                    "Kubernetes",
                    "Start with https://github.com/t/modules and "
                    "https://github.com/k/examples.",
                )
            ),
        )
        match = match_factory(listing=listing_factory(external_id="a"))
        gaps = [
            SkillGap(skill="Kubernetes", requirement_level="must_have", met=False),
            SkillGap(skill="Terraform", requirement_level="must_have", met=False),
        ]

        result = await tips_module.run_grounded_tips(None, [(match, gaps)], Settings())

        tip = result[0][1][0]
        assert tip.cited_urls == ["https://github.com/k/examples"]
        assert "t/modules" not in tip.tip
    ```

  - [ ] Verify it fails (`pytest tests/test_coach_tips.py -v`) — expected:
        `AssertionError` on `tip.cited_urls` (the Task 3 pass-through returns
        `cited_urls=[]` and never strips)
  - [ ] Implement: replace `_to_grounded_tips` in `tips.py` and import the
        validator.

    ```python
    from scout.sub_agents.coach.grounding import validate_grounding
    ```

    ```python
    def _to_grounded_tips(
        match: MatchResult,
        resources_by_skill: dict[str, list[RetrievedResource]],
        generated: GeneratedTips,
    ) -> list[GroundedTip]:
        """Validate the model's reply into storable tips.

        Three ways a tip dies here, all silent to the run: it names a skill
        that was never asked about, every URL it cites is fabricated, or it
        cites nothing at all. Uncited prose is exactly the static-template
        advice this stage replaces, so it is not worth storing.
        """
        grounded: list[GroundedTip] = []
        for item in generated.tips:
            allowed = resources_by_skill.get(item.gap_skill)
            if allowed is None:
                logger.warning(
                    "coach tips: %s/%s returned a tip for unrequested skill %r, dropping",
                    match.listing.source,
                    match.listing.external_id,
                    item.gap_skill,
                )
                continue

            result = validate_grounding(item.tip, [str(r.url) for r in allowed])
            for url in result.stripped_urls:
                logger.warning(
                    "coach tips: grounding violation on %s/%s skill=%r url=%s",
                    match.listing.source,
                    match.listing.external_id,
                    item.gap_skill,
                    url,
                )
            if not result.cited_urls:
                logger.info(
                    "coach tips: dropping uncited tip for %s/%s skill=%r",
                    match.listing.source,
                    match.listing.external_id,
                    item.gap_skill,
                )
                continue

            grounded.append(
                GroundedTip(
                    gap_skill=item.gap_skill,
                    tip=result.text,
                    cited_urls=result.cited_urls,
                )
            )
        return grounded
    ```

  - [ ] Verify it passes (`pytest tests/test_coach_tips.py -v`)
  - [ ] Commit: `feat(coach): enforce grounding before storing tips`

### Task 5: Wire the stage into the pipeline

- **Files:** `scout/agent.py`, `tests/test_agent.py`,
  `docs/project/architecture-pipeline-overview.md`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: the generated tips reach `record_listing_tips`,
        the run reports them as a pipeline event, and generation happens
        **before** the transaction opens — the LLM call must not hold a
        transaction open for minutes.

    Follow `test_scout_pipeline_agent_renders_report_after_persisting_run`'s
    structure exactly: this file fakes the whole DB layer with
    `monkeypatch.setattr("scout.agent.<name>", ...)` and a `_FakeTransaction`,
    rather than using the `db_pool` fixture. Copy its existing
    scraper/tracker/scorer/requirements/render fakes; the new parts are below.

    ```python
    # append to tests/test_agent.py
    async def test_scout_pipeline_agent_persists_grounded_tips(monkeypatch):
        from scout.agent import ScoutPipelineAgent
        from scout.shared.schemas import GroundedTip

        # ... copy the existing fakes from
        # test_scout_pipeline_agent_renders_report_after_persisting_run ...

        call_order: list[str] = []
        recorded: list[tuple] = []

        async def _fake_run_grounded_tips(conn, gaps_by_match, settings=None):
            call_order.append("generate")
            return [
                (
                    match,
                    [
                        GroundedTip(
                            gap_skill="Kubernetes",
                            tip="Start with https://github.com/k/examples.",
                            cited_urls=["https://github.com/k/examples"],
                        )
                    ],
                )
                for match, _checks in gaps_by_match
            ]

        async def _fake_record_listing_tips(conn, run_id, tips_by_match):
            call_order.append("record")
            recorded.append((run_id, tips_by_match))

        class _RecordingTransaction(_FakeTransaction):
            async def __aenter__(self):
                call_order.append("transaction-open")
                return None

        monkeypatch.setattr(
            "scout.agent.run_grounded_tips", _fake_run_grounded_tips
        )
        monkeypatch.setattr(
            "scout.agent.record_listing_tips", _fake_record_listing_tips
        )
        # ... plus the rest of the existing setattr block, with the fake
        # connection's transaction() returning _RecordingTransaction() ...

        events = [event async for event in ScoutPipelineAgent().run()]

        # Generation is outside the transaction: it makes LLM calls that take
        # minutes, and agent.py holds a connection only around persistence.
        assert call_order.index("generate") < call_order.index("transaction-open")
        assert call_order.index("transaction-open") < call_order.index("record")

        _run_id, tips_by_match = recorded[0]
        assert tips_by_match[0][1][0].cited_urls == [
            "https://github.com/k/examples"
        ]
        assert any("Coach:" in event.text for event in events)
    ```

    (`PipelineEvent` is `(author, text)` — see `scout/shared/events.py`.)

  - [ ] Verify it fails (`pytest tests/test_agent.py::test_scout_pipeline_agent_persists_grounded_tips -v`)
        — expected: `AttributeError: <module 'scout.agent'> has no attribute 'run_grounded_tips'`
  - [ ] Implement in `scout/agent.py`. Generation goes **before** the run
        transaction is opened — it makes LLM calls that take minutes, and
        `agent.py`'s existing comment is explicit that the connection is only
        held around actual persistence. Only the cheap local write goes inside.

    Imports:

    ```python
    from scout.shared.db import (
        create_pool,
        finish_run,
        get_adjacent_runs,
        record_listing_gaps,
        record_listing_meta,
        record_listing_tips,
        record_run_listings,
        start_run,
    )
    from scout.sub_agents.coach.tips import run_grounded_tips
    ```

    After the `Gaps detected:` event and before the run-transaction block:

    ```python
            # Retrieval reads only the corpus, which no part of this run
            # writes, so it takes its own short-lived connection rather than
            # extending the run transaction across minutes of LLM calls.
            async with pool.acquire() as conn:
                tips_by_match = await run_grounded_tips(
                    conn, checks_by_match, settings
                )
            tipped = sum(1 for _match, tips in tips_by_match if tips)
            tip_count = sum(len(tips) for _match, tips in tips_by_match)
            yield PipelineEvent(
                self.name,
                f"Coach: {tip_count} grounded tip(s) across {tipped} listing(s)",
            )
    ```

    Inside the existing `async with conn.transaction():` block, directly after
    `record_listing_gaps`:

    ```python
                    await record_listing_tips(conn, run_id, tips_by_match)
    ```

  - [ ] Verify it passes (`pytest tests/test_agent.py -v`)
  - [ ] Update `docs/project/architecture-pipeline-overview.md`: add the
        grounded-tip stage and the `listing_tips` table to the pipeline
        description, noting that nothing renders tips until P4.
  - [ ] Commit: `feat(coach): wire the grounded-tip stage into the pipeline`
        (include the docs update and the plan/phase status ticks in this same
        commit)

---

## Verification

- [ ] All phase tests pass:
      `pytest tests/test_coach_tips.py tests/test_coach_tips_prompt.py tests/test_coach_config.py tests/test_agent.py -v`
- [ ] Full suite, no regression: `pytest -q`
- [ ] Manual: run the pipeline against the dev database with a populated
      corpus. Confirm `SELECT count(*) FROM listing_tips;` is non-zero, that
      every `cited_urls` entry also appears in `SELECT url FROM resources`, and
      that the `Coach:` pipeline event reports a plausible count.

    ```sql
    -- must return zero rows: any cited URL absent from the corpus
    SELECT t.gap_skill, u.url
    FROM listing_tips t, unnest(t.cited_urls) AS u(url)
    WHERE NOT EXISTS (SELECT 1 FROM resources r WHERE r.url = u.url);
    ```

    (A trailing-slash difference is a legitimate near-miss here — the
    validator compares canonically while storing the URL as written. Check any
    row this returns against `canonical_url` before treating it as a failure.)
- [ ] Manual: run `python -m scout.rerender` for that date and confirm no LLM
      call is made and the tips are unchanged.

## Observability

- `Coach: N grounded tip(s) across M listing(s)` — the per-run pipeline event.
- `coach tips: grounding violation on <source>/<id> skill=... url=...` —
  WARNING, one per stripped URL. A rising count across runs means the prompt is
  drifting; a count of zero for many runs means the allowlist is doing its job
  quietly.
- `coach tips: no corpus coverage for <source>/<id>, skipping` — INFO. Frequent
  occurrences mean the corpus (P1) needs broader skill coverage, not that this
  stage is broken.
- `coach tips: dropping uncited tip ... skill=...` — INFO.
- `coach tips batch of 1 item(s) failed, skipping: ...` — WARNING from
  `run_batches`, one per failed listing.

## Rollback

Revert the phase's five commits. Phases 1 and 2 leave no active behaviour
behind: `listing_tips` simply stops being written, `get_run_details` returns
empty tip lists, and the pipeline returns to its pre-P3 sequence. No stored
data outside `listing_tips` is touched.

---

## Notes / Learnings

<Filled in during execution.>
