"""Gmail API client — ingest TSO portal alert emails into the screening pipeline.

Setup (one-time, manual steps — see GMAIL_SETUP.md):
1. Enable Gmail API in Google Cloud Console for hvdctenderscreening@gmail.com
2. Create OAuth2 Desktop app credentials, download credentials JSON
3. Run scripts/gmail_auth.py locally ONCE to generate refresh_token
4. Add GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN as GitHub secrets
5. In Gmail, set up a filter to label incoming TSO portal emails with "HVDC-Alerts"

This module runs in GitHub Actions using the three secrets to refresh an access
token, list messages with the label, fetch their bodies, and normalise them
into the shape the screener understands.
"""
from __future__ import annotations

import base64
import email
import html
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email import policy
from typing import Any

import requests

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
USER_AGENT = "hvdc-tender-screening/3.0"
REQUEST_TIMEOUT = 30


def fetch_gmail_notices(
    days_lookback: int = 3,
    label: str = "HVDC-Alerts",
    trusted_senders: list[str] | None = None,
) -> list[dict]:
    """Fetch recent alert emails matching the given label.

    Returns notices in the common shape. Returns empty list if Gmail
    credentials are not configured (so the tool still runs without Gmail).
    """
    client_id = os.environ.get("GMAIL_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        log.info("Gmail credentials not configured — skipping Gmail ingestion")
        return []

    trusted_senders = trusted_senders or []

    try:
        access_token = _refresh_access_token(client_id, client_secret, refresh_token)
    except Exception as e:
        log.exception("Failed to refresh Gmail access token: %s", e)
        return []

    since = (datetime.now(timezone.utc) - timedelta(days=days_lookback)).strftime("%Y/%m/%d")
    query = f'label:{label} after:{since}'

    log.info("Gmail query: %s", query)
    message_ids = _list_messages(access_token, query)
    log.info("Gmail: %d matching messages", len(message_ids))

    notices = []
    for i, mid in enumerate(message_ids, 1):
        try:
            msg = _get_message(access_token, mid)
            notice = _parse_message(msg, trusted_senders)
            if notice:
                notices.append(notice)
        except Exception as e:
            log.warning("Failed to fetch Gmail message %s: %s", mid, e)
        if i % 20 == 0:
            time.sleep(0.5)  # mild rate-limit politeness

    return notices


def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _list_messages(access_token: str, query: str, max_results: int = 200) -> list[str]:
    ids = []
    page_token = None
    while len(ids) < max_results:
        params = {"q": query, "maxResults": min(100, max_results - len(ids))}
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(
            f"{GMAIL_API}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        for m in data.get("messages", []):
            ids.append(m["id"])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids


def _get_message(access_token: str, message_id: str) -> dict:
    resp = requests.get(
        f"{GMAIL_API}/messages/{message_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"format": "full"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_message(msg: dict, trusted_senders: list[str]) -> dict | None:
    """Extract subject, sender, body, URL and return a normalised notice."""
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    sender = headers.get("from", "")
    subject = headers.get("subject", "").strip()
    date_str = headers.get("date", "")

    # Trust check — sender must match one of the trusted domains/addresses
    if trusted_senders and not _is_trusted(sender, trusted_senders):
        log.debug("Skipping email from untrusted sender: %s", sender)
        return None

    # Pull body text (plain preferred, else strip HTML)
    body_text = _extract_body(payload)

    # Try to find the main URL in the email (most alerts link to the portal)
    url = _extract_first_url(body_text) or ""

    # Try to find a deadline in the text
    deadline = _extract_deadline(body_text) or ""

    # Normalise
    published_dt = _parse_email_date(date_str)
    published_iso = published_dt.isoformat() if published_dt else ""

    buyer = _infer_buyer(sender)

    return {
        "source": "Gmail",
        "id": f"gmail-{msg.get('id', '')}",
        "url": url,
        "title": subject,
        "description": body_text[:4000],  # cap to keep archive sane
        "buyer": buyer,
        "notice_type": "Email alert",
        "published": published_iso,
        "deadline": deadline,
        "value_amount": None,
        "value_currency": None,
        "cpv_codes": [],
        "country": "",
        "raw": {"from": sender, "subject": subject, "snippet": msg.get("snippet", "")[:200]},
    }


def _is_trusted(sender: str, trusted_senders: list[str]) -> bool:
    sender_lower = sender.lower()
    for t in trusted_senders:
        if t.lower() in sender_lower:
            return True
    return False


def _extract_body(payload: dict) -> str:
    """Return the best available plain-text body, recursively walking parts."""
    text = _walk_for_mime(payload, "text/plain")
    if text:
        return text.strip()
    # Fallback: strip HTML
    htmlbody = _walk_for_mime(payload, "text/html")
    if htmlbody:
        return _strip_html(htmlbody).strip()
    return ""


def _walk_for_mime(part: dict, mime_type: str) -> str:
    if part.get("mimeType") == mime_type:
        data = (part.get("body") or {}).get("data")
        if data:
            return _b64url_decode(data)
    for sub in part.get("parts", []) or []:
        found = _walk_for_mime(sub, mime_type)
        if found:
            return found
    return ""


def _b64url_decode(s: str) -> str:
    try:
        return base64.urlsafe_b64decode(s.encode("ascii") + b"==").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _strip_html(htmlbody: str) -> str:
    # Remove scripts and styles entirely
    htmlbody = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", htmlbody, flags=re.DOTALL | re.IGNORECASE)
    # Replace breaks with newlines for readability
    htmlbody = re.sub(r"<br\s*/?>", "\n", htmlbody, flags=re.IGNORECASE)
    htmlbody = re.sub(r"</p>", "\n", htmlbody, flags=re.IGNORECASE)
    # Strip all other tags
    text = re.sub(r"<[^>]+>", " ", htmlbody)
    # Collapse whitespace and decode entities
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Re-introduce newlines for readability
    return text


def _extract_first_url(text: str) -> str:
    m = re.search(r"https?://[^\s<>\"'\)]+", text)
    return m.group(0).rstrip(".,);") if m else ""


def _extract_deadline(text: str) -> str:
    """Best-effort deadline extraction. Returns ISO date if confident, else ''."""
    # Common patterns: "deadline: 12 May 2026", "closing date: 15/05/2026"
    patterns = [
        r"deadline[:\s]+(\d{1,2}[/\-\s][A-Za-z0-9]+[/\-\s]\d{2,4})",
        r"closing\s+date[:\s]+(\d{1,2}[/\-\s][A-Za-z0-9]+[/\-\s]\d{2,4})",
        r"submission\s+deadline[:\s]+(\d{1,2}[/\-\s][A-Za-z0-9]+[/\-\s]\d{2,4})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def _parse_email_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s)
    except Exception:
        return None


def _infer_buyer(sender: str) -> str:
    """Infer the buyer name from the sender. Falls back to sender display name."""
    sender_lower = sender.lower()
    mapping = [
        ("tennet", "TenneT"),
        ("tenderned", "TenderNed (NL)"),
        ("mercell", "Mercell portal"),
        ("jaggaer", "Jaggaer portal"),
        ("in-tend", "In-tend portal"),
        ("sse.com", "SSEN"),
        ("nationalgrid", "National Grid / NESO"),
        ("50hertz", "50Hertz"),
        ("ebrd.com", "EBRD"),
        ("amprion", "Amprion"),
        ("transnetbw", "TransnetBW"),
        ("energinet", "Energinet"),
        ("statnett", "Statnett"),
        ("elia", "Elia"),
        ("terna", "Terna"),
        ("ree.es", "Red Eléctrica"),
    ]
    for needle, name in mapping:
        if needle in sender_lower:
            return name
    # Extract display name or email
    m = re.match(r'"?([^"<]+?)"?\s*<', sender)
    if m:
        return m.group(1).strip()
    return sender or "Email sender"
