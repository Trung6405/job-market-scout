# job-market-scout
Multi-agent job market scout, scrapes listings, matches them to a resume, tracks changes, and briefs daily

## Getting started

### Prerequisites
- Docker Desktop (running, with its socket available — `jobspy-mcp` shells
  out to `docker run` per search and mounts `/var/run/docker.sock`)
- A [DeepSeek API key](https://platform.deepseek.com/)
- A Gmail account with 2FA enabled, so you can generate an
  [app password](https://myaccount.google.com/apppasswords) (your regular
  Gmail password won't work for SMTP)

### Setup
1. Clone with submodules (the scraper vendors `jobspy-mcp-server`):
   ```
   git clone --recurse-submodules <repo-url>
   ```
   If you already cloned without `--recurse-submodules`, run:
   ```
   git submodule update --init --recursive
   ```
2. Copy the example config and fill in your own values:
   ```
   cp scout/.env.example scout/.env
   ```
   At minimum set `DEEPSEEK_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`,
   and `GMAIL_RECIPIENT`. Adjust `SEARCH_ROLES`, `SEARCH_LOCATIONS`,
   `PREFERRED_LOCATIONS`, `REMOTE_ONLY`, `MIN_SALARY`, and
   `MIN_MATCH_SCORE` to taste.
3. Copy the resume template and replace it with your own resume:
   ```
   cp scout/resume.txt.example scout/resume.txt
   ```
4. Run the pipeline:
   ```
   docker compose up --build
   ```
   This builds the app, the vendored `jobspy` scraper image, and the
   `jobspy-mcp` and `postgres` services, then runs one scrape → score →
   track → brief cycle via `python -m scout.main`. The Postgres schema is
   applied automatically on first run — no manual migration step needed.
   Matches above `MIN_MATCH_SCORE` are emailed to `GMAIL_RECIPIENT`.

### Running tests
```
pip install -r requirements.txt
pytest
```
