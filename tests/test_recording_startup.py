"""
tests/test_recording_startup.py

Focused integration tests for src/recording/startup.py
(run_startup_recovery) — Task 9 of the Player/Recorder migration
(startup recovery integration).

Like test_recording_recovery.py, this module is standard-library only:
no PySide6, no VLC, and all filesystem access goes through tmp_path.
Unlike the recorder.py characterization tests, this module deliberately
does NOT import conftest.py's fake-vlc/QCoreApplication machinery for
its own assertions — part of what it verifies is that recovery works
without any of that ever being set up (see
test_run_startup_recovery_never_imports_pyside6_or_vlc /
test_run_startup_recovery_does_not_import_recorder_pyside6_or_vlc_subprocess
below).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from recording import (
    RecordingMetadataStore,
    RecordingSegment,
    RecordingSession,
    RecordingStatus,
    RecoveryOutcome,
    SESSION_DIR_PREFIX,
    resolve_recording_base_dir,
    run_startup_recovery,
)


def _utcnow():
    return datetime.now(timezone.utc)


def _make_session_dir(base_dir, session_id="abc123"):
    session_dir = base_dir / f"{SESSION_DIR_PREFIX}{session_id}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _persist(session_dir, session):
    RecordingMetadataStore(session_dir).save(session)
    return session_dir


def _session_in_status(status):
    """Build a RecordingSession that has been driven, via its own
    transition_to() state machine, into `status` — the same path a real
    EmergencyRecorder session would take before being interrupted.

    Follows the allowed-transition table in session.py: DISK_FULL is only
    reachable from STARTING/RECORDING (not STOPPING), so it is reached via
    RECORDING rather than by always going through STOPPING first.
    """
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    if status == RecordingStatus.STARTING:
        return session

    session.transition_to(RecordingStatus.RECORDING)
    if status in (RecordingStatus.RECORDING, RecordingStatus.DISK_FULL):
        if status == RecordingStatus.DISK_FULL:
            session.transition_to(RecordingStatus.DISK_FULL)
        return session

    session.transition_to(RecordingStatus.STOPPING)
    if status == RecordingStatus.STOPPING:
        return session

    session.transition_to(status)  # STOPPED or FAILED
    return session


# ---------------------------------------------------------------------
# 1. Interrupted sessions (STARTING/RECORDING/STOPPING) -> FAILED
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "interrupted_status",
    [
        RecordingStatus.RECORDING,
        RecordingStatus.STARTING,
        RecordingStatus.STOPPING,
    ],
)
def test_startup_recovery_marks_interrupted_sessions_failed(
    tmp_path, interrupted_status
):
    session_dir = _make_session_dir(tmp_path, f"interrupted-{interrupted_status.name}")
    session = _session_in_status(interrupted_status)
    _persist(session_dir, session)

    report = run_startup_recovery(tmp_path)

    assert len(report.recovered) == 1
    recovered = report.recovered[0]
    assert recovered.session_dir == session_dir
    assert recovered.session.status == RecordingStatus.FAILED
    assert recovered.session.error is not None


# ---------------------------------------------------------------------
# 2. Already-terminal sessions are reported but left unchanged
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "terminal_status",
    [RecordingStatus.STOPPED, RecordingStatus.FAILED, RecordingStatus.DISK_FULL],
)
def test_startup_recovery_leaves_terminal_sessions_unchanged(
    tmp_path, terminal_status
):
    session_dir = _make_session_dir(tmp_path, f"terminal-{terminal_status.name}")
    session = _session_in_status(terminal_status)
    _persist(session_dir, session)

    raw_before = (session_dir / "session.json").read_text(encoding="utf-8")

    report = run_startup_recovery(tmp_path)

    assert len(report.already_terminal) == 1
    assert report.already_terminal[0].session.status == terminal_status
    assert report.recovered == []

    raw_after = (session_dir / "session.json").read_text(encoding="utf-8")
    assert raw_after == raw_before  # byte-for-byte untouched


# ---------------------------------------------------------------------
# 3. Multiple sessions: one malformed session never blocks the others
# ---------------------------------------------------------------------


def test_startup_recovery_isolates_one_malformed_session_from_others(tmp_path):
    recovering_dir = _make_session_dir(tmp_path, "good-recovering")
    _persist(recovering_dir, _session_in_status(RecordingStatus.RECORDING))

    terminal_dir = _make_session_dir(tmp_path, "good-terminal")
    _persist(terminal_dir, _session_in_status(RecordingStatus.STOPPED))

    malformed_dir = _make_session_dir(tmp_path, "malformed")
    (malformed_dir / "session.json").write_text("{not valid json", encoding="utf-8")

    report = run_startup_recovery(tmp_path)

    assert {r.session_dir for r in report.recovered} == {recovering_dir}
    assert {r.session_dir for r in report.already_terminal} == {terminal_dir}
    assert {r.session_dir for r in report.invalid} == {malformed_dir}
    assert len(report.results) == 3


# ---------------------------------------------------------------------
# 4. Nonexistent recording directory -> clean startup, empty report
# ---------------------------------------------------------------------


def test_startup_recovery_nonexistent_directory_is_clean_startup(tmp_path):
    missing_dir = tmp_path / "does" / "not" / "exist"
    assert not missing_dir.exists()

    report = run_startup_recovery(missing_dir)

    assert report.results == []
    assert report.recovered == []
    assert report.already_terminal == []
    assert report.invalid == []
    assert report.failed == []


def test_startup_recovery_default_base_dir_resolution_does_not_touch_disk(tmp_path):
    # resolve_recording_base_dir() must be pure path computation — no
    # exists()/mkdir() — so it's safe to call before deciding whether the
    # directory should even be created.
    resolved = resolve_recording_base_dir(None)
    assert resolved.name == "EzvizFloatCam"
    resolved_empty = resolve_recording_base_dir("")
    assert resolved_empty == resolved

    configured = tmp_path / "custom_recordings"
    assert resolve_recording_base_dir(str(configured)) == configured


# ---------------------------------------------------------------------
# 5. Independence from PySide6/VLC
# ---------------------------------------------------------------------


def test_startup_module_source_has_no_pyside6_or_vlc_import_statements():
    import ast

    import recording.startup as startup_module

    source = open(startup_module.__file__, encoding="utf-8").read()
    tree = ast.parse(source)

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)

    assert not any(
        name == "vlc" or name.startswith("PySide6") for name in imported_names
    )


def test_run_startup_recovery_never_imports_pyside6_or_vlc(tmp_path, monkeypatch):
    # Simulate a fresh interpreter where neither PySide6 nor vlc has ever
    # been imported, and make importing either one fail loudly — if
    # run_startup_recovery (or anything it calls) tried to pull either in,
    # this test would raise instead of silently passing because a prior
    # test already imported them.
    for mod_name in list(sys.modules):
        if mod_name == "vlc" or mod_name.startswith("PySide6"):
            monkeypatch.delitem(sys.modules, mod_name, raising=False)

    import builtins

    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        if name == "vlc" or name.startswith("PySide6"):
            raise AssertionError(f"run_startup_recovery must not import {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    session_dir = _make_session_dir(tmp_path, "no-vlc-needed")
    _persist(session_dir, _session_in_status(RecordingStatus.RECORDING))

    report = run_startup_recovery(tmp_path)

    assert len(report.recovered) == 1


# ---------------------------------------------------------------------
# 6. Can run before EmergencyRecorder is ever instantiated
# ---------------------------------------------------------------------

# This has to run in a fresh subprocess rather than in-process: this test
# file's own pytest process is not a valid host for the assertion. Two
# things make it unusable in-process:
#   - tests/conftest.py installs a *fake* `vlc` module into sys.modules at
#     collection time (before any test body runs) for the unrelated
#     recorder.py characterization tests, and provides a session-scoped
#     QCoreApplication (PySide6) autoused by every test in this suite —
#     so by the time this test's body runs, both are already present in
#     sys.modules regardless of what startup.py itself does.
#   - whether `recorder` (EmergencyRecorder's own module) happens to be in
#     sys.modules depends on pytest's test collection/execution order
#     across the whole suite, which is not something this test controls
#     or should depend on.
# A subprocess with only src/ on sys.path — and none of conftest.py's
# fixtures — is a genuinely clean interpreter to prove the actual
# architectural property against: importing recording.startup and calling
# run_startup_recovery() must not, by itself, cause `recorder`, `vlc`, or
# any `PySide6*` module to be imported.
_SUBPROCESS_PROBE = """
import sys
import json
from pathlib import Path

