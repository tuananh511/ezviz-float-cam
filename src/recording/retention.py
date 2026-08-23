"""
recording/retention.py — retention-eligibility policy for previously
persisted emergency recording sessions (Task 13 of the Player/Recorder
migration).

Like session.py, storage.py, metadata.py, recovery.py, and startup.py,
this module is deliberately plain:

- standard library only (dataclasses, datetime, typing)
- no PySide6, no vlc — no import anywhere in this module touches either
- no filesystem I/O of any kind — this module never lists a directory,
  never stat()s a file, never deletes/renames/moves anything
- no auto-run wiring — it is not called from recorder.py, main.py, any
  UI, startup, or StoragePolicy; wiring it into a live cleanup path is a
  later task, same two-step pattern as storage.py (Task 4) -> Task 5,
  metadata.py (Task 6) -> Task 7, and recovery.py/startup.py (Task 8/9)
  -> Task 11

--- What this module does NOT do ---

It does not delete a single file. It does not decide *when* cleanup
should run, *how much* to reclaim, or *what* the retention window should
be — this repository does not define a retention period, a disk-space
threshold, or a session-count limit anywhere today (StoragePolicy's
DEFAULT_MIN_FREE_BYTES/DEFAULT_LOW_FREE_BYTES govern refusing NEW
segments when disk is low, not reclaiming OLD ones — see storage.py's
own "không thêm auto-delete recording cũ (ngoài scope Task 4)" note).
Inventing such a default here would be scope creep this module
deliberately avoids: the caller must always supply an explicit cutoff
via RetentionCriteria: there is no default RetentionCriteria.

--- What "eligible for cleanup" means here ---

A RecordingSession is eligible only when ALL of the following hold:

1. `session.status` is one of the TERMINAL statuses — STOPPED, FAILED,
   DISK_FULL. This mirrors recovery.py's own `_TERMINAL_STATUSES` (and
   session.py's `_END_STATES`) exactly; it is not redefined or widened
   here. In particular STARTING/RECORDING/STOPPING (still potentially
   live) are never eligible, and RECOVERABLE/IDLE are also never
   eligible — this module does not treat them as terminal, consistent
   with recovery.py already excluding RECOVERABLE from its own terminal
   set.
2. `session.protected` is False. `protected` defaults to True on every
   RecordingSession (see session.py) specifically so emergency
   recordings are never casually swept up by cleanup logic without an
   explicit decision to unprotect them first — that decision is made
   entirely outside this module; this module only reads the flag.
3. `session.ended_at` is not None AND is at or before
   `criteria.older_than`. A terminal session with no ended_at (should
   not normally happen — session.py sets ended_at when entering an end
   state — but defensively handled here) is never eligible: with no
   reliable age to compare, this module does not guess one, matching
   recovery.py's own refusal to fabricate timestamps.

Everything else about a session (segment count, total_bytes, error
text, session_id) is irrelevant to eligibility and is never inspected
here.
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


# Mirrors recovery.py's `_TERMINAL_STATUSES` / session.py's `_END_STATES`
# exactly. Not imported from either: both are module-private constants,
# and the set is a stable property of the RecordingStatus enum itself —
# redefining it here keeps this module's import graph minimal (session.py
# only) without reaching into another module's private names.
_TERMINAL_STATUSES = frozenset(
    {
        RecordingStatus.STOPPED,
        RecordingStatus.FAILED,
        RecordingStatus.DISK_FULL,
    }
)


@dataclass(frozen=True)
class RetentionCriteria:
    """Caller-supplied retention cutoff. There is no default instance and
    no default for `older_than` — this repository does not define a
    retention period anywhere, so one is never invented here; the caller
    (a later task) must always decide and pass it explicitly.

    `older_than` must be a timezone-aware UTC datetime, consistent with
    every other datetime in the `recording` package (see session.py's
    `_utcnow()`). A session's `ended_at` at or before this instant is
    old enough to be eligible (subject to the status/protected checks in
    is_eligible_for_cleanup).
    """

    older_than: datetime


def is_eligible_for_cleanup(
    session: RecordingSession, criteria: RetentionCriteria
) -> bool:
    """Decide whether a single RecordingSession is eligible for cleanup
    under `criteria`. Read-only: never mutates `session`, never touches
    the filesystem, never deletes anything — this function only answers
    a yes/no question for a caller to act on (or not) elsewhere.

    See the module docstring for the exact three conditions checked.
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
    """Filter `sessions` down to those eligible for cleanup under
    `criteria`, preserving input order. A thin wrapper around
    is_eligible_for_cleanup — no additional logic, no deduplication, no
    sorting. Read-only, same guarantees as is_eligible_for_cleanup.
    """
    return [s for s in sessions if is_eligible_for_cleanup(s, criteria)]
