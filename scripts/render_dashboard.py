"""Render dashboard HTML with two sections + stage filter."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
OUTPUT_PATH = Path(__file__).parent.parent / "docs" / "index.html"


def render_dashboard(tenders: list[dict], total_screened: int, repo: str = "") -> Path:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tpl = env.get_template("dashboard.html.j2")

    bid_candidates = [t for t in tenders if t.get("section") == "bid_candidate"]
    market_intel = [t for t in tenders if t.get("section") == "market_intel"]
    rejected = [t for t in tenders if t.get("section") == "rejected"]

    for t in bid_candidates + market_intel:
        _enrich_for_display(t)

    # Stage counts (across visible sections)
    visible = bid_candidates + market_intel
    stage_counts = {"active": 0, "pipeline": 0, "corrigendum": 0, "award": 0, "other": 0}
    for t in visible:
        s = t.get("stage", "other")
        stage_counts[s] = stage_counts.get(s, 0) + 1

    now = datetime.now(timezone.utc)

    html = tpl.render(
        bid_candidates=bid_candidates,
        market_intel=market_intel,
        bid_count=len(bid_candidates),
        intel_count=len(market_intel),
        rejected_count=len(rejected),
        total_visible=len(visible),
        active_count=stage_counts["active"],
        pipeline_count=stage_counts["pipeline"],
        corrigenda_count=stage_counts["corrigendum"],
        award_count=stage_counts["award"],
        total_screened=total_screened,
        last_run_label=now.strftime("%a %d %b %Y, %H:%M UTC"),
        this_week_label=now.strftime("Updated %a %d %b %Y"),
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
        repo=repo or os.environ.get("GITHUB_REPOSITORY", ""),
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    log.info("Wrote dashboard to %s", OUTPUT_PATH)
    return OUTPUT_PATH


def _enrich_for_display(t: dict) -> None:
    value = t.get("value_amount")
    currency = t.get("value_currency") or ""
    if value:
        try:
            t["value_display"] = f"{currency} {float(value):,.0f}".strip()
        except (ValueError, TypeError):
            t["value_display"] = f"{value} {currency}".strip()
    else:
        t["value_display"] = ""

    t["deadline_display"] = _short_date(t.get("deadline"))
    t["published_display"] = _short_date(t.get("published"))

    desc = t.get("description") or ""
    t["description_snippet"] = (desc[:280] + "…") if len(desc) > 280 else desc


def _short_date(s: str) -> str:
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except (ValueError, TypeError):
        return s[:10]
