"""
tests/test_recording_session.py

Focused unit tests for src/recording/session.py (RecordingSession,
RecordingSegment, RecordingStatus) — Task 2 of the Player/Recorder
migration.

This module is a plain domain model: no PySide6, no VLC, no filesystem
I/O, no EmergencyRecorder/GlassWindow. These tests exercise it in
isolation and do not touch src/recorder.py or the existing
EmergencyRecorder test suite (tests/test_recorder.py) at all.
"""

from datetime import datetime, timedelta, timezone

import pytest

from recording import (
    InvalidTransitionError,
    RecordingSegment,
    RecordingSession,
    RecordingStatus,
)


# ---------------------------------------------------------------------
# 1. New session defaults to IDLE
# ---------------------------------------------------------------------


def test_new_session_defaults_to_idle():
    session = RecordingSession()
    assert session.status is RecordingStatus.IDLE


# ---------------------------------------------------------------------
# 2. New (emergency) session defaults to protected=True
# ---------------------------------------------------------------------


def test_new_session_defaults_to_protected():
    session = RecordingSession()
    assert session.protected is True


# ---------------------------------------------------------------------
# 3. Session IDs are unique
# ---------------------------------------------------------------------


def test_session_ids_are_unique():
    ids = {RecordingSession().session_id for _ in range(100)}
    assert len(ids) == 100


# ---------------------------------------------------------------------
# 4. Valid state transitions work
# ---------------------------------------------------------------------


def test_full_happy_path_transition_sequence():
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    assert session.status is RecordingStatus.STARTING

    session.transition_to(RecordingStatus.RECORDING)
    assert session.status is RecordingStatus.RECORDING

    session.transition_to(RecordingStatus.STOPPING)
    assert session.status is RecordingStatus.STOPPING

    session.transition_to(RecordingStatus.STOPPED)
    assert session.status is RecordingStatus.STOPPED


@pytest.mark.parametrize(
    "path",
    [
        [RecordingStatus.STARTING, RecordingStatus.FAILED],
        [RecordingStatus.STARTING, RecordingStatus.RECORDING, RecordingStatus.FAILED],
        [
            RecordingStatus.STARTING,
            RecordingStatus.RECORDING,
            RecordingStatus.DISK_FULL,
        ],
        [
            RecordingStatus.STARTING,
            RecordingStatus.RECORDING,
            RecordingStatus.FAILED,
            RecordingStatus.RECOVERABLE,
        ],
    ],
)
def test_valid_failure_paths(path):
    session = RecordingSession()
    for status in path:
        session.transition_to(status)
    assert session.status is path[-1]


# ---------------------------------------------------------------------
# 5. Invalid transitions are rejected
# ---------------------------------------------------------------------


def test_idle_to_recording_is_rejected_skipping_starting():
    session = RecordingSession()
    with pytest.raises(InvalidTransitionError):
        session.transition_to(RecordingStatus.RECORDING)
    # rejected transition must not mutate state
    assert session.status is RecordingStatus.IDLE


def test_stopped_is_terminal_no_further_transitions():
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    session.transition_to(RecordingStatus.STOPPING)
    session.transition_to(RecordingStatus.STOPPED)

    with pytest.raises(InvalidTransitionError):
        session.transition_to(RecordingStatus.RECORDING)
    with pytest.raises(InvalidTransitionError):
        session.transition_to(RecordingStatus.STARTING)


def test_disk_full_cannot_go_back_to_recording():
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    session.transition_to(RecordingStatus.DISK_FULL)

    with pytest.raises(InvalidTransitionError):
        session.transition_to(RecordingStatus.RECORDING)


def test_invalid_transition_error_is_a_value_error():
    """Callers that only catch ValueError (a common broad guard) must
    still catch this."""
    session = RecordingSession()
    with pytest.raises(ValueError):
        session.transition_to(RecordingStatus.STOPPED)


# ---------------------------------------------------------------------
# 6. ended_at is unset while active
# ---------------------------------------------------------------------


def test_ended_at_is_none_while_idle_starting_recording_stopping():
    session = RecordingSession()
    assert session.ended_at is None

    session.transition_to(RecordingStatus.STARTING)
    assert session.ended_at is None

    session.transition_to(RecordingStatus.RECORDING)
    assert session.ended_at is None

    session.transition_to(RecordingStatus.STOPPING)
    assert session.ended_at is None


# ---------------------------------------------------------------------
# 7. ended_at can be set when the session ends
# ---------------------------------------------------------------------


def test_ended_at_is_set_on_stopped():
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    session.transition_to(RecordingStatus.STOPPING)

    before = datetime.now(timezone.utc)
    session.transition_to(RecordingStatus.STOPPED)
    after = datetime.now(timezone.utc)

    assert session.ended_at is not None
    assert session.ended_at.tzinfo is not None  # timezone-aware, per requirement
    assert before <= session.ended_at <= after


