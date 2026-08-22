"""
recording — domain model package for emergency recording sessions.

Task 2 of the Player/Recorder migration: this package holds ONLY plain
domain objects (RecordingSession, RecordingSegment, RecordingStatus). It
has no dependency on PySide6, VLC, the filesystem, EmergencyRecorder, or
GlassWindow — see session.py for the full rationale. Wiring this model
into the real recording pipeline is a later task.

Task 4 adds storage.py (StoragePolicy) — a disk-space policy for
deciding whether it's safe to start a new RecordingSegment. It performs
filesystem stat() calls (shutil.disk_usage), unlike session.py, but is
still standard-library only: no PySide6, no VLC, no deletion of any
recording/session data.
"""

from .session import (
    InvalidTransitionError,
    RecordingSegment,
    RecordingSession,
    RecordingStatus,
)
from .storage import (
    DEFAULT_LOW_FREE_BYTES,
    DEFAULT_MIN_FREE_BYTES,
    DiskStatError,
    StorageCheckResult,
    StorageDecision,
    StoragePolicy,
)

__all__ = [
    "InvalidTransitionError",
    "RecordingSegment",
    "RecordingSession",
    "RecordingStatus",
    "DEFAULT_LOW_FREE_BYTES",
    "DEFAULT_MIN_FREE_BYTES",
    "DiskStatError",
    "StorageCheckResult",
    "StorageDecision",
    "StoragePolicy",
]
