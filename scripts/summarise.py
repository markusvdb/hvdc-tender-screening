"""Per-notice summariser using the Anthropic API.

Different prompt depending on section (bid_candidate vs market_intel).
"""
from __future__ import annotations

import json
import logging
import os

import anthropic

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an analyst screening HVDC-related tender notices for RTEi,
an engineering consultancy whose HVDC team bids for:
- Owner's engineer / technical advisor roles
- Electrical design review and specification review
- Feasibility studies, pre-FEED, FEED studies
- System studies (EMT, harmonic, grid stability, protection, insulation coordination)

For each tender, produce a compact structured summary in this EXACT JSON schema:

{
  "scope_summary": "2-3 sentences stating what is being procured, in plain English",
  "rtei_bid_fit": "yes / partial / no — does this scope match RTEi's HVDC consulting services?",
  "rtei_bid_fit_reason": "one short sentence justifying the bid_fit verdict",
  "estimated_value": "e.g. '€4.5m (indicative)' or 'Not disclosed'",
  "key_dates": {"submission_deadline": "DD Mon YYYY or 'Not specified'", "other_milestones": "brief note or 'None'"},
  "notable_requirements": ["up to 3 short bullets — only if genuinely notable; empty list is fine"],
  "red_flags": ["up to 2 short bullets on risks, unusual conditions, or scope ambiguities; empty list is fine"]
}

Rules:
- Return ONLY the JSON, no prose around it, no code fences.
- Be factual. Do not invent details not present in the source.
- For 'rtei_bid_fit': 'yes' = core RTEi services and HVDC scope; 'partial' = adjacent (e.g. AC scope with HVDC context, or HVDC project but non-engineering service); 'no' = equipment supply, EPC, construction, cable manufacture, platform fabrication.
- Fields unclear from the source: use "Not specified" (strings) or [] (lists).
- Keep it terse. This reads in a daily dashboard — signal, not padding.
"""

USER_TEMPLATE = """Tender to summarise (section = {section}):

Title: {title}
Buyer: {buyer}
Source: {source}
Notice type: {notice_type}
Published: {published}
Deadline: {deadline}
Value: {value}
CPV codes: {cpv}
HVDC terms matched: {gate}
RTEi service terms matched: {services}

Description:
{description}

URL: {url}
"""


def summarise_notices(notices: list[dict], config: dict) -> list[dict]:
    """Attach `.summary` dict to as many notices as budget allows.

    Prioritises bid_candidate section first, then market_intel.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping summaries")
        return notices

    llm_cfg = config.get("llm", {})
    model = llm_cfg.get("model", "claude-haiku-4-5-20251001")
    max_summaries = llm_cfg.get("max_summaries_per_run", 25)

    client = anthropic.Anthropic(api_key=api_key)

    # Prioritise: bid candidates first (highest value per dollar), then market intel
    bid_candidates = [n for n in notices if n.get("section") == "bid_candidate" and not n.get("summary")]
    market_intel = [n for n in notices if n.get("section") == "market_intel" and not n.get("summary")]

    to_summarise = (bid_candidates + market_intel)[:max_summaries]
    log.info(
        "Summarising %d notices (%d bid / %d intel) with %s",
        len(to_summarise), len(bid_candidates), len(market_intel), model,
    )

    for i, n in enumerate(to_summarise, 1):
        try:
            summary = _summarise_one(client, model, n)
            n["summary"] = summary
            log.info("  [%d/%d] %s: %s", i, len(to_summarise), n.get("section"), (n.get("title") or "")[:60])
        except Exception as e:
            log.exception("Failed to summarise notice %s: %s", n.get("id"), e)
            n["summary"] = {"scope_summary": "(summary unavailable)", "error": str(e)}

    return notices


def _summarise_one(client, model: str, notice: dict) -> dict:
    value = notice.get("value_amount")
    currency = notice.get("value_currency") or ""
    value_str = f"{value} {currency}".strip() if value else "Not disclosed"

    prompt = USER_TEMPLATE.format(
        section=notice.get("section", ""),
        title=notice.get("title", ""),
        buyer=notice.get("buyer", ""),
        source=notice.get("source", ""),
        notice_type=notice.get("notice_type", ""),
        published=notice.get("published", ""),
        deadline=notice.get("deadline", ""),
        value=value_str,
        cpv=", ".join(notice.get("cpv_codes", [])[:5]) or "none",
        gate=", ".join(notice.get("gate_hits", [])) or "none",
        services=", ".join(notice.get("service_hits", [])) or "none",
        description=(notice.get("description") or "")[:3000],
        url=notice.get("url", ""),
    )

    resp = client.messages.create(
        model=model,
        max_tokens=700,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()

    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Summariser returned non-JSON: %s", text[:200])
        return {"scope_summary": text[:500], "parse_error": True}
