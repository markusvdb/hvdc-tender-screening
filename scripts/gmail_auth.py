"""One-time Gmail OAuth setup — generate a refresh token for the bot.

Run this ONCE on your laptop to get a refresh token. Copy the printed token
into your GitHub secret GMAIL_REFRESH_TOKEN. After that, the scheduled
workflow refreshes access tokens automatically.

Prereqs:
  1. You have downloaded your OAuth2 Desktop client credentials JSON from
     Google Cloud Console (see GMAIL_SETUP.md).
  2. Python + requests installed locally: `pip install requests`
  3. You know the client_id and client_secret from that JSON.

Usage:
  python scripts/gmail_auth.py
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import webbrowser

import requests

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT = "urn:ietf:wg:oauth:2.0:oob"  # out-of-band flow (paste code)


def main() -> int:
    print("=" * 70)
    print("Gmail OAuth setup for hvdc-tender-screening")
    print("=" * 70)
    print()
    client_id = input("Paste your OAuth2 Client ID: ").strip()
    client_secret = input("Paste your OAuth2 Client Secret: ").strip()

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print()
    print("Open this URL in your browser and sign in as hvdctenderscreening@gmail.com:")
    print()
    print(auth_url)
    print()
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    code = input("Paste the authorisation code Google gave you: ").strip()

    resp = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"ERROR {resp.status_code}: {resp.text}")
        return 1

    tokens = resp.json()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("ERROR: no refresh_token in response. Did you pass prompt=consent?")
        print(json.dumps(tokens, indent=2))
        return 1

    print()
    print("=" * 70)
    print("SUCCESS")
    print("=" * 70)
    print()
    print("Add these three to your GitHub repo as Actions secrets:")
    print(f"  GMAIL_CLIENT_ID     = {client_id}")
    print(f"  GMAIL_CLIENT_SECRET = {client_secret}")
    print(f"  GMAIL_REFRESH_TOKEN = {refresh_token}")
    print()
    print("After adding them, your next daily run will ingest Gmail alerts.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
