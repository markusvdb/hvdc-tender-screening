"""Score notices against keyword tiers defined in config.yaml."""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)


def score_notices(notices: list[dict], config: dict) -> list[dict]:
    """Score each notice and return the list sorted by score (desc).

    Each notice is annotated in place with:
      score (float)
      matched_strong (list[str])
      matched_contextual (list[str])
      matched_watchlist (list[str])
      matched_cpv (list[str])
      relevance ("high" | "possible" | "low")
      category_tags (list[str])  e.g. ["converter", "interconnector"]
    """
    scoring = config.get("scoring", {})
    min_high = scoring.get("min_score_high", 1.5)
    min_possible = scoring.get("min_score_possible", 0.5)

    strong_kws = [k.lower() for k in config.get("keywords_strong", [])]
    contextual_kws = [k.lower() for k in config.get("keywords_contextual", [])]
    watchlist = [w.lower() for w in config.get("watchlist_projects", [])]
    cpv_codes = set(str(c) for c in config.get("cpv_codes", []))

    for n in notices:
        haystack = _haystack(n)
        hay_lower = haystack.lower()

        strong_hits = _find_hits(hay_lower, strong_kws)
        ctx_hits = _find_hits(hay_lower, contextual_kws)
        watch_hits = _find_hits(hay_lower, watchlist)
        cpv_hits = [c for c in n.get("cpv_codes", []) if str(c) in cpv_codes]

        score = len(strong_hits) * 1.0 + len(ctx_hits) * 0.5 + len(cpv_hits) * 0.5
        if watch_hits:
            score += 2.0

        if score >= min_high:
            relevance = "high"
        elif score >= min_possible:
            relevance = "possible"
        else:
            relevance = "low"

        n["score"] = round(score, 2)
        n["matched_strong"] = strong_hits
        n["matched_contextual"] = ctx_hits
        n["matched_watchlist"] = watch_hits
        n["matched_cpv"] = cpv_hits
        n["relevance"] = relevance
        n["category_tags"] = _categorise(strong_hits + ctx_hits + watch_hits)

    notices.sort(key=lambda n: n["score"], reverse=True)
    return notices


def _haystack(notice: dict) -> str:
    """Concatenate searchable fields into one string."""
    return " ".join([
        notice.get("title") or "",
        notice.get("description") or "",
        notice.get("buyer") or "",
    ])


def _find_hits(hay_lower: str, terms: list[str]) -> list[str]:
    """Find which terms appear in the haystack. Returns the original (lowercase) terms."""
    hits = []
    for term in terms:
        # Use word-boundary regex for short terms to avoid false matches;
        # for multi-word phrases a plain substring check is fine.
        if len(term) <= 6 and " " not in term:
            pattern = r"\b" + re.escape(term) + r"\b"
            if re.search(pattern, hay_lower):
                hits.append(term)
        else:
            if term in hay_lower:
                hits.append(term)
    return hits


def _categorise(matched_terms: list[str]) -> list[str]:
    """Map matched keywords to scope tags (for dashboard filters)."""
    tags = set()
    joined = " ".join(matched_terms).lower()

    if any(t in joined for t in ["vsc", "lcc", "mmc", "converter station", "converter platform", "valve hall", "voltage source", "line commutated", "modular multilevel"]):
        tags.add("converter")
    if any(t in joined for t in ["interconnector", "bipole", "monopole", "multi-terminal", "meshed", "hybrid interconnector", "offshore hybrid"]):
        tags.add("interconnector")
    if any(t in joined for t in ["owner's engineer", "owners engineer", "technical advisor", "feasibility study", "pre-feed", "feed study"]):
        tags.add("consulting")
    if any(t in joined for t in ["emt study", "electromagnetic transient", "grid stability study", "r&d", "research"]):
        tags.add("studies")

    # Always tag on project-named watchlist hits — these projects are all
    # interconnector/transmission projects by definition
    watchlist_markers = ["egl", "eastern green link", "viking link", "neuconnect", "lionlink", "suedlink", "balwin", "lanwin", "dolwin", "borwin", "helwin", "kriegers flak", "kontek", "shetland", "north sea link"]
    if any(w in joined for w in watchlist_markers):
        tags.add("interconnector")

    return sorted(tags)
