"""Find a Tender (UK) OCDS API client.

Docs: https://www.find-tender.service.gov.uk/apidocumentation/1.0/GET-ocdsReleasePackages
Base: https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages
Data licence: Open Government Licence v3.0.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
USER_AGENT = "hvdc-tender-screening/1.0 (weekly HVDC screening bot)"
REQUEST_TIMEOUT = 30


def fetch_fts_notices(days_lookback: int = 3) -> list[dict]:
    """Fetch all FTS OCDS releases published in the last `days_lookback` days.

    Returns a normalised list of dicts with consistent fields used downstream.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days_lookback)
    until = datetime.now(timezone.utc)

    params = {
        "updatedFrom": since.strftime("%Y-%m-%dT%H:%M:%S"),
        "updatedTo": until.strftime("%Y-%m-%dT%H:%M:%S"),
        "limit": 100,
    }

    all_releases: list[dict] = []
    url = BASE_URL
    page = 0
    while url and page < 50:  # hard safety limit
        log.info("FTS page %d — %s", page, url)
        try:
            resp = _get_with_retry(url, params=params if page == 0 else None)
            payload = resp.json()
        except (requests.RequestException, ValueError) as e:
            # Transient server glitch (bad JSON, 5xx, timeout). Keep what we
            # already have rather than discarding the entire fetch.
            log.warning(
                "FTS page %d failed (%s) — continuing with %d releases gathered so far",
                page, e, len(all_releases),
            )
            break

        releases = payload.get("releases", [])
        all_releases.extend(releases)
        log.info("  got %d releases (running total %d)", len(releases), len(all_releases))
        # OCDS release packages use a `links.next` pointer for pagination
        url = (payload.get("links") or {}).get("next")
        page += 1
        if url:
            time.sleep(0.5)  # be polite

    return [_normalise_release(r) for r in all_releases]


def _get_with_retry(url: str, params: dict | None = None, max_attempts: int = 3) -> requests.Response:
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
            log.warning("FTS request failed (%s), retrying in %ds", e, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _normalise_release(release: dict) -> dict:
    """Flatten an OCDS release into the shape our screener expects."""
    tender = release.get("tender") or {}
    buyer = (release.get("buyer") or {})
    planning = release.get("planning") or {}

    # OCDS 'tag' tells us the notice stage (planning, tender, award, ...)
    tags = release.get("tag") or []

    # Extract CPV codes
    cpv_codes = []
    for item in tender.get("items", []) or []:
        classification = item.get("classification") or {}
        if classification.get("scheme") == "CPV" and classification.get("id"):
            cpv_codes.append(classification["id"])

    # Deadline
    tender_period = tender.get("tenderPeriod") or {}
    deadline = tender_period.get("endDate")

    # Value
    value = tender.get("value") or {}

    # Notice URL — construct from OCID
    ocid = release.get("ocid", "")
    notice_id = ocid.replace("ocds-b5fd17-", "") if ocid else ""
    url = f"https://www.find-tender.service.gov.uk/Notice/{notice_id}" if notice_id else ""

    return {
        "source": "FTS",
        "id": ocid,
        "url": url,
        "title": tender.get("title") or release.get("title") or "",
        "description": tender.get("description") or "",
        "buyer": buyer.get("name") or "",
        "notice_type": ",".join(tags),
        "published": release.get("date", ""),
        "deadline": deadline or "",
        "value_amount": value.get("amount"),
        "value_currency": value.get("currency"),
        "cpv_codes": cpv_codes,
        "country": "GB",
        "raw": release,  # keep for later inspection
    }
