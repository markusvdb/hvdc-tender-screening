"""Monday morning: send weekly digest of the last 7 days.

Called by .github/workflows/weekly.yml every Monday 06:00 UTC.
Reads from the archive that the daily job maintains — does NOT re-fetch.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from render_email import render_email
from send_email import send_email
from state import load_archive

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("weekly")


def main() -> int:
    log.info("=== Weekly HVDC digest ===")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    _ = config  # reserved for future tuning (e.g. email thresholds)

    archive = load_archive()

    # Take anything first-seen in the last 7 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    this_week = [
        t for t in archive
        if (t.get("first_seen") or t.get("published") or "") >= cutoff
        and t.get("relevance") in ("high", "possible")
    ]
    this_week.sort(key=lambda t: t.get("score", 0), reverse=True)

    log.info("This week: %d relevant tenders", len(this_week))

    dashboard_url = _dashboard_url()

    html = render_email(
        this_week,
        total_screened=len(archive),
        dashboard_url=dashboard_url,
    )

    text_body = _plain_text_fallback(this_week, dashboard_url)

    high_count = sum(1 for t in this_week if t.get("relevance") == "high")
    subject = f"HVDC tenders — {high_count} high-relevance this week"
    if high_count == 0:
        subject = "HVDC tenders — weekly digest (no high-relevance matches)"

    send_email(subject=subject, html_body=html, text_body=text_body)
    log.info("=== Weekly digest complete ===")
    return 0


def _dashboard_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"
    return os.environ.get("DASHBOARD_URL", "")


def _plain_text_fallback(tenders: list[dict], url: str) -> str:
    lines = [f"HVDC tender weekly digest — {len(tenders)} matches", "", f"Dashboard: {url}", ""]
    for t in tenders[:30]:
        lines.append(f"- [{t.get('source')}] {t.get('title')}")
        lines.append(f"    {t.get('buyer')} · score {t.get('score')}")
        if t.get("url"):
            lines.append(f"    {t.get('url')}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