sys.path.insert(0, {src_dir!r})

# Precondition: none of these are loaded yet in this fresh interpreter.
preexisting = sorted(
    m for m in sys.modules if m == "recorder" or m == "vlc" or m.startswith("PySide6")
)

from recording.startup import run_startup_recovery

session_dir = Path({session_dir!r})
report = run_startup_recovery(session_dir.parent)

after = sorted(
    m for m in sys.modules if m == "recorder" or m == "vlc" or m.startswith("PySide6")
)

print(json.dumps({{
    "preexisting": preexisting,
    "after": after,
    "recovered_count": len(report.recovered),
}}))
"""


def test_run_startup_recovery_does_not_import_recorder_pyside6_or_vlc_subprocess(
    tmp_path,
):
    session_dir = _make_session_dir(tmp_path, "before-recorder")
    _persist(session_dir, _session_in_status(RecordingStatus.STARTING))

    src_dir = str(Path(__file__).resolve().parent.parent / "src")
    script = _SUBPROCESS_PROBE.format(src_dir=src_dir, session_dir=str(session_dir))

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"subprocess probe failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

    payload = json.loads(result.stdout.strip().splitlines()[-1])

    # Sanity: the fresh interpreter genuinely started with none of these
    # loaded — otherwise the "after" check below would be meaningless.
    assert payload["preexisting"] == []

    # The actual architectural property: importing recording.startup and
    # calling run_startup_recovery() must not pull in recorder.py,
    # PySide6, or vlc as a side effect.
    assert payload["after"] == []

    # Sanity: recovery still actually ran against the interrupted session.
    assert payload["recovered_count"] == 1


# ---------------------------------------------------------------------
# 7. Idempotency
# ---------------------------------------------------------------------


def test_run_startup_recovery_is_idempotent(tmp_path):
    session_dir = _make_session_dir(tmp_path, "idempotent")
    _persist(session_dir, _session_in_status(RecordingStatus.RECORDING))

    first_report = run_startup_recovery(tmp_path)
    assert len(first_report.recovered) == 1
    first_error = first_report.recovered[0].session.error
    raw_after_first = (session_dir / "session.json").read_text(encoding="utf-8")

    second_report = run_startup_recovery(tmp_path)

    assert second_report.recovered == []
    assert len(second_report.already_terminal) == 1
    assert second_report.already_terminal[0].session.status == RecordingStatus.FAILED
    assert second_report.already_terminal[0].session.error == first_error

    raw_after_second = (session_dir / "session.json").read_text(encoding="utf-8")
    assert raw_after_second == raw_after_first  # not rewritten a second time


# ---------------------------------------------------------------------
# 8. Does not create or delete recording (.mkv) files
# ---------------------------------------------------------------------


def test_run_startup_recovery_does_not_create_or_delete_mkv_files(tmp_path):
    session_dir = _make_session_dir(tmp_path, "mkv-untouched")
    session = _session_in_status(RecordingStatus.RECORDING)

    completed_seg = RecordingSegment(
        path=str(session_dir / "completed.mkv"), started_at=_utcnow()
    )
    completed_seg.mark_completed(size_bytes=1234)
    in_progress_seg = RecordingSegment(
        path=str(session_dir / "in_progress.mkv"), started_at=_utcnow()
    )
    session.add_segment(completed_seg)
    session.add_segment(in_progress_seg)

    (session_dir / "completed.mkv").write_bytes(b"\x00" * 1234)
    (session_dir / "in_progress.mkv").write_bytes(b"\x00" * 500)
    _persist(session_dir, session)

    mkv_files_before = sorted(p.name for p in session_dir.glob("*.mkv"))

    report = run_startup_recovery(tmp_path)

    mkv_files_after = sorted(p.name for p in session_dir.glob("*.mkv"))
    assert mkv_files_after == mkv_files_before
    assert (session_dir / "completed.mkv").read_bytes() == b"\x00" * 1234
    assert (session_dir / "in_progress.mkv").read_bytes() == b"\x00" * 500

    # Sanity: recovery did in fact run against this directory.
    assert len(report.recovered) == 1


def test_run_startup_recovery_does_not_create_extra_files_in_base_dir(tmp_path):
    session_dir = _make_session_dir(tmp_path, "no-extra-files")
    _persist(session_dir, _session_in_status(RecordingStatus.RECORDING))

    entries_before = sorted(p.name for p in tmp_path.iterdir())

    run_startup_recovery(tmp_path)

    entries_after = sorted(p.name for p in tmp_path.iterdir())
    assert entries_after == entries_before


# ---------------------------------------------------------------------
# 9. Return type: the existing RecoveryReport, unchanged
# ---------------------------------------------------------------------


def test_run_startup_recovery_returns_the_existing_recovery_report_type(tmp_path):
    from recording import RecoveryReport

    report = run_startup_recovery(tmp_path)
    assert isinstance(report, RecoveryReport)
