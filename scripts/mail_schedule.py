#!/usr/bin/env python3
"""Send each daily letter once, starting at its Shanghai time.

GitHub Actions starts scheduled work late and sometimes skips a tick.
A morning letter stays open from its clock time until 14:00. An evening
letter stays open until 08:00 the next morning, so a run after midnight
still sends last night's letters. Each mailbox is sent at most once per slot.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
# 14:00 Shanghai is 06:00 UTC, the same cutoff the letter body uses to
# choose morning versus evening copy. Evening stays open until the next 08:00.
MORNING_OPEN = (8, 0)
MORNING_CLOSE = (14, 0)
SLOTS = {
    "trending": ("08:00", "18:00"),
    "events": ("08:15", "18:15"),
    "ideas": ("08:30", "18:30"),
}
COMMANDS = {
    "trending": [
        "scripts/github_trending_digest.py",
        "--send",
        "--html-out",
        "digests/latest.html",
        "--text-out",
        "digests/latest.txt",
    ],
    "events": [
        "scripts/major_events.py",
        "--send",
        "--html-out",
        "digests/events.html",
        "--text-out",
        "digests/events.txt",
    ],
    "ideas": [
        "scripts/daily_ideas.py",
        "--send",
        "--html-out",
        "digests/ideas.html",
        "--text-out",
        "digests/ideas.txt",
    ],
}


def _stamp(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def state_root() -> Path:
    override = os.environ.get("MAIL_STATE_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "mail-state"


def slot_name(kind: str, now: datetime | None = None) -> str:
    morning, evening = SLOTS[kind]
    current = _stamp(now)
    return morning if current.hour < 12 else evening


def _minutes(value: datetime | tuple[int, int] | str) -> int:
    if isinstance(value, datetime):
        return value.hour * 60 + value.minute
    if isinstance(value, str):
        return int(value[:2]) * 60 + int(value[3:])
    return value[0] * 60 + value[1]


def slot_day(now: datetime, slot: str) -> date:
    """Calendar day the slot belongs to. After midnight, evening is still yesterday."""
    current = _stamp(now)
    if _minutes(slot) >= _minutes("12:00") and _minutes(current) < _minutes(MORNING_OPEN):
        return current.date() - timedelta(days=1)
    return current.date()


def due_delivery(kind: str, now: datetime | None = None) -> tuple[date, str] | None:
    """Return the unsent slot that is open now, with the day it belongs to."""
    current = _stamp(now)
    morning, evening = SLOTS[kind]
    mins = _minutes(current)
    if mins >= _minutes(evening):
        return current.date(), evening
    if _minutes(morning) <= mins < _minutes(MORNING_CLOSE):
        return current.date(), morning
    if mins < _minutes(MORNING_OPEN):
        return current.date() - timedelta(days=1), evening
    return None


def marker_path(kind: str, now: datetime, slot: str) -> Path:
    return state_root() / slot_day(now, slot).isoformat() / f"{kind}-{slot.replace(':', '')}"


_ADDRESS_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def parse_addresses(*chunks: str) -> list[str]:
    """Split mailbox lists. Order is kept, duplicates and fragments without @ are dropped."""
    found: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        for part in re.split(r"[,，、;；\s]+", chunk or ""):
            address = part.strip().strip("<>")
            if not _ADDRESS_RE.fullmatch(address):
                continue
            key = address.casefold()
            if key in seen:
                continue
            seen.add(key)
            found.append(address)
    return found


def recipient_list() -> list[str]:
    """Sending mailbox first, then extra recipients. Extras are never the SMTP login."""
    return parse_addresses(
        os.environ.get("DIGEST_TO", ""),
        os.environ.get("DIGEST_ALSO", ""),
    )


def mailbox_key(address: str) -> str:
    """Stable id for a mailbox. The address itself stays out of the repo and the logs."""
    return hashlib.sha256(address.strip().casefold().encode("utf-8")).hexdigest()[:16]


def require_recipient() -> str | None:
    """Mailboxes for this run. Empty means do not fetch or send."""
    found = recipient_list()
    if found:
        return ", ".join(found)
    print("DIGEST_TO is not set. Refusing to send.", file=sys.stderr)
    return None


def _delivery_keys(path: Path) -> set[str] | None:
    """Mailboxes already delivered, by key.

    None means an older marker that finished the whole slot for whoever was configured then.
    """
    if not path.exists():
        return set()
    keys = {
        line[3:].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("to ") and line[3:].strip()
    }
    if not keys:
        return None
    return keys


def slot_satisfied(kind: str, now: datetime, slot: str) -> bool:
    recorded = _delivery_keys(marker_path(kind, now, slot))
    if recorded is None:
        return True
    everyone = recipient_list()
    if not everyone:
        return False
    return all(mailbox_key(item) in recorded for item in everyone)


def pending_recipients(kind: str, now: datetime, slot: str, *, force: bool = False) -> list[str]:
    everyone = recipient_list()
    if force:
        return everyone
    recorded = _delivery_keys(marker_path(kind, now, slot))
    if recorded is None:
        return []
    return [item for item in everyone if mailbox_key(item) not in recorded]


def begin_send(kind: str, now: datetime | None = None, force: bool | None = None) -> str | None:
    """Return the slot when a letter should go out. None means skip."""
    current = _stamp(now)
    if force is None:
        force = os.environ.get("MAIL_FORCE", "").strip() == "1"
    if force:
        slot = slot_name(kind, current)
    else:
        found = due_delivery(kind, current)
        if found is None:
            morning, evening = SLOTS[kind]
            print(f"skip {kind}: waiting for {morning} or {evening}")
            return None
        slot = found[1]
    if slot_satisfied(kind, current, slot):
        print(f"already sent {kind} {slot}")
        return None
    return slot


def letters_due(now: datetime | None = None) -> list[str]:
    current = _stamp(now)
    return [kind for kind in SLOTS if begin_send(kind, current)]


def mark_sent(kind: str, now: datetime, slot: str, recipients: list[str] | None = None) -> None:
    path = marker_path(kind, now, slot)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    if not lines or lines[0].startswith("to "):
        lines.insert(0, _stamp(now).isoformat())
    if recipients:
        existing = set(lines)
        for address in recipients:
            token = "to " + mailbox_key(address)
            if token not in existing:
                lines.append(token)
                existing.add(token)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    del argv
    due = letters_due()
    if not due:
        return 0
    if require_recipient() is None:
        return 1
    root = Path(__file__).resolve().parents[1]
    failed = 0
    for kind in due:
        command = [sys.executable, *COMMANDS[kind]]
        print("run " + " ".join(command), flush=True)
        if subprocess.run(command, cwd=root).returncode != 0:
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
