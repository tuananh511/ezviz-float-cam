"""
recording/recovery.py — crash/session recovery for persisted emergency
recording sessions (Task 8 of the Player/Recorder migration).

Like session.py, metadata.py, and storage.py, this module is deliberately
plain:

- standard library only (os, dataclasses, pathlib, typing)
- no PySide6, no vlc — no import anywhere in this module touches either
- no filesystem deletion, ever
- no automatic resumption of VLC/RTSP recording — recovery only
  reconciles on-disk metadata + physical .mkv evidence, it never starts
  a media player or a network stream

Why a separate module instead of extending EmergencyRecorder: recovery is
a one-shot, offline reconciliation pass over `session.json` files left
behind by a previous process that terminated unexpectedly (crash, power
loss, "End task"). It has nothing to do with the live recording pipeline
EmergencyRecorder drives, and folding it in there would mix "manage an
active VLC session" concerns with "inspect a directory tree of possibly
stale sessions" concerns. Keeping it standalone also means it can be
imported and exercised without ever touching PySide6/VLC — important for
running it early at app startup, or from a standalone maintenance tool.

--- What "recovery" means here ---

A RecordingSession is only ever persisted (via RecordingMetadataStore)
while STARTING, RECORDING, or STOPPING, or after it has reached one of
its terminal states (STOPPED, FAILED, DISK_FULL). If the process that
wrote a STARTING/RECORDING/STOPPING session.json is gone (crashed) and
nothing resumed it, that session is *interrupted*: no live recorder is
ever going to move it forward again, its VLC handle is long gone, and it
must be reconciled into a terminal state that reflects the physical
evidence — the .mkv segment files actually sitting in the session
directory — rather than the last state it happened to be in when the
process died.

Recovery for one interrupted session means:

1. Load `session.json` (RecordingMetadataStore.load()) — if this fails,
   the session directory is reported as invalid, not silently skipped.
2. List the `.mkv` files that physically exist in the session directory.
3. For every segment already recorded in metadata whose `path` matches
   an existing `.mkv` file:
     - if the segment is already `completed`, its recorded metadata
       (ended_at, size_bytes) is preserved as-is — we do not second-guess
       a segment the previous process already finished and recorded.
     - if the segment is marked completed but has size_bytes == 0 (the
       file exists but its size was never recorded), the size is filled
       in from `stat()` — this is populating *missing* evidence, not
       overwriting evidence that was already captured.
     - if the segment is NOT completed, recovery does not fabricate an
       ended_at or flip it to completed: without an explicit close event
       we have no reliable end time for that segment, only that some
       bytes exist on disk. That is left for a human/operator to inspect;
       recovery must not invent timestamps or completion.
4. `total_bytes` is recalculated via
   `RecordingSession.recalculate_total_bytes()` — i.e. it is always the
   sum of `size_bytes` across `completed` segments only, per the existing
   domain-model semantics in session.py. This is a straight call into
   that existing method, not a re-implementation of its rule.
5. The session is transitioned to FAILED (via
   `RecordingSession.transition_to()`, which enforces the existing
   session.py state machine) with a clear recovery `error` reason. If the
   session already had an `ended_at` (e.g. it was already STOPPING with
   one set) it is preserved; only sessions without one get `ended_at` set
   at recovery time.
6. The recovered RecordingSession is persisted back via
   `RecordingMetadataStore.save()` — atomically, via the store's existing
   temp-file + os.replace() implementation, so there's no window where
   session.json could be left half-written.

A session already in a terminal state (STOPPED, FAILED, DISK_FULL) is
reported as "already terminal" and is left completely untouched — no
save() call is made for it — which is what makes running recovery twice
in a row idempotent: the second pass finds only terminal sessions and
touches nothing.

No `.mkv` file is ever deleted, moved, or renamed by this module. No VLC
instance or RTSP connection is created. Callers remain fully responsible
for deciding whether/how to *notify* the user about a recovered session,
or whether to ever resume live recording — this module only reconciles
records.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from .metadata import MetadataError, RecordingMetadataStore
from .session import RecordingSession, RecordingStatus

__all__ = [
    "RecoveryOutcome",
    "SessionRecoveryResult",
    "RecoveryReport",
    "SESSION_DIR_PREFIX",
    "discover_session_dirs",
    "recover_session",
    "recover_all",
]


# Directory naming convention used by EmergencyRecorder
# (see recorder.py: `session_dir = base_dir / f"emergency_{session.session_id}"`).
SESSION_DIR_PREFIX = "emergency_"

# Statuses that represent a session possibly interrupted mid-flight by an
# unexpected process termination — these are the only statuses recovery
# will ever transition out of. Anything else persisted (STOPPED, FAILED,
# DISK_FULL) is already a terminal, resolved outcome and is left alone.
_INTERRUPTIBLE_STATUSES = frozenset(
    {
        RecordingStatus.STARTING,
        RecordingStatus.RECORDING,
        RecordingStatus.STOPPING,
    }
)

_TERMINAL_STATUSES = frozenset(
    {
        RecordingStatus.STOPPED,
        RecordingStatus.FAILED,
        RecordingStatus.DISK_FULL,
    }
)

_DEFAULT_RECOVERY_ERROR = (
    "Recovered after unexpected application termination: session was "
    "left in {status} state with no active recorder; reconciled against "
    "on-disk .mkv evidence and marked FAILED."
)


class RecoveryOutcome:
    """String-enum-like constants describing what happened to one session
    directory during recovery. Plain string constants (not enum.Enum) so
    they serialize/compare trivially and match the plain-data style of
    the rest of this module.
    """

    RECOVERED = "RECOVERED"
    ALREADY_TERMINAL = "ALREADY_TERMINAL"
    INVALID = "INVALID"
    FAILED = "FAILED"


@dataclass
class SessionRecoveryResult:
    """Outcome of attempting to recover a single session directory.

    Exactly one of the following holds, matching `outcome`:
    - RECOVERED: `session` is the recovered (and already persisted, via
      RecordingMetadataStore.save()) RecordingSession.
    - ALREADY_TERMINAL: `session` is the terminal session as loaded, left
      untouched (nothing was written back to disk).
    - INVALID: `session` is None; `error` describes why the session
      directory could not even be read (missing/malformed session.json,
      or a directory that doesn't match the expected naming convention
      closely enough to contain one).
    - FAILED: `session` is None; `error` describes a failure that
      happened while attempting to reconcile/persist an otherwise
      loadable, interruptible session (e.g. a filesystem error while
      stat()'ing a segment, or a save() failure). This session's
      session.json is left as-is — never partially written — because
      RecordingMetadataStore.save() is atomic and is only called with a
      fully-reconciled in-memory session.
    """

    session_dir: Path
    outcome: str
    session: Optional[RecordingSession] = None
    error: Optional[str] = None


@dataclass
class RecoveryReport:
    """Aggregate result of running recovery over a whole base directory.

    One bad session never stops the others: each session directory is
    processed independently and its result recorded here regardless of
    what happened to any other directory.
    """

    results: List[SessionRecoveryResult] = field(default_factory=list)

    @property
    def recovered(self) -> List[SessionRecoveryResult]:
        return [r for r in self.results if r.outcome == RecoveryOutcome.RECOVERED]

    @property
    def already_terminal(self) -> List[SessionRecoveryResult]:
        return [r for r in self.results if r.outcome == RecoveryOutcome.ALREADY_TERMINAL]

    @property
    def invalid(self) -> List[SessionRecoveryResult]:
        return [r for r in self.results if r.outcome == RecoveryOutcome.INVALID]

    @property
    def failed(self) -> List[SessionRecoveryResult]:
        return [r for r in self.results if r.outcome == RecoveryOutcome.FAILED]


def discover_session_dirs(base_dir: Union[str, os.PathLike]) -> List[Path]:
    """Scan `base_dir` for subdirectories that look like emergency
    recording session directories (`emergency_<session_id>/`) containing
    a `session.json`.

    Unrelated directories/files directly under `base_dir` are ignored
    silently — they are, by definition, not emergency-recording session
    directories, so there is nothing to report about them. A directory
    that DOES match the `emergency_` naming convention but has no (or an
    unreadable) `session.json` is still returned here — discovery only
    filters by *name*; whether the metadata inside is valid is decided by
    recover_session()/recover_all(), which is what surfaces malformed
    metadata explicitly rather than discovery quietly dropping it.

    Returns paths sorted for deterministic ordering; does not raise if
    `base_dir` does not exist (returns an empty list) — that is not, by
    itself, evidence of a malformed session.
    """
    base = Path(base_dir)
    if not base.is_dir():
        return []

    found: List[Path] = []
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        if not entry.name.startswith(SESSION_DIR_PREFIX):
            continue
        found.append(entry)

    return sorted(found)


def _discover_mkv_files(session_dir: Path) -> List[Path]:
    """Every `.mkv` file directly inside `session_dir` (no recursion —
    EmergencyRecorder writes segments flat in the session directory, see
    recorder.py's `_session_dir / candidate_name`)."""
    if not session_dir.is_dir():
        return []
    return sorted(p for p in session_dir.iterdir() if p.is_file() and p.suffix == ".mkv")


def _reconcile_segments(session: RecordingSession, session_dir: Path) -> None:
    """Reconcile `session.segments` against the .mkv files physically
    present in `session_dir`, in place. Never deletes/renames a file;
    never fabricates a completion or a timestamp for a segment lacking
    evidence of having finished. Only fills in `size_bytes` for a
    COMPLETED segment whose recorded size_bytes is 0 but whose file
    exists on disk with a non-zero size.
    """
    mkv_by_name = {p.name: p for p in _discover_mkv_files(session_dir)}

    for segment in session.segments:
        matching_path = mkv_by_name.get(Path(segment.path).name)
        if matching_path is None:
            # Recorded in metadata but no physical file found — leave the
            # segment's recorded metadata exactly as-is; recovery does not
            # delete/repair missing evidence, only fills in what it can
            # verify from what DOES exist.
            continue

        if segment.completed and segment.size_bytes == 0:
            try:
                actual_size = matching_path.stat().st_size
            except OSError:
                # Can't stat it — leave size_bytes as recorded rather than
                # guessing or raising; this is a best-effort enrichment,
                # not a requirement for recovery to proceed.
                continue
            if actual_size > 0:
                segment.size_bytes = actual_size

    session.recalculate_total_bytes()


def recover_session(session_dir: Union[str, os.PathLike]) -> SessionRecoveryResult:
    """Attempt to recover a single emergency-recording session directory.

    Never deletes any file. Never starts VLC/RTSP recording. Only reads
    `session.json` + the segment `.mkv` files already present, then (for
    an interruptible session) writes back a reconciled, FAILED
    session.json via RecordingMetadataStore.save().

    Returns a SessionRecoveryResult describing exactly what happened;
    never raises for an individual session's own problems (missing/
    malformed metadata, filesystem errors) — those are captured in the
    result so one bad session cannot abort recovery of any other.
    """
    session_dir = Path(session_dir)
    store = RecordingMetadataStore(session_dir)

    try:
        session = store.load()
    except MetadataError as exc:
        return SessionRecoveryResult(
            session_dir=session_dir,
            outcome=RecoveryOutcome.INVALID,
            error=str(exc),
        )
    except OSError as exc:
        return SessionRecoveryResult(
            session_dir=session_dir,
            outcome=RecoveryOutcome.INVALID,
            error=f"filesystem error reading session metadata: {exc}",
        )

    if session.status not in _INTERRUPTIBLE_STATUSES:
        # Already STOPPED / FAILED / DISK_FULL (or, in principle,
        # RECOVERABLE) — a resolved, terminal outcome from a prior run.
        # Recovery must be idempotent, so this session is reported and
        # left completely untouched: no reconciliation, no save().
        return SessionRecoveryResult(
            session_dir=session_dir,
            outcome=RecoveryOutcome.ALREADY_TERMINAL,
            session=session,
        )

    try:
        _reconcile_segments(session, session_dir)

        preserved_ended_at = session.ended_at
        session.transition_to(
            RecordingStatus.FAILED,
            error=_DEFAULT_RECOVERY_ERROR.format(status=session.status.name),
            ended_at=preserved_ended_at,
        )

        store.save(session)
    except (MetadataError, OSError, ValueError) as exc:
        return SessionRecoveryResult(
            session_dir=session_dir,
            outcome=RecoveryOutcome.FAILED,
            error=f"failed to recover session {session.session_id}: {exc}",
        )

    return SessionRecoveryResult(
        session_dir=session_dir,
        outcome=RecoveryOutcome.RECOVERED,
        session=session,
    )


def recover_all(base_dir: Union[str, os.PathLike]) -> RecoveryReport:
    """Discover and attempt recovery of every emergency-recording session
    directory under `base_dir`.

    Each session directory is processed independently via
    recover_session(); a failure/invalid result for one never prevents
    the others from being processed. Directories that do not match the
    `emergency_<session_id>` naming convention are ignored (not part of
    the report at all) — see discover_session_dirs().
    """
    report = RecoveryReport()
    for session_dir in discover_session_dirs(base_dir):
        report.results.append(recover_session(session_dir))
    return report
