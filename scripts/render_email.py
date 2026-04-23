"""Render the weekly digest email HTML — bid candidates only."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from render_dashboard import _enrich_for_display

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def render_email(tenders: list[dict], total_screened: int, dashboard_url: str) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tpl = env.get_template("email.html.j2")

    bid_candidates = [t for t in tenders if t.get("section") == "bid_candidate"]
    intel_count = sum(1 for t in tenders if t.get("section") == "market_intel")

    for t in bid_candidates:
        _enrich_for_display(t)

    now = datetime.now(timezone.utc)

    return tpl.render(
        bid_candidates=bid_candidates,
        bid_count=len(bid_candidates),
        intel_count=intel_count,
        total_screened=total_screened,
        week_of=now.strftime("%d %b %Y"),
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        dashboard_url=dashboard_url,
    )
