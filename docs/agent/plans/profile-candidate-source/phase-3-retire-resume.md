# Phase 3: Retire resume.txt across infra

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 2 complete (nothing reads `resume_text` anymore)

---

## Goal

Delete `resume_text`/`resume_path` from config, remove the resume files and
their Docker/CI/deploy plumbing, and clean the last `resume_text` test
references. Suite stays green; `profile.json` (committed) is the only
candidate artifact.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — edits the deploy workflow (removes the resume render step and its
  secret usage). No behavioural change beyond dropping the resume.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. (The `RESUME_TEXT`/`RESUME_PATH` GitHub secrets are left in place;
  optionally deleted by the human later.)

---

## Tasks

### Task 3.1: Remove `resume_text`/`resume_path` from config + tests

- **Files:** `scout/config.py`, `tests/test_config.py`, `tests/test_advisor_requirements.py`
- **Gate:** none
- **Steps:**
  - [ ] Delete the resume-only tests in `tests/test_config.py`:
        `test_settings_reads_resume_text_from_default_resume_path` (lines ~80–97,
        including the custom-`RESUME_PATH` variant) and
        `test_settings_raises_when_resume_path_missing` (lines ~104–105). Remove
        the `"RESUME_PATH"` entry at line ~62 from whichever env-list test holds it.
  - [ ] In `tests/test_advisor_requirements.py`, update
        `test_build_requirements_instruction_does_not_include_resume` (line ~137):
        rename to `..._does_not_include_profile` and replace line ~143
        `assert settings.resume_text not in instruction` with:

    ```python
    from scout.shared.profile import render_profile_text
    assert render_profile_text(settings.profile) not in instruction
    ```

  - [ ] In `scout/config.py`, remove: `_DEFAULT_RESUME_PATH` (line ~12),
        `_read_resume_text` (lines ~14–17), the `resume_path` field (lines ~84–85),
        the `resume_text` field (line ~135), and the `resume_text` assignment in
        `__post_init__` (line ~138). Leave the Phase 1 `profile` field and its
        `__post_init__` assignment intact.
  - [ ] Verify green: `pytest tests/test_config.py tests/test_advisor_requirements.py -v`
        Expected: PASS. Then `grep -rn "resume_text\|resume_path\|_read_resume\|_DEFAULT_RESUME_PATH" scout/`
        Expected: no matches.
  - [ ] Commit: `git add scout/config.py tests/test_config.py tests/test_advisor_requirements.py && git commit -m "refactor(config): drop resume_text; profile is the only candidate source"`

### Task 3.2: Delete resume files, compose mount, and env example

- **Files:** `scout/resume.txt`, `scout/resume.txt.example`,
  `docker-compose.yaml`, `scout/.env.example`
- **Gate:** none
- **Steps:**
  - [ ] Delete `scout/resume.txt` and `scout/resume.txt.example`:
        `git rm scout/resume.txt scout/resume.txt.example`
  - [ ] In `docker-compose.yaml`, remove the resume bind mount (line ~18):
        `- ./scout/resume.txt:/app/scout/resume.txt:ro`
  - [ ] In `scout/.env.example`, remove the `RESUME_PATH=scout/resume.txt` line (line ~9).
  - [ ] Verify config still constructs (profile.json is committed):
        `python -c "from scout.config import Settings; Settings(); print('ok')"`
        Expected: prints `ok`. Then `grep -rn "resume" docker-compose.yaml scout/.env.example`
        Expected: no matches.
  - [ ] Commit: `git add -A && git commit -m "chore: remove resume.txt file, mount, and env example"`

### Task 3.3: Remove resume steps from the deploy workflow

- **Files:** `.github/workflows/deploy.yml`
- **Gate:** none
- **Steps:**
  - [ ] In the `test` job, delete the `Provide resume placeholder for tests`
        step (`cp scout/resume.txt.example scout/resume.txt`). CI now relies on
        the committed `scout/profile.json`.
  - [ ] In the `deploy` job, delete the entire `Render resume.txt on VM` step
        (the one that pipes `RESUME_TEXT` to `$APP_DIR/scout/resume.txt`).
  - [ ] In the `Render .env on VM` step, remove the `RESUME_PATH:
        ${{ secrets.RESUME_PATH }}` env mapping and the `RESUME_PATH=${RESUME_PATH}`
        line inside the heredoc.
  - [ ] Verify the workflow YAML parses:
        `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('ok')"`
        Expected: prints `ok`. Then `grep -ni "resume" .github/workflows/deploy.yml`
        Expected: no matches.
  - [ ] Commit: `git add .github/workflows/deploy.yml && git commit -m "ci: drop resume placeholder and render steps"`

---

## Verification

- [ ] Full suite green: `pytest`
- [ ] No `resume` references remain in code/infra:
      `grep -rni "resume" scout/ docker-compose.yaml .github/workflows/deploy.yml`
      returns nothing (test_schemas.py's `"...resume experience"` reasoning
      string is prose, not a reference — leave it).
- [ ] Manual (post-merge, after deploy): the VM run persists gaps and the
      dashboard shows a spread of scores driven by the real profile.

## Rollback

Revert this phase's commits; `git revert` restores the resume files and the
workflow steps. Config's `resume_text` removal is reverted with them.

---

## Notes / Learnings

<Filled in during execution.>
