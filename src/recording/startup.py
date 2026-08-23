"""
recording/startup.py — startup crash-recovery integration point
(Task 9 of the Player/Recorder migration).

This module is the single seam between "the existing Task 8 recovery
engine" (recovery.py: discover_session_dirs/recover_session/recover_all)
and "application startup". It does not implement any recovery logic
itself — it only resolves *where* to look and calls the existing
recover_all() there. Like session.py, storage.py, metadata.py and
recovery.py, it is deliberately plain:

- standard library only (os, pathlib, typing)
- no PySide6, no vlc — no import anywhere in this module touches either,
  so it can be called at the very top of application startup, before a
  QApplication exists and before EmergencyRecorder (which imports both)
  is ever instantiated
- no filesystem deletion, no VLC/RTSP session resumption — identical
  guarantees to recovery.py, since this module only delegates to it

Why not just import recover_all() directly from main.py: a single named
entry point (run_startup_recovery) gives the startup sequence one clear
call to make, keeps the "what directory do we scan" resolution rule
(resolve_recording_base_dir) in one place, and gives future callers
(e.g. a maintenance CLI, or a later UI-wiring task) a stable seam to
depend on instead of reaching into recovery.py's lower-level functions
directly.

Why this duplicates one line of recorder.py's default-directory rule
instead of importing it: recorder.py imports PySide6 (QObject/QTimer/
Signal) and vlc at module scope. Importing anything from recorder.py
here would pull both into this module's import graph, breaking the
"recovery stays importable without PySide6/VLC" guarantee this whole
package (session.py/storage.py/metadata.py/recovery.py) has kept since
Task 2, and would risk a circular import once a later task has
recorder.py call into this module. The one-line default
(~/Videos/EzvizFloatCam) is small enough that duplicating it is cheaper
and safer than adding that dependency.

This module does not decide *whether* the application should run
startup recovery, or wire itself into any run loop — see the Task 9
scope notes: it deliberately does not touch glass_window.py,
stream_widget.py, tray.py, or main.py. It only provides the entry point
a later task can call before starting a new EmergencyRecorder session.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

from .recovery import RecoveryReport, recover_all

__all__ = [
    "DEFAULT_RECORDING_SUBDIR",
    "resolve_recording_base_dir",
    "run_startup_recovery",
]

# Mirrors recorder.py's `_SUBDIR` / `default_recording_dir()` fallback
# (Path.home() / "Videos" / "EzvizFloatCam") — see the module docstring
# for why this is duplicated here rather than imported.
DEFAULT_RECORDING_SUBDIR = Path("Videos") / "EzvizFloatCam"


def resolve_recording_base_dir(
    recording_base_dir: Optional[Union[str, os.PathLike]] = None,
) -> Path:
    """Resolve the directory startup recovery should scan for emergency
    recording session directories (`emergency_<session_id>/`).

    `recording_base_dir` is expected to be whatever the caller's config
    already stores for this (e.g. `config["recording"]["save_dir"]`) — a
    path, or an empty/None value if the user never picked one. An empty
    string or None falls back to the same default EmergencyRecorder.start()
    falls back to when no save_dir is configured, so recovery always looks
    in the same place a new recording would be written to.

    Never touches the filesystem (no exists()/mkdir()) — resolving the
    path and discovering what's actually there are kept separate, same as
    recovery.py's own discover_session_dirs().
    """
    if recording_base_dir:
        return Path(recording_base_dir)
    return Path.home() / DEFAULT_RECORDING_SUBDIR


def run_startup_recovery(
    recording_base_dir: Optional[Union[str, os.PathLike]] = None,
) -> RecoveryReport:
    """Single public entry point for startup crash recovery (Task 9).

    Intended to be called once, early in application startup — before any
    EmergencyRecorder is instantiated and before a new recording session
    can be started — so that any session left interrupted by a previous
    process's crash/power loss/forced termination is reconciled into a
    terminal state first.

    `recording_base_dir` should be the same directory a new recording
    session would be written under (e.g. the configured `save_dir`); pass
    None/empty to use the same default EmergencyRecorder falls back to.

    This is a thin wrapper: it resolves the base directory, then delegates
    entirely to the existing recover_all() (Task 8) — no discovery/
    reconciliation logic is reimplemented here. All of recover_all()'s
    existing guarantees carry over unchanged:

    - one malformed/unreadable session never prevents recovery of any
      other session directory (each is handled independently and reported
      in the returned RecoveryReport, never raised)
    - no VLC instance or RTSP connection is created; no .mkv file is ever
      deleted, moved, or renamed
    - a base directory that does not exist yet is not an error — it is
      reported as a clean startup with no sessions to recover (an empty
      RecoveryReport), exactly as discover_session_dirs() already treats
      a missing directory
    - already-terminal sessions (STOPPED/FAILED/DISK_FULL) are left
      completely untouched, which is what makes calling this twice in a
      row idempotent

    Returns the RecoveryReport produced by recover_all() unchanged.
    """
    base_dir = resolve_recording_base_dir(recording_base_dir)
    return recover_all(base_dir)
