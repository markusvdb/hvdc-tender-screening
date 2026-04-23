"""Per-notice summariser using the Anthropic API.

Only called for high-relevance notices to keep costs low.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import anthropic

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an analyst summarising HVDC-related tender notices for an engineering firm.

For each tender you receive, produce a compact, structured summary in this exact JSON schema:

{
  "scope_summary": "2-3 sentences on what is actually being procured",
  "key_dates": {"submission_deadline": "...", "other_milestones": "..."},
  "estimated_value": "e.g. '€4.5m (indicative)' or 'Not disclosed'",
  "notable_requirements": ["up to 3 short bullets — e.g. 'EMT modelling in PSCAD', 'Multi-vendor interoperability per CIGRE B4.72'"],
  "red_flags": ["up to 2 short bullets on risks or unusual conditions — or empty list"],
  "bid_fit_indicator": "one of: strong / possible / weak / n/a — based purely on whether scope is genuinely HVDC-related"
}

Rules:
- Return ONLY the JSON, no prose around it.
- Be factual. Do not invent details not in the source.
- If a field isn't clear from the source, say "Not specified" (string fields) or [] (lists).
- Keep it terse. This goes in a daily digest — reader wants signal, not padding.
"""

USER_TEMPLATE = """Summarise this tender:

Title: {title}
Buyer: {buyer}
Source: {source}
Notice type: {notice_type}
Published: {published}
Deadline: {deadline}
Value: {value}
CPV codes: {cpv}
Matched keywords: {keywords}

Description:
{description}

URL: {url}
"""


def summarise_notices(notices: list[dict], config: dict) -> list[dict]:
    """Add `.summary` (dict) to high-relevance notices.

    Returns the full list (mutated in place) with summaries attached to as
    many top-scored notices as budget allows.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping summaries")
        return notices

    llm_cfg = config.get("llm", {})
    model = llm_cfg.get("model", "claude-haiku-4-5-20251001")
    max_summaries = llm_cfg.get("max_summaries_per_run", 30)

    client = anthropic.Anthropic(api_key=api_key)

    to_summarise = [n for n in notices if n.get("relevance") == "high"][:max_summaries]
    log.info("Summarising %d high-relevance notices with %s", len(to_summarise), model)

    for i, n in enumerate(to_summarise, 1):
        try:
            summary = _summarise_one(client, model, n)
            n["summary"] = summary
            log.info("  [%d/%d] summarised: %s", i, len(to_summarise), n.get("title", "")[:60])
        except Exception as e:
            log.exception("Failed to summarise notice %s: %s", n.get("id"), e)
            n["summary"] = {"scope_summary": "(summary unavailable)", "error": str(e)}

    return notices


def _summarise_one(client, model: str, notice: dict) -> dict:
    value = notice.get("value_amount")
    currency = notice.get("value_currency") or ""
    value_str = f"{value} {currency}".strip() if value else "Not disclosed"

    prompt = USER_TEMPLATE.format(
        title=notice.get("title", ""),
        buyer=notice.get("buyer", ""),
        source=notice.get("source", ""),
        notice_type=notice.get("notice_type", ""),
        published=notice.get("published", ""),
        deadline=notice.get("deadline", ""),
        value=value_str,
        cpv=", ".join(notice.get("cpv_codes", [])[:5]) or "none",
        keywords=", ".join((notice.get("matched_strong") or []) + (notice.get("matched_watchlist") or [])) or "none",
        description=(notice.get("description") or "")[:3000],
        url=notice.get("url", ""),
    )

    resp = client.messages.create(
        model=model,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()

    import json
    # Strip code fences if present
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Summariser returned non-JSON: %s", text[:200])
        return {"scope_summary": text[:500], "parse_error": True}
