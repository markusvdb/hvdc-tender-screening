"""World Bank Procurement Notices API client.

Public endpoint: https://search.worldbank.org/api/v2/procnotices
Returns JSON. No authentication required.
Docs: https://www.worldbank.org/ext/en/what-we-do/project-procurement/for-suppliers
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)

ENDPOINT = "https://search.worldbank.org/api/v2/procnotices"
USER_AGENT = "hvdc-tender-screening/3.0 (daily HVDC screening bot)"
REQUEST_TIMEOUT = 45
PAGE_SIZE = 100


def fetch_worldbank_notices(
    days_lookback: int = 3,
    major_sector: str = "Energy and Extractives",
    notice_types: list[str] | None = None,
) -> list[dict]:
    """Fetch recent World Bank procurement notices in the energy sector.

    Filters applied at the API level:
      - Energy sector
      - Publication date within lookback window

    Keyword/HVDC filtering happens downstream in screen.py so the gate rule
    is applied consistently across all sources.
    """
    notice_types = notice_types or [
        "Request for Expression of Interest",
        "Invitation for Bids",
        "Invitation for Prequalification",
        "General Procurement Notice",
        "Specific Procurement Notice",
    ]

    since = (datetime.now(timezone.utc) - timedelta(days=days_lookback)).strftime("%Y-%m-%d")

    all_notices: list[dict] = []
    offset = 0
    while offset < 2000:  # hard safety cap
        params = {
            "format": "json",
            "fl": "id,title,description,notice_type,notice_text,country_name,project_name,project_id,"
                  "submission_deadline_date,publication_date,contact,major_sector,notice_status,url",
            "rows": PAGE_SIZE,
            "os": offset,
            "srt": "publication_date",
            "order": "desc",
            "apilang": "en",
            "srce": "both",
            "deadline_strdate": since,
            "major_sector_exact": major_sector,
            # notice_type_exact accepts caret-separated values per WB docs
            "notice_type_exact": "^".join(notice_types),
        }

        log.info("World Bank page offset=%d", offset)
        try:
            resp = _get_with_retry(ENDPOINT, params)
        except requests.RequestException as e:
            log.exception("World Bank request failed after retries: %s", e)
            break

        try:
            payload = resp.json()
        except ValueError:
            log.warning("World Bank returned non-JSON response, stopping")
            break

        # WB API response shape varies — try the documented keys
        docs = payload.get("procnotices") or payload.get("documents") or payload.get("notices") or {}
        if isinstance(docs, dict):
            batch = list(docs.values())
        elif isinstance(docs, list):
            batch = docs
        else:
            batch = []

        if not batch:
            log.info("  no notices in response (keys: %s)", list(payload.keys())[:5])
            break

        all_notices.extend(batch)
        log.info("  got %d notices (running total %d)", len(batch), len(all_notices))

        total = int(payload.get("total", 0))
        if offset + PAGE_SIZE >= total:
            break
        offset += PAGE_SIZE
        time.sleep(0.5)

    return [_normalise_wb(n) for n in all_notices]


def _get_with_retry(url: str, params: dict, max_attempts: int = 3) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt == max_attempts:
                raise
            wait = 2 ** attempt
            log.warning("World Bank request failed (%s), retrying in %ds", e, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _normalise_wb(n: dict) -> dict:
    """Normalise a World Bank procnotices record to the common shape."""
    pub_num = n.get("id", "")
    title = (n.get("title") or "").strip()
    description = (n.get("description") or n.get("notice_text") or "").strip()
    country = n.get("country_name") or ""
    if isinstance(country, list):
        country = country[0] if country else ""
    project = n.get("project_name") or ""
    buyer = f"World Bank — {project}" if project else "World Bank"
    notice_type = n.get("notice_type") or ""
    deadline = n.get("submission_deadline_date") or ""
    published = n.get("publication_date") or ""
    url = n.get("url") or f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{pub_num}"

    return {
        "source": "WB",
        "id": f"wb-{pub_num}" if pub_num else f"wb-{hash(title)}",
        "url": url,
        "title": title,
        "description": description,
        "buyer": buyer,
        "notice_type": notice_type,
        "published": published,
        "deadline": deadline,
        "value_amount": None,   # WB API doesn't expose contract value at notice level
        "value_currency": None,
        "cpv_codes": [],        # WB doesn't use CPV
        "country": country,
        "raw": n,
    }
