"""Render the weekly digest email HTML."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from render_dashboard import _enrich_for_display, _is_corrigendum

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def render_email(tenders: list[dict], total_screened: int, dashboard_url: str) -> str:
    """Return the HTML body of the weekly email."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tpl = env.get_template("email.html.j2")

    for t in tenders:
        _enrich_for_display(t)

    high = [t for t in tenders if t.get("relevance") == "high" and not _is_corrigendum(t)]
    possible = [t for t in tenders if t.get("relevance") == "possible" and not _is_corrigendum(t)]
    corrigenda = [t for t in tenders if _is_corrigendum(t)]

    now = datetime.now(timezone.utc)

    return tpl.render(
        high_tenders=high,
        possible_tenders=possible,
        corrigenda=corrigenda,
        total_screened=total_screened,
        high_count=len(high),
        possible_count=len(possible),
        corrigenda_count=len(corrigenda),
        week_of=now.strftime("%d %b %Y"),
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        dashboard_url=dashboard_url,
    )
