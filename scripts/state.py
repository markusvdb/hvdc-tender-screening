"""Read/write persisted state — last run date, seen IDs, rolling archive."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent.parent / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

LAST_RUN_PATH = STATE_DIR / "last_run.json"
ARCHIVE_PATH = STATE_DIR / "tenders.json"


def load_archive() -> list[dict]:
    if ARCHIVE_PATH.exists():
        try:
            return json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("Archive corrupt, starting fresh")
    return []


def save_archive(tenders: list[dict], archive_days: int = 90) -> None:
    """Save tenders to the rolling archive, pruning anything older than N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=archive_days)
    cutoff_iso = cutoff.isoformat()

    # Merge by ID — new entries overwrite old
    existing = {t.get("id"): t for t in load_archive() if t.get("id")}
    for t in tenders:
        tid = t.get("id")
        if tid:
            # Strip the bulky raw field before archiving to save space
            slim = {k: v for k, v in t.items() if k != "raw"}
            slim["first_seen"] = existing.get(tid, {}).get("first_seen") or datetime.now(timezone.utc).isoformat()
            slim["last_seen"] = datetime.now(timezone.utc).isoformat()
            existing[tid] = slim

    # Prune old
    kept = [t for t in existing.values() if (t.get("last_seen") or t.get("published") or "9999") > cutoff_iso]
    kept.sort(key=lambda t: t.get("published") or "", reverse=True)

    ARCHIVE_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Archive now contains %d tenders", len(kept))


def load_last_run() -> dict:
    if LAST_RUN_PATH.exists():
        try:
            return json.loads(LAST_RUN_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"last_run": None, "seen_ids": []}


def save_last_run(seen_ids: list[str]) -> None:
    LAST_RUN_PATH.write_text(
        json.dumps({
            "last_run": datetime.now(timezone.utc).isoformat(),
            "seen_ids": seen_ids[-5000:],  # keep last 5000
        }, indent=1),
        encoding="utf-8",
    )
