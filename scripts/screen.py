"""Screen notices: apply gate rule, classify section & stage.

Sections (same as v2):
  bid_candidate: RTEi-suitable HVDC engineering/consulting work
  market_intel:  HVDC tenders outside RTEi scope (OEM/EPC/supply)
  rejected:      no HVDC gate term matched

Stages (new in v3):
  pipeline / active / corrigendum / award / other
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def score_notices(notices: list[dict], config: dict) -> list[dict]:
    """Classify and score notices. Mutates and returns the list.

    Gate rule (two paths):
      Path A: notice contains a HVDC TECHNOLOGY term → passes gate
      Path B: notice contains a PROJECT NAME + a technology term → passes gate
              (project name alone is insufficient — avoids geographic collisions
              like Madagascar "Sofia region" matching the UK "Sofia" wind farm)
    """
    tech_terms = [t.lower() for t in config.get("hvdc_technology_terms", [])]
    project_names = [p.lower() for p in config.get("hvdc_project_names", [])]
    # Backward-compat: if old single-list config is used, treat all as tech
    legacy_gate = [t.lower() for t in config.get("hvdc_gate_terms", [])]
    if legacy_gate and not tech_terms:
        tech_terms = legacy_gate
        project_names = []

    service_terms = [t.lower() for t in config.get("rtei_service_signals", [])]
    watchlist_buyers = [b.lower() for b in config.get("watchlist_buyers", [])]
    stages_cfg = config.get("stages", {})

    min_bid_score = config.get("scoring", {}).get("bid_candidate_min_score", 2.0)

    for n in notices:
        haystack = (
            (n.get("title") or "") + " "
            + (n.get("description") or "")
        ).lower()
        buyer = (n.get("buyer") or "").lower()

        tech_hits = _find_hits(haystack, tech_terms)
        project_hits = _find_hits(haystack, project_names)
        service_hits = _find_hits(haystack, service_terms)
        buyer_hits = [b for b in watchlist_buyers if b in buyer]

        # Apply two-path gate
        if tech_hits:
            # Path A: technology term present → pass, count project name as bonus
            gate_hits = tech_hits + project_hits
            gate_pass = True
        elif project_hits and tech_hits:
            # Path B would fire here but already covered above
            gate_hits = project_hits + tech_hits
            gate_pass = True
        else:
            # No technology term → project names are NOT sufficient alone
            gate_hits = []
            gate_pass = False

        n["gate_hits"] = gate_hits
        n["tech_hits"] = tech_hits
        n["project_hits"] = project_hits
        n["service_hits"] = service_hits
        n["buyer_hits"] = buyer_hits
        n["stage"] = _classify_stage(n, stages_cfg)

        if not gate_pass:
            n["section"] = "rejected"
            n["relevance"] = "low"
            n["score"] = 0.0
            n["category_tags"] = []
            continue

        score = (
            len(tech_hits) * 1.0
            + len(project_hits) * 0.5
            + len(service_hits) * 1.0
            + (0.5 if buyer_hits else 0.0)
        )
        n["score"] = round(score, 2)

        if service_hits and score >= min_bid_score:
            n["section"] = "bid_candidate"
            n["relevance"] = "high"
        else:
            n["section"] = "market_intel"
            n["relevance"] = "possible"

        n["category_tags"] = _categorise(n)

    section_order = {"bid_candidate": 0, "market_intel": 1, "rejected": 2}
    notices.sort(key=lambda x: (section_order.get(x.get("section"), 3), -x.get("score", 0.0)))
    return notices


def _find_hits(haystack: str, terms: list[str]) -> list[str]:
    hits = []
    for term in terms:
        if len(term) <= 5 and " " not in term and "-" not in term:
            if re.search(r"\b" + re.escape(term) + r"\b", haystack):
                hits.append(term)
        else:
            if term in haystack:
                hits.append(term)
    return hits


def _classify_stage(notice: dict, stages_cfg: dict) -> str:
    """Assign a stage based on notice_type and other signals."""
    notice_type = (notice.get("notice_type") or "").lower()
    title = (notice.get("title") or "").lower()

    # Check each stage's keywords in priority order
    # Corrigendum wins over active (corrigendum of an active tender is still a corrigendum)
    priority = ["corrigendum", "award", "pipeline", "active", "other"]

    for stage in priority:
        stage_def = stages_cfg.get(stage, {})
        keywords = [k.lower() for k in stage_def.get("keywords", [])]
        for kw in keywords:
            if kw in notice_type or kw in title:
                return stage

    # Source-specific heuristics
    source = notice.get("source", "")
    if source == "Gmail":
        return "active"  # TSO portal alerts are usually active opportunities
    if source == "WB":
        # World Bank: REoI and IFBs are active; GPN is pipeline
        if "general procurement" in notice_type.lower():
            return "pipeline"
        return "active"

    return "other"


def _categorise(notice: dict) -> list[str]:
    tags = set()
    joined = " ".join(notice.get("gate_hits", []) + notice.get("service_hits", [])).lower()

    if any(t in joined for t in ["owner's engineer", "owners engineer", "owner engineer", "technical advisor", "independent engineer"]):
        tags.add("owners_engineer")
    if any(t in joined for t in ["feasibility", "pre-feed", "feed study", "concept study", "options study"]):
        tags.add("feasibility")
    if any(t in joined for t in ["emt study", "electromagnetic transient", "harmonic study", "grid study", "grid stability", "system study", "protection study", "insulation coordination"]):
        tags.add("studies")
    if any(t in joined for t in ["design review", "specification review", "spec writing", "specification writing"]):
        tags.add("design_review")
    if any(t in joined for t in ["converter station", "converter platform", "valve hall", "vsc converter", "lcc converter", "mmc converter"]):
        tags.add("converter")

    # Watchlist-project tagging (rough — these are all interconnectors or offshore projects)
    watchlist_markers = [
        "egl", "eastern green link", "viking link", "neuconnect", "lionlink",
        "suedlink", "balwin", "lanwin", "dolwin", "borwin", "helwin",
        "kriegers flak", "kontek", "shetland", "north sea link", "dogger bank",
        "hornsea", "ijmuiden", "nederwiek", "doordewind", "celtic interconnector",
        "neuconnect", "tarchon", "nautilus", "gridlink",
    ]
    if any(w in joined for w in watchlist_markers):
        tags.add("named_project")

    return sorted(tags)