def test_ended_at_is_set_on_failed_and_on_disk_full():
    s1 = RecordingSession()
    s1.transition_to(RecordingStatus.STARTING)
    s1.transition_to(RecordingStatus.FAILED, error="camera unreachable")
    assert s1.ended_at is not None
    assert s1.error == "camera unreachable"

    s2 = RecordingSession()
    s2.transition_to(RecordingStatus.STARTING)
    s2.transition_to(RecordingStatus.RECORDING)
    s2.transition_to(RecordingStatus.DISK_FULL, error="no space left on device")
    assert s2.ended_at is not None
    assert s2.error == "no space left on device"


def test_ended_at_can_be_supplied_explicitly():
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    session.transition_to(RecordingStatus.STOPPING)

    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session.transition_to(RecordingStatus.STOPPED, ended_at=fixed_time)
    assert session.ended_at == fixed_time


def test_ended_at_is_preserved_across_failed_to_recoverable():
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.FAILED)
    failed_ended_at = session.ended_at
    assert failed_ended_at is not None

    session.transition_to(RecordingStatus.RECOVERABLE)
    assert session.ended_at == failed_ended_at


# ---------------------------------------------------------------------
# 8. Segment can represent incomplete and completed states
# ---------------------------------------------------------------------


def test_segment_starts_incomplete():
    segment = RecordingSegment(
        path="/tmp/emergency_20260101_000000.mkv",
        started_at=datetime.now(timezone.utc),
    )
    assert segment.completed is False
    assert segment.ended_at is None
    assert segment.size_bytes == 0


def test_segment_mark_completed():
    segment = RecordingSegment(
        path="/tmp/emergency_20260101_000000.mkv",
        started_at=datetime.now(timezone.utc),
    )
    segment.mark_completed(size_bytes=4096)

    assert segment.completed is True
    assert segment.ended_at is not None
    assert segment.size_bytes == 4096


def test_segment_mark_completed_rejects_negative_size():
    segment = RecordingSegment(
        path="/tmp/x.mkv", started_at=datetime.now(timezone.utc)
    )
    with pytest.raises(ValueError):
        segment.mark_completed(size_bytes=-1)


def test_session_can_hold_a_completed_and_a_pending_segment():
    session = RecordingSession()
    done = RecordingSegment(
        path="/tmp/a.mkv",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc) + timedelta(seconds=5),
        size_bytes=1024,
        completed=True,
    )
    pending = RecordingSegment(
        path="/tmp/b.mkv", started_at=datetime.now(timezone.utc)
    )
    session.add_segment(done)
    session.add_segment(pending)

    assert session.segments == [done, pending]
    assert session.segments[0].completed is True
    assert session.segments[1].completed is False


# ---------------------------------------------------------------------
# 9. total_bytes can be updated safely
# ---------------------------------------------------------------------


def test_total_bytes_defaults_to_zero():
    assert RecordingSession().total_bytes == 0


def test_add_bytes_accumulates():
    session = RecordingSession()
    session.add_bytes(100)
    session.add_bytes(50)
    assert session.total_bytes == 150


def test_add_bytes_rejects_negative():
    session = RecordingSession()
    with pytest.raises(ValueError):
        session.add_bytes(-1)
    assert session.total_bytes == 0


def test_set_total_bytes_overwrites_and_rejects_negative():
    session = RecordingSession()
    session.add_bytes(100)
    session.set_total_bytes(999)
    assert session.total_bytes == 999

    with pytest.raises(ValueError):
        session.set_total_bytes(-1)
    assert session.total_bytes == 999  # unchanged after rejected call


# ---------------------------------------------------------------------
# 10. The recording model has no dependency on PySide6/VLC
# ---------------------------------------------------------------------


def test_recording_package_imports_no_pyside6_or_vlc():
    """Static regression guard: src/recording/ must stay a plain domain
    model. If a future change adds a PySide6 or vlc import to this
    package, this test fails immediately."""
    import ast
    from pathlib import Path

    recording_dir = Path(__file__).resolve().parent.parent / "src" / "recording"
    py_files = sorted(recording_dir.glob("*.py"))
    assert py_files, "expected src/recording/*.py to exist"

    forbidden_prefixes = ("PySide6", "vlc", "shiboken6")

    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)

        offending = [
            name
            for name in imported_names
            if any(name == p or name.startswith(p + ".") for p in forbidden_prefixes)
        ]
        assert not offending, f"{py_file.name} imports forbidden module(s): {offending}"


def test_recording_session_is_constructible_without_qt_or_vlc_loaded():
    """Functional companion: importing/using RecordingSession must not
    require PySide6 or vlc to be importable at all — this test module
    never imports either, unlike tests/test_recorder.py (which fakes
    vlc via conftest.py for EmergencyRecorder's sake)."""
    import sys

    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    session.add_bytes(1)
    assert session.status is RecordingStatus.RECORDING
    # Note: conftest.py's fake `vlc` module is present in sys.modules
    # session-wide (installed for test_recorder.py), so this only proves
    # `recording` itself doesn't reference PySide6/vlc — the static AST
    # check above is the authoritative guard for that.
    assert "recording" in sys.modules
