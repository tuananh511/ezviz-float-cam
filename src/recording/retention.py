"""
recording/retention.py — retention-eligibility policy for persisted
emergency recording sessions (Task 13 of the Player/Recorder migration).

Stdlib-only, no PySide6/vlc, no filesystem I/O — same discipline as
session.py, storage.py, metadata.py, recovery.py, and startup.py. Not
wired into recorder.py, main.py, any UI, startup, or StoragePolicy;
that remains a later task, same standalone-first pattern those modules
used before their own integration tasks.

Never deletes a file. Never defines a retention period, disk threshold,
or session-count limit itself — none exists elsewhere in this repo, and
none is invented here; the caller always supplies an explicit cutoff via
RetentionCriteria.

See is_eligible_for_cleanup() for the exact eligibility rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List

from .session import RecordingSession, RecordingStatus

__all__ = [
    "RetentionCriteria",
    "is_eligible_for_cleanup",
    "find_eligible_sessions",
]


# Mirrors recovery.py's private _TERMINAL_STATUSES / session.py's
# _END_STATES; redefined here since both are module-private.
_TERMINAL_STATUSES = frozenset(
    {
        RecordingStatus.STOPPED,
        RecordingStatus.FAILED,
        RecordingStatus.DISK_FULL,
    }
)


@dataclass(frozen=True)
class RetentionCriteria:
    """Caller-supplied retention cutoff — no default, this repo defines
    no retention period, so none is invented here. `older_than` must be
    a timezone-aware UTC datetime, like every other datetime in this
    package (see session.py's `_utcnow()`).
    """

    older_than: datetime


def is_eligible_for_cleanup(
    session: RecordingSession, criteria: RetentionCriteria
) -> bool:
    """True iff session.status is terminal (STOPPED/FAILED/DISK_FULL —
    STARTING/RECORDING/STOPPING are never eligible, nor are IDLE/
    RECOVERABLE), session.protected is False, and session.ended_at is
    not None and is at or before criteria.older_than. Read-only: never
    mutates `session`, never touches the filesystem or deletes anything.
    """
    if session.status not in _TERMINAL_STATUSES:
        return False
    if session.protected:
        return False
    if session.ended_at is None:
        return False
    return session.ended_at <= criteria.older_than


def find_eligible_sessions(
    sessions: Iterable[RecordingSession], criteria: RetentionCriteria
) -> List[RecordingSession]:
    """`sessions` filtered to those eligible for cleanup, order
    preserved. Read-only, same guarantees as is_eligible_for_cleanup.
    """
    return [s for s in sessions if is_eligible_for_cleanup(s, criteria)]
