"""TED (EU) Search API v3 client.

Docs: https://docs.ted.europa.eu/api/latest/search.html
Endpoint: https://api.ted.europa.eu/v3/notices/search (anonymous access for search).

The TED search API uses an 'expert query' string. We build a broad query
(CPV codes OR keyword match) and let the local screener do the fine filtering.
Reason: the TED query language doesn't support the same nuanced scoring we do
locally, and pulling a superset is cheap.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

import requests

log = logging.getLogger(__name__)

TED_ENDPOINT = "https://api.ted.europa.eu/v3/notices/search"
USER_AGENT = "hvdc-tender-screening/1.0 (daily HVDC screening bot; contact via repo)"
REQUEST_TIMEOUT = 45
PAGE_SIZE = 100


def fetch_ted_notices(
    days_lookback: int = 3,
    strong_keywords: list[str] | None = None,
    cpv_codes: list[str] | None = None,
    countries: list[str] | None = None,
) -> list[dict]:
    """Fetch TED notices matching a broad HVDC filter.

    We pull a superset (anything matching a strong keyword OR a listed CPV OR
    an interconnector-related word). Local screening does the real filtering.
    """
    strong_keywords = strong_keywords or ["HVDC"]
    cpv_codes = cpv_codes or []
    countries = countries or []

    since = (datetime.now(timezone.utc) - timedelta(days=days_lookback)).strftime("%Y%m%d")
    until = datetime.now(timezone.utc).strftime("%Y%m%d")

    query = _build_query(since, until, strong_keywords, cpv_codes, countries)
    log.info("TED query: %s", query)

    all_notices: list[dict] = []
    page = 1
    while page <= 20:  # safety cap — 20 * 100 = 2000 notices max per run
        body = {
            "query": query,
            "fields": [
                "publication-number",
                "notice-title",
                "notice-type",
                "publication-date",
                "deadline-receipt-tender-date-lot",
                "buyer-name",
                "buyer-country",
                "classification-cpv",
                "description-proc",
                "total-value",
                "links",
            ],
            "limit": PAGE_SIZE,
            "page": page,
            "scope": "ALL",
            "checkQuerySyntax": False,
            "paginationMode": "PAGE_NUMBER",
            "onlyLatestVersions": True,
        }
        log.info("TED page %d", page)
        resp = _post_with_retry(TED_ENDPOINT, body)
        payload = resp.json()
        notices = payload.get("notices", [])
        if not notices:
            break
        all_notices.extend(notices)
        log.info("  got %d notices (running total %d)", len(notices), len(all_notices))
        total = payload.get("totalNoticeCount", 0)
        if len(all_notices) >= total:
            break
        page += 1
        time.sleep(0.8)  # respect TED fair-use

    return [_normalise_ted(n) for n in all_notices]


def _build_query(since: str, until: str, keywords: list[str], cpvs: list[str], countries: list[str]) -> str:
    """Build a TED expert-search query string."""
    # Date window
    parts = [f"publication-date>={since}", f"publication-date<={until}"]

    # OR together: keyword match OR CPV match
    or_clauses = []
    for kw in keywords:
        # Escape quotes, wrap multiword phrases
        kw_q = kw.replace('"', '\\"')
        or_clauses.append(f'notice-title~"{kw_q}" OR description-proc~"{kw_q}"')
    for cpv in cpvs:
        or_clauses.append(f'classification-cpv={cpv}')
    if or_clauses:
        parts.append("(" + " OR ".join(or_clauses) + ")")

    # Country filter
    if countries:
        country_q = " OR ".join(f"buyer-country={c}" for c in countries)
        parts.append(f"({country_q})")

    return " AND ".join(parts)


def _post_with_retry(url: str, body: dict, max_attempts: int = 3) -> requests.Response:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt == max_attempts:
                raise
            wait = 2 ** attempt
            log.warning("TED request failed (%s), retrying in %ds", e, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _normalise_ted(notice: dict) -> dict:
    """Flatten a TED search result into our common shape."""
    pub_num = notice.get("publication-number", "")
    title = _pick_lang(notice.get("notice-title"))
    description = _pick_lang(notice.get("description-proc"))
    buyer = _pick_lang(notice.get("buyer-name"))
    country = notice.get("buyer-country") or ""
    if isinstance(country, list):
        country = country[0] if country else ""

    cpv_raw = notice.get("classification-cpv") or []
    if isinstance(cpv_raw, str):
        cpv_codes = [cpv_raw]
    else:
        cpv_codes = [str(c) for c in cpv_raw]

    deadline = notice.get("deadline-receipt-tender-date-lot") or ""
    if isinstance(deadline, list):
        deadline = deadline[0] if deadline else ""

    value = notice.get("total-value") or {}
    if isinstance(value, list):
        value = value[0] if value else {}

    url = f"https://ted.europa.eu/en/notice/-/detail/{pub_num}" if pub_num else ""

    return {
        "source": "TED",
        "id": pub_num,
        "url": url,
        "title": title,
        "description": description,
        "buyer": buyer,
        "notice_type": notice.get("notice-type", ""),
        "published": notice.get("publication-date", ""),
        "deadline": deadline,
        "value_amount": value.get("amount") if isinstance(value, dict) else None,
        "value_currency": value.get("currency") if isinstance(value, dict) else None,
        "cpv_codes": cpv_codes,
        "country": country,
        "raw": notice,
    }


def _pick_lang(field) -> str:
    """TED fields are often dicts keyed by language code. Prefer English."""
    if not field:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, list):
        field = field[0] if field else ""
        return _pick_lang(field)
    if isinstance(field, dict):
        for k in ("eng", "en", "ENG", "EN"):
            if k in field:
                return str(field[k])
        # fall back to first non-empty value
        for v in field.values():
            if v:
                return str(v)
    return ""
