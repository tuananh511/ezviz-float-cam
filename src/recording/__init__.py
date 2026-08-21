"""
recording — domain model package for emergency recording sessions.

Task 2 of the Player/Recorder migration: this package holds ONLY plain
domain objects (RecordingSession, RecordingSegment, RecordingStatus). It
has no dependency on PySide6, VLC, the filesystem, EmergencyRecorder, or
GlassWindow — see session.py for the full rationale. Wiring this model
into the real recording pipeline is a later task.
"""

from .session import (
    InvalidTransitionError,
    RecordingSegment,
    RecordingSession,
    RecordingStatus,
)

__all__ = [
    "InvalidTransitionError",
    "RecordingSegment",
    "RecordingSession",
    "RecordingStatus",
]
