"""Monday morning: send weekly digest of bid candidates seen in the last 7 days.

Reads from the archive that the daily job maintains.
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
    log.info("=== Weekly HVDC bid candidates digest ===")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    _ = config

    archive = load_archive()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    # Only bid_candidates seen in the last 7 days
    this_week = [
        t for t in archive
        if (t.get("first_seen") or t.get("published") or "") >= cutoff
        and t.get("section") == "bid_candidate"
    ]
    this_week.sort(key=lambda t: t.get("score", 0), reverse=True)

    log.info("This week: %d bid candidates", len(this_week))

    dashboard_url = _dashboard_url()

    html = render_email(
        this_week,
        total_screened=len(archive),
        dashboard_url=dashboard_url,
    )

    text_body = _plain_text_fallback(this_week, dashboard_url)

    bid_count = len(this_week)
    if bid_count == 0:
        subject = "HVDC digest — no bid candidates this week"
    elif bid_count == 1:
        subject = "HVDC digest — 1 bid candidate this week"
    else:
        subject = f"HVDC digest — {bid_count} bid candidates this week"

    send_email(subject=subject, html_body=html, text_body=text_body)
    log.info("=== Weekly digest sent ===")
    return 0


def _dashboard_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"
    return os.environ.get("DASHBOARD_URL", "")


def _plain_text_fallback(tenders: list[dict], url: str) -> str:
    lines = [f"HVDC bid candidates — {len(tenders)} this week", "", f"Full dashboard: {url}", ""]
    for t in tenders[:30]:
        lines.append(f"- [{t.get('source')}] {t.get('title')}")
        lines.append(f"    {t.get('buyer')} · score {t.get('score')}")
        if t.get("url"):
            lines.append(f"    {t.get('url')}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
