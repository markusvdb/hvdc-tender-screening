"""Render the dashboard HTML to docs/index.html."""
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
    """Build docs/index.html from the screened + summarised tender list."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tpl = env.get_template("dashboard.html.j2")

    # Only show high + possible on the dashboard
    visible = [t for t in tenders if t.get("relevance") in ("high", "possible")]
    for t in visible:
        _enrich_for_display(t)

    high_count = sum(1 for t in visible if t.get("relevance") == "high")
    possible_count = sum(1 for t in visible if t.get("relevance") == "possible")
    corrigenda_count = sum(1 for t in visible if _is_corrigendum(t))

    # Category counts
    counts = {"converter": 0, "interconnector": 0, "consulting": 0, "studies": 0}
    for t in visible:
        for tag in t.get("category_tags", []):
            if tag in counts:
                counts[tag] += 1

    now = datetime.now(timezone.utc)

    html = tpl.render(
        tenders=visible,
        total_screened=total_screened,
        high_count=high_count,
        possible_count=possible_count,
        corrigenda_count=corrigenda_count,
        relevant_count=len(visible),
        counts=counts,
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
    """Pre-compute display strings so the template stays clean."""
    t["badge_class"], t["badge_label"] = _badge(t)

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


def _badge(t: dict) -> tuple[str, str]:
    if _is_corrigendum(t):
        return "b-corr", "Corrigendum"
    if _is_award(t):
        return "b-award", "Award"
    if t.get("relevance") == "high":
        return "b-high", "High relevance"
    return "b-possible", "Possibly relevant"


def _is_corrigendum(t: dict) -> bool:
    nt = (t.get("notice_type") or "").lower()
    return "corrigendum" in nt or "f14" in nt or "cor-" in nt


def _is_award(t: dict) -> bool:
    nt = (t.get("notice_type") or "").lower()
    return "award" in nt or "f03" in nt or "f06" in nt or "uk6" in nt


def _short_date(s: str) -> str:
    if not s:
        return ""
    try:
        # Try common ISO formats
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s[:len(fmt) if fmt == "%Y-%m-%d" else 25], fmt) if fmt != "%Y-%m-%dT%H:%M:%S%z" else datetime.fromisoformat(s.replace("Z", "+00:00"))
                return dt.strftime("%d %b %Y")
            except ValueError:
                continue
    except Exception:
        pass
    return s[:10]
