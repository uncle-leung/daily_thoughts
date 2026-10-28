#!/usr/bin/env python3
"""Send each daily letter once, inside a short window after its Shanghai slot."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
GRACE = timedelta(minutes=100)
SLOTS = {
    "trending": ("09:00", "18:00"),
    "events": ("09:15", "18:15"),
    "ideas": ("09:30", "18:30"),
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


def marker_path(kind: str, now: datetime, slot: str) -> Path:
    return state_root() / now.date().isoformat() / f"{kind}-{slot.replace(':', '')}"


def begin_send(kind: str, now: datetime | None = None, force: bool | None = None) -> str | None:
    """Return the slot when a letter should go out. None means skip."""
    current = _stamp(now)
    if force is None:
        force = os.environ.get("MAIL_FORCE", "").strip() == "1"
    slot = slot_name(kind, current)
    hour, minute = int(slot[:2]), int(slot[3:])
    start = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    path = marker_path(kind, current, slot)
    if path.exists() and not force:
        print(f"already sent {kind} {slot}")
        return None
    if not force and not (start <= current < start + GRACE):
        print(f"skip {kind} {slot}: outside the {int(GRACE.total_seconds() // 60)} minute window")
        return None
    return slot


def mark_sent(kind: str, now: datetime, slot: str) -> None:
    path = marker_path(kind, now, slot)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_stamp(now).isoformat() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    del argv
    root = Path(__file__).resolve().parents[1]
    commands = (
        [
            sys.executable,
            "scripts/github_trending_digest.py",
            "--send",
            "--html-out",
            "digests/latest.html",
            "--text-out",
            "digests/latest.txt",
        ],
        [
            sys.executable,
            "scripts/major_events.py",
            "--send",
            "--html-out",
            "digests/events.html",
            "--text-out",
            "digests/events.txt",
        ],
        [
            sys.executable,
            "scripts/daily_ideas.py",
            "--send",
            "--html-out",
            "digests/ideas.html",
            "--text-out",
            "digests/ideas.txt",
        ],
    )
    failed = 0
    for command in commands:
        print("run " + " ".join(command))
        if subprocess.run(command, cwd=root).returncode != 0:
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
