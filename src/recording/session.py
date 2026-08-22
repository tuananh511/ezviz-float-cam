"""
recording/session.py — RecordingSession / RecordingSegment domain model.

Task 2 of the Player/Recorder migration (see architecture audit notes).
This module is intentionally a PLAIN domain model with no side effects:

- standard library only (uuid, dataclasses, datetime, enum, typing)
- no PySide6 (no QObject/Signal — this is not wired into Qt yet)
- no VLC
- no filesystem I/O
- no dependency on EmergencyRecorder or GlassWindow

It does not record anything and does not talk to a camera. It exists so
the STATE and DATA a recording session needs to track can be reasoned
about and tested on its own, before the next task wires it into the real
recording pipeline (src/recorder.py is not touched here).

All datetimes are timezone-aware UTC (datetime.now(timezone.utc)) —
naive datetimes are not used anywhere in this module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecordingStatus(Enum):
    """Lifecycle states for one RecordingSession."""

    IDLE = "IDLE"
    STARTING = "STARTING"
    RECORDING = "RECORDING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    DISK_FULL = "DISK_FULL"
    RECOVERABLE = "RECOVERABLE"


# Only the transitions actually needed today (per Task 2 scope, extended
# in Task 5 to allow STARTING -> DISK_FULL so a storage-policy check made
# before the first segment is created can end the session in DISK_FULL
# without first passing through RECORDING; extended in Task 8 to allow
# STOPPING -> FAILED so crash/session recovery can reconcile a session
# that was persisted mid-STOPPING when its process terminated
# unexpectedly, without inventing an intermediate STOPPED it never
# actually reached). Anything not listed here is rejected by
# RecordingSession.transition_to().
_ALLOWED_TRANSITIONS: dict[RecordingStatus, frozenset[RecordingStatus]] = {
    RecordingStatus.IDLE: frozenset({RecordingStatus.STARTING}),
    RecordingStatus.STARTING: frozenset(
        {RecordingStatus.RECORDING, RecordingStatus.FAILED, RecordingStatus.DISK_FULL}
    ),
    RecordingStatus.RECORDING: frozenset(
        {
            RecordingStatus.STOPPING,
            RecordingStatus.FAILED,
            RecordingStatus.DISK_FULL,
        }
    ),
    RecordingStatus.STOPPING: frozenset(
        {RecordingStatus.STOPPED, RecordingStatus.FAILED}
    ),
    RecordingStatus.STOPPED: frozenset(),
    RecordingStatus.FAILED: frozenset({RecordingStatus.RECOVERABLE}),
    RecordingStatus.DISK_FULL: frozenset(),
    RecordingStatus.RECOVERABLE: frozenset(),
}

# Statuses at which a session stops being "active" — ended_at is set when
# entering one of these (never reset afterwards by a later transition,
# e.g. FAILED -> RECOVERABLE keeps the ended_at recorded at FAILED time).
_END_STATES: frozenset[RecordingStatus] = frozenset(
    {RecordingStatus.STOPPED, RecordingStatus.FAILED, RecordingStatus.DISK_FULL}
)


class InvalidTransitionError(ValueError):
    """Raised when a RecordingSession status transition is not allowed."""


@dataclass
class RecordingSegment:
    """One physical recording segment (e.g. one output file) belonging to
    a RecordingSession. A session may have exactly one segment (today's
    EmergencyRecorder writes a single .mkv per session) or several, if a
    future implementation splits long recordings — this model does not
    assume either way.
    """

    path: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    size_bytes: int = 0
    completed: bool = False

    def mark_completed(
        self,
        *,
        ended_at: Optional[datetime] = None,
        size_bytes: Optional[int] = None,
    ) -> None:
        """Transition this segment from incomplete to completed."""
        self.ended_at = ended_at or _utcnow()
        if size_bytes is not None:
            if size_bytes < 0:
                raise ValueError("size_bytes must be non-negative")
            self.size_bytes = size_bytes
        self.completed = True


@dataclass
class RecordingSession:
    """One emergency recording session — the thing a future Recorder
    creates, updates, and closes out. Pure data + state-transition rules;
    it does not itself start/stop VLC, touch the filesystem, or know
    anything about the UI.

    Emergency recordings default to protected=True: an emergency session
    should not be casually auto-deleted by future retention/cleanup logic
    without an explicit decision to unprotect it.
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=_utcnow)
    ended_at: Optional[datetime] = None
    status: RecordingStatus = RecordingStatus.IDLE
    protected: bool = True
    segments: List[RecordingSegment] = field(default_factory=list)
    total_bytes: int = 0
    error: Optional[str] = None

    def transition_to(
        self,
        new_status: RecordingStatus,
        *,
        error: Optional[str] = None,
        ended_at: Optional[datetime] = None,
    ) -> None:
        """Move to new_status if that transition is allowed from the
        current status; raise InvalidTransitionError otherwise.

        ended_at is set automatically (to `ended_at` if given, else "now")
        when entering STOPPED, FAILED, or DISK_FULL, and is left untouched
        by any other transition — including FAILED -> RECOVERABLE, which
        keeps the ended_at recorded when the session originally failed.

        `error` (an error message or a short reason) is stored verbatim
        when given; it is never cleared automatically.
        """
        allowed = _ALLOWED_TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition RecordingSession from "
                f"{self.status.name} to {new_status.name}"
            )

        self.status = new_status

        if new_status in _END_STATES:
            self.ended_at = ended_at if ended_at is not None else _utcnow()

        if error is not None:
            self.error = error

    def add_segment(self, segment: RecordingSegment) -> None:
        self.segments.append(segment)

    def add_bytes(self, n: int) -> None:
        """Increment total_bytes by n (e.g. as new data is flushed)."""
        if n < 0:
            raise ValueError("n must be non-negative")
        self.total_bytes += n

    def set_total_bytes(self, value: int) -> None:
        """Set total_bytes to an absolute value (e.g. from a filesystem
        stat of the output file). Rejects negative values; this model does
        no filesystem I/O itself, the caller is responsible for measuring.
        """
        if value < 0:
            raise ValueError("total_bytes must be non-negative")
        self.total_bytes = value

    def recalculate_total_bytes(self) -> int:
        """Task 4: recompute total_bytes as the sum of size_bytes across
        only the COMPLETED segments in `segments`. A segment that has not
        been marked completed yet is still being written — its current
        size_bytes (0, per the RecordingSegment default) is not final and
        must not be counted, or total_bytes would understate/misstate the
        session's real size while a segment is mid-write.

        This does not run automatically on add_segment()/mark_completed()
        (this model has no callbacks) — callers (the future recorder
        integration) call this after finalizing a segment. Returns the
        recomputed total_bytes for convenience.
        """
        total = sum(segment.size_bytes for segment in self.segments if segment.completed)
        self.set_total_bytes(total)
        return self.total_bytes

    def is_active(self) -> bool:
        """True while the session has not reached STOPPED/FAILED/DISK_FULL
        (RECOVERABLE is a resolved-but-not-active terminal-ish state too)."""
        return self.status not in _END_STATES and self.status != RecordingStatus.RECOVERABLE
