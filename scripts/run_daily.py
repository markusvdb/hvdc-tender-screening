"""Daily run: fetch from FTS + TED + World Bank + Gmail → screen → summarise → update dashboard."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from fetch_fts import fetch_fts_notices
from fetch_ted import fetch_ted_notices
from fetch_worldbank import fetch_worldbank_notices
from fetch_gmail import fetch_gmail_notices
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
    log.info("=== Daily HVDC screening run (v3) ===")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    api_cfg = config.get("api", {})
    wb_cfg = config.get("worldbank", {})
    gmail_cfg = config.get("gmail", {})

    # ----- FETCH -----
    log.info("Fetching FTS (UK)...")
    try:
        fts_notices = fetch_fts_notices(days_lookback=api_cfg.get("fts_days_lookback", 3))
    except Exception as e:
        log.exception("FTS fetch failed: %s", e)
        fts_notices = []

    log.info("Fetching TED (EU)...")
    try:
        # TED keyword search uses technology terms only — project names need
        # co-occurrence with technology anyway, so searching for technology
        # terms captures the superset.
        ted_notices = fetch_ted_notices(
            days_lookback=api_cfg.get("ted_days_lookback", 3),
            strong_keywords=config.get("hvdc_technology_terms", [])[:15],
            cpv_codes=config.get("cpv_codes", []),
            countries=api_cfg.get("ted_countries", []),
        )
    except Exception as e:
        log.exception("TED fetch failed: %s", e)
        ted_notices = []

    log.info("Fetching World Bank...")
    try:
        wb_notices = fetch_worldbank_notices(
            days_lookback=api_cfg.get("worldbank_days_lookback", 3),
            major_sector=wb_cfg.get("major_sector", "Energy and Extractives"),
            notice_types=wb_cfg.get("notice_types"),
        )
    except Exception as e:
        log.exception("World Bank fetch failed: %s", e)
        wb_notices = []

    log.info("Fetching Gmail alerts...")
    try:
        gmail_notices = fetch_gmail_notices(
            days_lookback=api_cfg.get("gmail_days_lookback", 3),
            label=gmail_cfg.get("label", "HVDC-Alerts"),
            trusted_senders=gmail_cfg.get("trusted_senders", []),
        )
    except Exception as e:
        log.exception("Gmail fetch failed: %s", e)
        gmail_notices = []

    all_new = fts_notices + ted_notices + wb_notices + gmail_notices
    log.info(
        "Fetched %d total new notices (%d FTS + %d TED + %d WB + %d Gmail)",
        len(all_new), len(fts_notices), len(ted_notices), len(wb_notices), len(gmail_notices),
    )

    # ----- MERGE WITH ARCHIVE -----
    archive = load_archive()
    archive_by_id = {t.get("id"): t for t in archive if t.get("id")}
    for n in all_new:
        nid = n.get("id")
        if nid:
            archive_by_id[nid] = n
    merged = list(archive_by_id.values())
    log.info("Merged: %d total (archive + new)", len(merged))

    # ----- SCORE -----
    scored = score_notices(merged, config)
    bid = [n for n in scored if n.get("section") == "bid_candidate"]
    intel = [n for n in scored if n.get("section") == "market_intel"]
    log.info("Scored: %d bid candidates, %d market intel", len(bid), len(intel))

    # ----- SUMMARISE (only notices without summary yet, in priority order) -----
    need_summary = [n for n in scored if n.get("section") in ("bid_candidate", "market_intel") and not n.get("summary")]
    log.info("Summarising up to %d notices needing summaries", len(need_summary))
    if need_summary:
        summarise_notices(need_summary, config)

    # ----- RENDER DASHBOARD -----
    render_dashboard(scored, total_screened=len(scored))

    # ----- PERSIST -----
    save_archive(scored, archive_days=config.get("scoring", {}).get("archive_days", 90))
    save_last_run([n.get("id") for n in scored if n.get("id")])

    log.info("=== Daily run complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
