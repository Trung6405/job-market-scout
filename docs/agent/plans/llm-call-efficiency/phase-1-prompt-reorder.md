# Phase 1: Invariant-first prompt reorder

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing

---

## Goal

Restructure `build_scorer_instruction` and `build_requirements_instruction`
so their invariant content (role, rules/rubric, profile for the Scorer,
return-format) leads and the per-batch `Listings:` block trails, making the
invariant block a cacheable shared prefix. Confirmed by tests asserting the
listings come last and the Extractor stays profile-blind.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No — pure prompt-string construction; the model consumes the output.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No.

---

## Tasks

### Task 1: Reorder both prompts, listings last

- **Files:** `scout/prompts.py`, `tests/test_prompts.py`
- **Gate:** none
- **Steps:**
  - [x] Update the shared-prefix test to assert the *new* order. Replace
        `test_scorer_and_requirements_instructions_share_a_listings_prefix`
        with an intent-matching test, e.g.:
    ```python
    def test_scorer_and_requirements_put_listings_last(listing_factory):
        """Invariant instructions lead so the rubric+profile form a cacheable
        prefix across batches and days; the variable listings JSON trails."""
        settings = Settings()
        listings = [listing_factory()]

        scorer = build_scorer_instruction(settings, listings)
        requirements = build_requirements_instruction(settings, listings)

        for instruction in (scorer, requirements):
            assert not instruction.startswith("Listings:\n")
            listings_idx = instruction.index("Listings:\n")
            # Nothing but the listings JSON follows the "Listings:" label.
            head, tail = instruction.split("Listings:\n", 1)
            assert head.strip()  # invariant content precedes the listings
            assert tail.strip()  # the JSON block is present and non-empty
        # Scorer's invariant prefix carries the rubric + profile.
        assert scorer.index("Candidate profile:") < scorer.index("Listings:\n")
        assert scorer.index("90-100") < scorer.index("Listings:\n")
    ```
  - [x] Verify it fails (`pytest tests/test_prompts.py::test_scorer_and_requirements_put_listings_last -v`) — expect FAIL (prompts still start with `Listings:`).
  - [x] Reorder `build_scorer_instruction`: emit the role line, rubric,
        `Candidate profile:\n{render_profile_text(...)}`, the
        `Return a JSON object ...` instruction, then finally
        `{_listings_block(settings, listings)}` as the last block. Change the
        rubric's "For each listing above" to "For each listing in the
        Listings block below".
  - [x] Reorder `build_requirements_instruction` the same way: role,
        extraction rules, `Return a JSON object ...`, then
        `{_listings_block(...)}` last; flip "For each listing above" to
        "below".
  - [x] Rewrite the `_listings_block` docstring: it is now the *trailing
        variable suffix*, not a shared leading prefix; the cacheable prefix
        is the invariant instruction+profile ahead of it.
  - [x] Verify the reorder test passes and the untouched prompt tests still
        pass (`pytest tests/test_prompts.py -v`) — expect PASS, including
        `test_scorer_instruction_keeps_profile_and_rubric`,
        `test_scorer_instruction_omits_preferences`, and
        `test_requirements_instruction_never_includes_the_profile`.
  - [x] Commit: `refactor(prompts): put invariant instructions first, listings last for prefix cache`

### Task 2: Update the spike comment

- **Files:** `scripts/spike_prefix_cache.py`
- **Gate:** none
- **Steps:**
  - [x] Update the module docstring's "today's prompt shape" note: the
        pipeline now places listings *last* (invariant-first); the spike
        remains a throwaway for later live measurement.
  - [x] No test — comment-only. Confirm nothing imports it
        (`pytest tests/test_prompts.py -q` still green as a sanity check).
  - [x] Commit: `docs(spike): note pipeline now uses invariant-first prompts`

---

## Verification

- [x] Phase tests pass: `pytest tests/test_prompts.py -v`
- [x] Manual (optional): print `build_scorer_instruction(Settings(), [<one listing>])` and confirm the profile and rubric appear before `Listings:`.

## Rollback

Revert the two commits; the prompt builders return to listings-first. No
state involved.

---

## Notes / Learnings

Went exactly to plan. All 9 tests in `test_prompts.py` passed after the
reorder with no further adjustment needed.
