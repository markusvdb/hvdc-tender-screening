# HVDC tender screening

Automated screening of HVDC-related tenders from:

- **Find a Tender (UK)** — OCDS JSON API
- **TED (EU)** — Search API v3

## What this does

- **Every morning at 06:00 UTC**, a GitHub Actions job fetches new notices from both APIs, scores them against the keyword tiers in `config.yaml`, and updates the dashboard.
- **Dashboard** is a static HTML page served by GitHub Pages at `https://<your-username>.github.io/<repo-name>/`. Bookmark it. It shows this week's matches plus a rolling archive of the last 90 days.
- **Every Monday at 06:00 UTC**, a second job emails a weekly digest to your configured address summarising the last 7 days.

## One-time setup (~20 minutes in the browser)

1. **Fork/create the repo** on GitHub.

2. **Add repository secrets** (Settings → Secrets and variables → Actions → New repository secret):

   | Secret | What it is |
   |--------|------------|
   | `ANTHROPIC_API_KEY` | From https://console.anthropic.com — for the summariser |
   | `SMTP_HOST` | e.g. `smtp.office365.com`, `smtp.gmail.com` |
   | `SMTP_PORT` | Usually `587` |
   | `SMTP_USER` | Your email address |
   | `SMTP_PASSWORD` | Email password or app password (required for 2FA accounts) |
   | `EMAIL_TO` | Where the Monday digest is sent |
   | `EMAIL_FROM` | Usually same as `SMTP_USER` |

3. **Enable GitHub Pages**: Settings → Pages → Source: "Deploy from a branch" → Branch: `main` → Folder: `/docs`.

4. **Tune `config.yaml`** — the keywords, CPV codes, and watchlist projects are pre-filled for the scopes you chose (converter stations, interconnectors, consulting, studies/R&D). Edit as you like.

5. **Trigger the first run manually**: Actions tab → "Daily screening" → Run workflow. Verify the dashboard appears at your Pages URL.

## What you'll edit regularly

Just `config.yaml`. Add a keyword, commit the change in the browser — tomorrow's run picks it up.

## Files

```
hvdc-tender-screening/
├── config.yaml                    # Keywords, CPV codes, watchlist. THE file you edit.
├── requirements.txt
├── .github/workflows/
│   ├── daily.yml                  # Runs every day 06:00 UTC, updates dashboard
│   └── weekly.yml                 # Runs Mondays 06:00 UTC, sends digest email
├── scripts/
│   ├── fetch_fts.py               # Find a Tender client
│   ├── fetch_ted.py               # TED client
│   ├── screen.py                  # Keyword scoring
│   ├── summarise.py               # LLM summaries via Anthropic API
│   ├── render_dashboard.py        # Build docs/index.html
│   ├── render_email.py            # Build weekly email HTML
│   ├── send_email.py              # SMTP delivery
│   ├── run_daily.py               # Orchestrator for daily job
│   └── run_weekly.py              # Orchestrator for Monday digest
├── templates/
│   ├── dashboard.html.j2
│   └── email.html.j2
├── state/
│   ├── last_run.json              # Last-run date & seen IDs (committed by bot)
│   └── tenders.json               # Rolling 90-day archive (committed by bot)
└── docs/
    └── index.html                 # The dashboard (auto-generated)
```

## Running locally to test

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/run_daily.py
# Opens docs/index.html — inspect before committing
```

For the email:
```bash
export SMTP_HOST=... SMTP_PORT=587 SMTP_USER=... SMTP_PASSWORD=...
export EMAIL_TO=you@company.com EMAIL_FROM=you@company.com
python scripts/run_weekly.py
```

## Costs

- GitHub Actions: ~30 min/month used of 2,000 free.
- Anthropic API: ~$0.02–$0.10 per daily run. Budget $10–30/year.
- Everything else: free.
