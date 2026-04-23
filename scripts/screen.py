"""Screen notices against HVDC gate rule, then classify into two sections:

Section 1 — bid_candidate: RTEi-suitable HVDC engineering/consulting work.
Section 2 — market_intel:   HVDC tenders outside RTEi's scope (OEM/EPC/cable supply).

Everything not mentioning HVDC is rejected at the gate.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def score_notices(notices: list[dict], config: dict) -> list[dict]:
    """Apply gate rule and classify. Mutates and returns notices list.

    Each notice gets these fields:
      gate_hits (list[str])           — HVDC gate terms found
      service_hits (list[str])        — RTEi service signal terms found
      buyer_hits (list[str])          — watchlist buyers matched
      score (float)
      section ("bid_candidate" | "market_intel" | "rejected")
      relevance ("high" | "possible" | "low")  — kept for back-compat
      category_tags (list[str])       — for filter buttons
    """
    gate_terms = [t.lower() for t in config.get("hvdc_gate_terms", [])]
    service_terms = [t.lower() for t in config.get("rtei_service_signals", [])]
    watchlist_buyers = [b.lower() for b in config.get("watchlist_buyers", [])]

    min_bid_score = config.get("scoring", {}).get("bid_candidate_min_score", 2.0)

    for n in notices:
        haystack = (
            (n.get("title") or "") + " "
            + (n.get("description") or "")
        ).lower()
        buyer = (n.get("buyer") or "").lower()

        gate_hits = _find_hits(haystack, gate_terms)
        service_hits = _find_hits(haystack, service_terms)
        buyer_hits = [b for b in watchlist_buyers if b in buyer]

        n["gate_hits"] = gate_hits
        n["service_hits"] = service_hits
        n["buyer_hits"] = buyer_hits

        # === GATE RULE ===
        # No gate term match anywhere → rejected, no further processing
        if not gate_hits:
            n["section"] = "rejected"
            n["relevance"] = "low"
            n["score"] = 0.0
            n["category_tags"] = []
            continue

        # Score
        score = len(gate_hits) * 1.0 + len(service_hits) * 1.0 + (0.5 if buyer_hits else 0.0)
        n["score"] = round(score, 2)

        # Classification
        if service_hits and score >= min_bid_score:
            n["section"] = "bid_candidate"
            n["relevance"] = "high"
        else:
            n["section"] = "market_intel"
            n["relevance"] = "possible"

        n["category_tags"] = _categorise(n)

    # Sort: bid_candidate first (by score desc), then market_intel (by score desc), rejected last
    section_order = {"bid_candidate": 0, "market_intel": 1, "rejected": 2}
    notices.sort(key=lambda x: (section_order.get(x.get("section"), 3), -x.get("score", 0.0)))
    return notices


def _find_hits(haystack: str, terms: list[str]) -> list[str]:
    """Find which terms appear in the haystack."""
    hits = []
    for term in terms:
        # Short standalone acronyms (HVDC, VSC, MMC, LCC, EMT, FEED, EGL1-4):
        # require word boundaries to avoid e.g. 'hvdc' matching inside urls
        if len(term) <= 5 and " " not in term and "-" not in term:
            if re.search(r"\b" + re.escape(term) + r"\b", haystack):
                hits.append(term)
        else:
            if term in haystack:
                hits.append(term)
    return hits


def _categorise(notice: dict) -> list[str]:
    """Assign filter tags for the dashboard."""
    tags = set()
    joined = " ".join(notice.get("gate_hits", []) + notice.get("service_hits", [])).lower()
    buyer = (notice.get("buyer") or "").lower()

    # Section 1 categories
    if any(t in joined for t in ["owner's engineer", "owners engineer", "owner engineer", "technical advisor", "technical adviser", "independent engineer"]):
        tags.add("owners_engineer")
    if any(t in joined for t in ["feasibility", "pre-feed", "feed study", "concept study", "options study"]):
        tags.add("feasibility")
    if any(t in joined for t in ["emt study", "electromagnetic transient", "harmonic study", "grid study", "grid stability", "system study", "protection study", "insulation coordination"]):
        tags.add("studies")
    if any(t in joined for t in ["design review", "specification review", "spec writing", "specification writing"]):
        tags.add("design_review")

    # Section 2 categories
    if any(t in joined for t in ["converter station", "converter platform", "valve hall", "vsc converter", "lcc converter", "mmc converter", "modular multilevel converter", "voltage source converter", "line commutated converter"]):
        tags.add("converter")
    if any(t in joined for t in ["eastern green link", "egl1", "egl2", "egl3", "egl4", "viking link", "neuconnect", "lionlink", "suedlink", "nordlink", "balwin", "lanwin", "dolwin", "borwin", "helwin", "north sea link"]):
        tags.add("named_project")

    return sorted(tags)
