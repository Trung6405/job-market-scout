# Project instructions

## Worklog — automated, do not maintain by hand

The daily worklog is generated automatically at 9pm (Australia/Sydney) by a
scheduled cloud routine, which reads that day's pushed commits and writes
`YYYY-MM-DD.md` to the private `Trung6405/job-market-scout-worklog` repo.

Do NOT create or update `docs/project/worklog/` as part of committing here.
That directory is gitignored and personal; anything written there locally
stays local and is not the source of truth.

If a commit's reasoning matters for the worklog, put it in the commit
message — the routine only has git history to work from.
