# Gmail ingestion setup

This is a one-time ~30-minute setup. You need: the `hvdctenderscreening@gmail.com` account,
Python installed on your laptop, and a web browser.

## Part 1: Enable Gmail API in Google Cloud (10 min)

1. Go to https://console.cloud.google.com/
2. Sign in as `hvdctenderscreening@gmail.com`
3. Top bar → click the project dropdown → **New project** → name it `hvdc-tender-screening` → Create
4. Left menu → **APIs & Services** → **Library**
5. Search "Gmail API" → click it → **Enable**

## Part 2: Create OAuth2 credentials (10 min)

1. Left menu → **APIs & Services** → **OAuth consent screen**
2. User type: **External** → Create
3. Fill in:
   - App name: `HVDC tender screening`
   - User support email: `hvdctenderscreening@gmail.com`
   - Developer email: same
4. Scopes step → click **Add or remove scopes** → filter `gmail` → tick `gmail.readonly` → Update → Save
5. Test users step → **Add users** → add `hvdctenderscreening@gmail.com` → Save
6. Back to dashboard. Left menu → **Credentials** → **+ Create credentials** → **OAuth client ID**
7. Application type: **Desktop app**, name: `hvdc-bot`, Create
8. A dialog shows your **Client ID** and **Client Secret**. Copy both — you'll need them in Part 3.

## Part 3: Generate refresh token locally (5 min)

On your laptop, open a terminal (Windows: Command Prompt or PowerShell):

```
pip install requests
python scripts/gmail_auth.py
```

The script will:
- Ask for the Client ID and Client Secret (paste them in)
- Open your browser to a Google sign-in page — sign in as `hvdctenderscreening@gmail.com`
- Show "Google hasn't verified this app" — click **Advanced** → **Go to HVDC tender screening (unsafe)** (safe because you created it)
- Grant the `gmail.readonly` permission
- Give you an authorisation code — copy it and paste back into the script
- Print a `refresh_token`

## Part 4: Add 3 new GitHub secrets

Repo → Settings → Secrets and variables → Actions → New repository secret:

| Name | Value |
|------|-------|
| `GMAIL_CLIENT_ID` | from Part 2 |
| `GMAIL_CLIENT_SECRET` | from Part 2 |
| `GMAIL_REFRESH_TOKEN` | from Part 3 |

## Part 5: Set up the Gmail label filter (5 min)

1. Go to https://mail.google.com/ logged in as `hvdctenderscreening@gmail.com`
2. Settings (⚙ gear) → **See all settings** → **Labels** tab → **Create new label** → name: `HVDC-Alerts` → Create
3. **Filters and Blocked Addresses** tab → **Create a new filter**
4. In the **From** field, paste:
   ```
   mercell.com OR tenderned.nl OR jaggaer.com OR in-tend.co.uk OR sap.com OR ariba.com OR tennet.eu OR sse.com OR nationalgrid.com OR 50hertz.com OR ebrd.com
   ```
5. Click **Create filter**
6. Tick **Apply the label** → `HVDC-Alerts`, and **Never send to Spam**
7. Click **Create filter**

## Part 6: Register on the TSO portals you care about

This is manual but one-time. For each portal, create a supplier account with `hvdctenderscreening@gmail.com`, set alert keywords to "HVDC", "converter station", "transmission study", "owner's engineer", and enable email notifications.

Key portals for HVDC services work:

| TSO / region | Portal |
|---|---|
| TenneT (DE/NL) | https://www.tennet.eu/purchasing (links to Mercell/TenderNed) |
| National Grid / NESO (UK) | https://www.nationalgrid.com/suppliers |
| SSEN Transmission (UK) | https://www.ssen-transmission.co.uk/suppliers/ |
| 50Hertz (DE) | https://www.50hertz.com/en/SupplierPortal |
| Amprion (DE) | https://www.amprion.net/Suppliers |
| TransnetBW (DE) | https://www.transnetbw.com/en/suppliers |
| Energinet (DK) | https://en.energinet.dk/About-us/Suppliers/ |
| Statnett (NO) | https://www.statnett.no/en/about-statnett/suppliers/ |
| Elia (BE) | https://www.elia.be/en/suppliers |
| Terna (IT) | https://portaleacquisti.terna.it |
| Red Eléctrica (ES) | https://www.ree.es/en/suppliers |
| EBRD | https://ecepp.ebrd.com |

## Verification

After Parts 1-6:

1. Go to GitHub Actions → Daily screening → Run workflow
2. Check the log — you should see `Gmail: N matching messages` where N ≥ 0
3. If N > 0, those emails will appear on your dashboard with source "Gmail"

## If Gmail stops working

The most likely cause is OAuth consent expiry (Google expires unverified-app tokens every 7 days *during testing status*). To publish your app out of testing: OAuth consent screen → **Publish app**. This makes the token permanent but requires nothing else — your app doesn't need Google verification for personal use.
