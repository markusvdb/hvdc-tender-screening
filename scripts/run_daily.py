"""Daily run: fetch → screen → summarise → update dashboard.

Called by .github/workflows/daily.yml every morning 06:00 UTC.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

# Add scripts/ to path so sibling imports work
sys.path.insert(0, str(Path(__file__).parent))

from fetch_fts import fetch_fts_notices
from fetch_ted import fetch_ted_notices
from screen import score_notices
from summarise import summarise_notices
from render_dashboard import render_dashboard
from state import load_archive, save_archive, save_last_run

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("daily")


def main() -> int:
    log.info("=== Daily HVDC screening run ===")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    api_cfg = config.get("api", {})

    # 1. Fetch from both sources
    log.info("Fetching FTS (UK)...")
    try:
        fts_notices = fetch_fts_notices(days_lookback=api_cfg.get("fts_days_lookback", 3))
    except Exception as e:
        log.exception("FTS fetch failed: %s", e)
        fts_notices = []

    log.info("Fetching TED (EU)...")
    try:
        ted_notices = fetch_ted_notices(
            days_lookback=api_cfg.get("ted_days_lookback", 3),
            strong_keywords=config.get("keywords_strong", []),
            cpv_codes=config.get("cpv_codes", []),
            countries=api_cfg.get("ted_countries", []),
        )
    except Exception as e:
        log.exception("TED fetch failed: %s", e)
        ted_notices = []

    all_new = fts_notices + ted_notices
    log.info("Fetched %d new notices (%d FTS + %d TED)", len(all_new), len(fts_notices), len(ted_notices))

    # 2. Merge with archive so dashboard shows rolling view
    archive = load_archive()
    archive_by_id = {t.get("id"): t for t in archive if t.get("id")}
    for n in all_new:
        nid = n.get("id")
        if nid:
            archive_by_id[nid] = n  # new data overwrites old
    merged = list(archive_by_id.values())
    log.info("Merged: %d total (archive + new)", len(merged))

    # 3. Score everything
    scored = score_notices(merged, config)
    high = [n for n in scored if n.get("relevance") == "high"]
    possible = [n for n in scored if n.get("relevance") == "possible"]
    log.info("Scored: %d high, %d possible", len(high), len(possible))

    # 4. Summarise high-relevance only (caps cost)
    # Only summarise ones that don't already have a summary from a prior run
    need_summary = [n for n in high if not n.get("summary")]
    log.info("Summarising %d new high-relevance notices", len(need_summary))
    if need_summary:
        summarise_notices(need_summary, config)

    # 5. Render dashboard
    render_dashboard(scored, total_screened=len(scored))

    # 6. Persist state
    save_archive(scored, archive_days=config.get("scoring", {}).get("archive_days", 90))
    save_last_run([n.get("id") for n in scored if n.get("id")])

    log.info("=== Daily run complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
