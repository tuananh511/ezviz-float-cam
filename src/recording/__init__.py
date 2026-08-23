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

Task 6 adds metadata.py (RecordingMetadataStore) — save()/load()
persistence of a RecordingSession to a `session.json` file inside a
session directory, using atomic replacement (temp file + os.replace())
and strict validation on load. Still standard-library only: no
PySide6, no VLC. Not yet wired into EmergencyRecorder.

Task 8 adds recovery.py (recover_all/recover_session) — a standalone
reconciliation pass over previously persisted session directories after
an unexpected application/process termination. It reads session.json +
existing .mkv segment evidence and reconciles interrupted sessions
(STARTING/RECORDING/STOPPING) into a terminal FAILED state; it never
deletes a file and never resumes VLC/RTSP recording automatically. Also
standard-library only: no PySide6, no VLC. Not wired into any
auto-run-at-startup path — a caller decides when/whether to invoke it.

Task 9 adds startup.py (run_startup_recovery) — the single public entry
point a later task calls to run Task 8's recover_all() at application
startup, before a new EmergencyRecorder session can start. It resolves
the directory to scan (falling back to the same default recorder.py
falls back to) and otherwise only delegates to recover_all(); no
recovery/discovery logic is reimplemented. Still standard-library only:
no PySide6, no VLC. Does not wire itself into main.py/glass_window.py —
that remains a later task.

Task 13 adds retention.py (is_eligible_for_cleanup/find_eligible_sessions)
— a standalone policy that decides whether a persisted RecordingSession
is eligible for cleanup (terminal status + protected=False + old enough
per a caller-supplied cutoff). It never deletes a file, never lists a
directory, and is not wired into recorder.py, main.py, any UI, startup,
or StoragePolicy — same standalone-first pattern as storage.py/
metadata.py/recovery.py before their own later integration tasks. Still
standard-library only: no PySide6, no VLC.
"""

from .metadata import (
    MetadataError,
    RecordingMetadataStore,
    SESSION_METADATA_FILENAME,
)
from .recovery import (
    RecoveryOutcome,
    RecoveryReport,
    SESSION_DIR_PREFIX,
    SessionRecoveryResult,
    discover_session_dirs,
    recover_all,
    recover_session,
)
from .startup import (
    DEFAULT_RECORDING_SUBDIR,
    resolve_recording_base_dir,
    run_startup_recovery,
)
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
from .retention import (
    RetentionCriteria,
    find_eligible_sessions,
    is_eligible_for_cleanup,
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
    "MetadataError",
    "RecordingMetadataStore",
    "SESSION_METADATA_FILENAME",
    "RecoveryOutcome",
    "RecoveryReport",
    "SESSION_DIR_PREFIX",
    "SessionRecoveryResult",
    "discover_session_dirs",
    "recover_all",
    "recover_session",
    "DEFAULT_RECORDING_SUBDIR",
    "resolve_recording_base_dir",
    "run_startup_recovery",
    "RetentionCriteria",
    "find_eligible_sessions",
    "is_eligible_for_cleanup",
]
