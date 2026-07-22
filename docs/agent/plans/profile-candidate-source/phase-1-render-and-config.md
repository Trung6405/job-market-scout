# Phase 1: Profile rendering + Settings ownership

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** nothing

---

## Goal

Add a pure `render_profile_text(profile)` renderer and load the profile into
`settings.profile` (fail-fast). Purely additive — `resume_text` stays for
now, so the whole suite remains green.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  No — reads a local JSON file already read elsewhere.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No.

---

## Tasks

### Task 1.1: Spike — confirm no circular import

- **Files:** none (verification only)
- **Gate:** none
- **Steps:**
  - [ ] Confirm `scout/shared/profile.py` imports only `scout.shared.schemas`
        (not `scout.config`), and that `scout/shared/schemas.py` does not
        import `scout.config`. Run: `python -c "import scout.shared.profile, scout.shared.schemas; print('ok')"`
  - [ ] Verify config can import the loader without a cycle. Run:
        `python -c "from scout.shared.profile import load_profile; import scout.config; print('ok')"`
        Expected: prints `ok` (no ImportError). If a cycle appears, move
        `load_profile` import inside `__post_init__` (local import) and note
        it here before continuing.

### Task 1.2: `render_profile_text` renderer

- **Files:** `scout/shared/profile.py`, `tests/test_profile_text.py`
- **Gate:** none
- **Interfaces:**
  - Produces: `render_profile_text(profile: Profile) -> str`
- **Steps:**
  - [ ] Write failing test in `tests/test_profile_text.py`:

    ```python
    from scout.shared.profile import render_profile_text
    from scout.shared.schemas import (
        Background, DomainKnowledge, Profile, Project, TechCategory, TechSkill,
    )


    def _profile() -> Profile:
        return Profile(
            name="Test Student",
            target_role="Junior Software Engineer",
            target_locations=["Sydney"],
            tech_stack=[
                TechCategory(
                    category="Languages",
                    skills=[TechSkill(name="Python", proficiency=4)],
                )
            ],
            domain_knowledge=[
                DomainKnowledge(name="Web", proficiency=60, description="APIs")
            ],
            background=Background(
                education="B.Sc. CS",
                experience="0.5 yrs",
                preferred_roles=["Software Engineer"],
                locations=["Sydney"],
            ),
            projects=[Project(title="Scout", description="job agent", tags=["Python"])],
        )


    def test_render_profile_text_maps_proficiency_to_words():
        text = render_profile_text(_profile())
        assert "Python (advanced)" in text
        assert "Target role: Junior Software Engineer" in text
        assert "Scout: job agent" in text
        assert "Web (Good)" in text
    ```

  - [ ] Verify it fails: `pytest tests/test_profile_text.py -v`
        Expected: FAIL (ImportError: cannot import name `render_profile_text`).
  - [ ] Implement in `scout/shared/profile.py` (append below `load_profile`):

    ```python
    _SKILL_LEVELS = {1: "beginner", 2: "basic", 3: "intermediate", 4: "advanced", 5: "expert"}


    def render_profile_text(profile: Profile) -> str:
        """Render a Profile into a readable resume-like block for LLM prompts."""
        lines: list[str] = [
            f"Name: {profile.name}",
            f"Target role: {profile.target_role}",
        ]
        if profile.target_locations:
            lines.append(f"Target locations: {', '.join(profile.target_locations)}")
        lines.append(f"Education: {profile.background.education}")
        lines.append(f"Experience: {profile.background.experience}")

        lines += ["", "Skills:"]
        for category in profile.tech_stack:
            skills = ", ".join(
                f"{s.name} ({_SKILL_LEVELS[s.proficiency]})" for s in category.skills
            )
            lines.append(f"- {category.category}: {skills}")

        if profile.domain_knowledge:
            lines += ["", "Domain knowledge:"]
            for dk in profile.domain_knowledge:
                lines.append(f"- {dk.name} ({dk.level}): {dk.description}")

        if profile.projects:
            lines += ["", "Projects:"]
            for project in profile.projects:
                tags = f" [{', '.join(project.tags)}]" if project.tags else ""
                lines.append(f"- {project.title}: {project.description}{tags}")

        return "\n".join(lines)
    ```

  - [ ] Verify it passes: `pytest tests/test_profile_text.py -v` → PASS
  - [ ] Commit: `git add scout/shared/profile.py tests/test_profile_text.py && git commit -m "feat(profile): add render_profile_text renderer"`

### Task 1.3: Load the profile into `Settings` (additive)

- **Files:** `scout/config.py`, `tests/test_config.py`
- **Gate:** none
- **Interfaces:**
  - Produces: `Settings().profile: Profile` (loaded from `profile_path`,
    raises `FileNotFoundError` if the file is absent)
- **Steps:**
  - [ ] Write failing test in `tests/test_config.py`:

    ```python
    import pytest
    from scout.config import Settings


    def test_settings_loads_profile_object():
        # Default PROFILE_PATH points at the committed scout/profile.json.
        settings = Settings()
        assert settings.profile.name  # a Profile object with a name

    def test_settings_missing_profile_raises(monkeypatch, tmp_path):
        monkeypatch.setenv("PROFILE_PATH", str(tmp_path / "nope.json"))
        with pytest.raises(FileNotFoundError):
            Settings()
    ```

  - [ ] Verify it fails: `pytest tests/test_config.py -k "loads_profile_object or missing_profile" -v`
        Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'profile'`).
  - [ ] Implement in `scout/config.py`:
    - Add imports near the top: `from scout.shared.profile import load_profile`
      and `from scout.shared.schemas import Profile`.
    - Add a field (leave `resume_path`/`resume_text` in place for now):
      `profile: Profile = field(init=False)`
    - Extend `__post_init__` to also set it:
      `object.__setattr__(self, "profile", load_profile(self.profile_path))`
  - [ ] Verify it passes: `pytest tests/test_config.py -v` → PASS
  - [ ] Commit: `git add scout/config.py tests/test_config.py && git commit -m "feat(config): load profile into Settings (additive)"`

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_profile_text.py tests/test_config.py -v`
- [ ] Full suite still green: `pytest`

## Rollback

Revert the two commits; `render_profile_text` and `settings.profile` are
additive, so nothing downstream depends on them yet.

---

## Notes / Learnings

<Filled in during execution.>
