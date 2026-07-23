# Amendments to the Product Requirements Spec

> **Status:** Historical record of the v1.0 → v2.0 and v2.0 → v2.1 transitions.
> `product-requirements-spec.md` was updated in place at each step to
> incorporate these changes as current scope; this document keeps the
> deviation-by-deviation reasoning for why each change was made.

The original PRS (`product-requirements-spec.md`, v1.0) scoped a
four-stage pipeline — Scraper → Tracker → Scorer → Briefing — with match
scores explicitly *not* persisted (Decision D4). The `advisor-report`
initiative (`docs/agent/specs/advisor-report/spec.md`) added a fifth
stage and changed that decision. Each row below is a deviation from the
PRS as originally written, and why:

| PRS said (v1.0) | Now | Why |
|---|---|---|
| Four stages: Scraper → Tracker → Scorer → Briefing. | Six stages: adds **Advisor** and a **Persistence/Report** step between Scorer and Briefing. | A raw 0–100 score used once for the email and discarded (per D4) can't answer "why is this job a good/bad fit for me" or let a student browse past runs — that gap is the whole reason the `advisor-report` work exists (spec, "Problem"). |
| D4: match scores are **not persisted**; the `matches` table and `config_version` correlation are deferred. | Scores (and bands, and gaps) **are persisted**, in `runs` / `run_listings` / `listing_gaps` (`scout/shared/db.py`). | D4 was accepted on the explicit basis that "a persistence step can be added after the Scorer later without redesign" (PRS §5) — this is that step, and it's what makes `history.html` show real past runs instead of hardcoded samples. |
| Only a raw numeric score — no qualitative tiers. | Scores are also classified into a band (`strong_match` / `competitive` / `reach`) via `classify_band(score, settings)`. | A bare number reads as a fake percentage in the UI; a deterministic threshold function (reusing `min_match_score`, adding `strong_match_score`) is simpler and easier to test than an LLM doing the classification. |
| No requirement/skill-gap analysis — out of scope entirely. | A second LLM pass extracts must-have/nice-to-have requirements per listing; `evaluate_requirements(requirements, profile)` (in `scout/sub_agents/advisor/gaps.py`) checks each against the student's `profile.json` and flags the ones missing. | "Gap-first coaching" was the core feature of the `job-detail.html` mockup this initiative wires up — a score alone doesn't tell the student what to go learn. |
| §2.2/§8: no UI beyond the email; rendering deferred/out of scope. | Jinja2 templates render real HTML (dashboard, job-detail, history, profile) from persisted run data; the email gains a link to that day's report. | The `docs/project/prototypes/` mockups were static demos with hardcoded sample data — persisted scores/bands/gaps are dead weight with nothing to render them, so rendering was built in the same initiative instead of deferred again. |
| D2/D3: only the Tracker (deterministic code) writes to the DB; LLM stages produce content only. | **Unchanged.** Advisor's persistence writes happen in the deterministic pipeline layer, not inside its LLM-calling `agent.py`/`runner.py`. | Not revisited — the single-writer rule still holds, just extended to the new tables. |

## v2.0 → v2.1

Two more changes landed after v2.0: the pipeline's candidate data source was
consolidated, and the deployment work that v2.0 §7 still listed as
"Planned" (scheduler, cloud host, CI/CD) was actually built, plus a new
dashboard-hosting capability that wasn't scoped in v2.0 at all.

| PRS said (v2.0) | Now | Why |
|---|---|---|
| §1/FR-7/FR-14: scoring and the briefing read a configured **resume**; gap detection separately read `profile.json`. Two candidate artifacts. | `profile.json` is the **single, required** candidate source for scoring, the briefing, and gap detection (D8). `resume.txt`, its config field, Docker mount, and deploy/CI steps are removed. A missing/invalid profile fails fast at startup (FR-15). | The two representations drifted in production: `resume.txt` sat at a generic 3-line placeholder while `profile.json` held the real, detailed candidate data, so the Scorer graded every listing against the placeholder and rated them all "out of reach." See `docs/agent/specs/profile-candidate-source/spec.md`. |
| FR-10: gap detection is **skipped (with a status event) if no profile exists**. | Gap detection **always runs** — the profile is required, so the missing-profile branch no longer exists. | Direct consequence of the profile becoming required; the skip path had nothing left to guard against. |
| §7: Scheduler, Cloud host, and CI/CD are **Planned**, target described in a Draft appendix; §2.2 lists "automated scheduling and cloud deployment" as out of scope; runs are triggered manually. | All three are **Built**: GitHub Actions `scheduled-run.yml` cron-triggers the pipeline twice daily (05:00/11:00 Melbourne time), starts the Azure VM `scout-vm`, runs the pipeline over SSH, and deallocates the VM afterward; `infra-provision.yml` applies the Bicep infra; `deploy.yml` rsyncs app code to the VM. | This is standard infrastructure work that was simply completed after v2.0 was written — no scope decision was being reversed, the doc just hadn't caught up. |
| Not scoped in v2.0 at all. | The reports dashboard is published to an **Azure Storage static website** after each run (D9), so it stays reachable while the VM is deallocated (~23h/day, to control cost). | The VM's deallocate-when-idle cost strategy meant the dashboard was unreachable almost all the time under the original single-host plan; Static Web Apps was tried first but isn't offered in any region this subscription's policy allows, so a Storage static website was used instead (same ~$0 cost). See `docs/agent/plans/static-dashboard-hosting/plan.md`. |

## Where to go next

- Current pipeline shape and stage responsibilities: `docs/project/architecture-pipeline-overview.md`
- Stage-by-stage design rationale and requirements: `docs/agent/specs/<stage>/spec.md`
- Phased implementation history: `docs/agent/plans/<stage>/plan.md` (+ `phase-N.md`)
