"""
tests/test_recording_retention.py

Focused unit tests for src/recording/retention.py
(RetentionCriteria/is_eligible_for_cleanup/find_eligible_sessions) — Task
13 of the Player/Recorder migration.

This module is a plain domain model: no PySide6, no VLC, no filesystem
I/O. These tests exercise it in isolation and do not touch
src/recorder.py, src/main.py, or any other existing test suite.
"""

from datetime import datetime, timedelta, timezone

import pytest

from recording import (
    RecordingSession,
    RecordingStatus,
    RetentionCriteria,
    find_eligible_sessions,
    is_eligible_for_cleanup,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_session(
    *,
    status: RecordingStatus,
    protected: bool,
    ended_at=None,
) -> RecordingSession:
    """Build a RecordingSession already in `status`, going through the
    real transition_to() state machine (never setting .status directly)
    so these tests only exercise reachable, legal states.
    """
    session = RecordingSession(protected=protected)

    if status is RecordingStatus.IDLE:
        pass
    elif status is RecordingStatus.STARTING:
        session.transition_to(RecordingStatus.STARTING)
    elif status is RecordingStatus.RECORDING:
        session.transition_to(RecordingStatus.STARTING)
        session.transition_to(RecordingStatus.RECORDING)
    elif status is RecordingStatus.STOPPING:
        session.transition_to(RecordingStatus.STARTING)
        session.transition_to(RecordingStatus.RECORDING)
        session.transition_to(RecordingStatus.STOPPING)
    elif status is RecordingStatus.STOPPED:
        session.transition_to(RecordingStatus.STARTING)
        session.transition_to(RecordingStatus.RECORDING)
        session.transition_to(RecordingStatus.STOPPING)
        session.transition_to(RecordingStatus.STOPPED, ended_at=ended_at)
    elif status is RecordingStatus.FAILED:
        session.transition_to(RecordingStatus.STARTING)
        session.transition_to(RecordingStatus.FAILED, ended_at=ended_at)
    elif status is RecordingStatus.DISK_FULL:
        session.transition_to(RecordingStatus.STARTING)
        session.transition_to(RecordingStatus.DISK_FULL, ended_at=ended_at)
    elif status is RecordingStatus.RECOVERABLE:
        session.transition_to(RecordingStatus.STARTING)
        session.transition_to(RecordingStatus.FAILED, ended_at=ended_at)
        session.transition_to(RecordingStatus.RECOVERABLE)
    else:  # pragma: no cover - exhaustive guard for future statuses
        raise AssertionError(f"unhandled status in test helper: {status}")

    return session


# ---------------------------------------------------------------------
# 1. Terminal + unprotected + old enough -> eligible
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [RecordingStatus.STOPPED, RecordingStatus.FAILED, RecordingStatus.DISK_FULL],
)
def test_terminal_unprotected_old_session_is_eligible(status):
    old_ended_at = _now() - timedelta(days=30)
    session = _make_session(status=status, protected=False, ended_at=old_ended_at)
    criteria = RetentionCriteria(older_than=_now())

    assert is_eligible_for_cleanup(session, criteria) is True


# ---------------------------------------------------------------------
# 2. protected=True is never eligible, regardless of status/age
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [RecordingStatus.STOPPED, RecordingStatus.FAILED, RecordingStatus.DISK_FULL],
)
def test_protected_session_is_never_eligible(status):
    old_ended_at = _now() - timedelta(days=365)
    session = _make_session(status=status, protected=True, ended_at=old_ended_at)
    criteria = RetentionCriteria(older_than=_now())

    assert is_eligible_for_cleanup(session, criteria) is False


# ---------------------------------------------------------------------
# 3. Non-terminal (still potentially live) statuses are never eligible,
#    even when unprotected
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [RecordingStatus.STARTING, RecordingStatus.RECORDING, RecordingStatus.STOPPING],
)
def test_active_session_is_never_eligible(status):
    session = _make_session(status=status, protected=False)
    # Deliberately generous cutoff (far future) — even so, an active
    # session must never be eligible.
    criteria = RetentionCriteria(older_than=_now() + timedelta(days=3650))

    assert is_eligible_for_cleanup(session, criteria) is False


def test_idle_session_is_never_eligible():
    session = _make_session(status=RecordingStatus.IDLE, protected=False)
    criteria = RetentionCriteria(older_than=_now() + timedelta(days=3650))

    assert is_eligible_for_cleanup(session, criteria) is False


def test_recoverable_session_is_never_eligible():
    """RECOVERABLE is reachable (FAILED -> RECOVERABLE) but is not in the
    terminal set this module checks against — mirrors recovery.py's own
    _TERMINAL_STATUSES excluding RECOVERABLE."""
    old_ended_at = _now() - timedelta(days=365)
    session = _make_session(
        status=RecordingStatus.RECOVERABLE, protected=False, ended_at=old_ended_at
    )
    criteria = RetentionCriteria(older_than=_now())

    assert is_eligible_for_cleanup(session, criteria) is False


# ---------------------------------------------------------------------
# 4. Age boundary: only sessions old enough per the caller-supplied
#    cutoff are eligible
# ---------------------------------------------------------------------


def test_terminal_unprotected_session_too_recent_is_not_eligible():
    recent_ended_at = _now() - timedelta(seconds=1)
    session = _make_session(
        status=RecordingStatus.STOPPED, protected=False, ended_at=recent_ended_at
    )
    # Cutoff far in the past -> session ended after the cutoff -> not old
    # enough yet.
    criteria = RetentionCriteria(older_than=_now() - timedelta(days=30))

    assert is_eligible_for_cleanup(session, criteria) is False


def test_ended_at_exactly_at_cutoff_is_eligible():
    """ended_at <= older_than is the documented boundary (inclusive)."""
    cutoff = _now()
    session = _make_session(
        status=RecordingStatus.STOPPED, protected=False, ended_at=cutoff
    )
    criteria = RetentionCriteria(older_than=cutoff)

    assert is_eligible_for_cleanup(session, criteria) is True


# ---------------------------------------------------------------------
# 5. No fabricated age: a terminal session with no ended_at is never
#    eligible
# ---------------------------------------------------------------------


def test_terminal_session_with_no_ended_at_is_never_eligible():
    session = _make_session(status=RecordingStatus.STOPPED, protected=False)
    # Force the defensive case (ended_at should always be set on a
    # terminal session by transition_to(), but this module must not
    # assume/trust that and must not fabricate an age if it's ever
    # missing).
    session.ended_at = None
    criteria = RetentionCriteria(older_than=_now() + timedelta(days=3650))

    assert is_eligible_for_cleanup(session, criteria) is False


# ---------------------------------------------------------------------
# 6. find_eligible_sessions filters a mixed collection, preserving order
# ---------------------------------------------------------------------


def test_find_eligible_sessions_filters_mixed_collection_preserving_order():
    old_ended_at = _now() - timedelta(days=30)
    cutoff = _now()

    eligible_one = _make_session(
        status=RecordingStatus.STOPPED, protected=False, ended_at=old_ended_at
    )
    protected_one = _make_session(
        status=RecordingStatus.FAILED, protected=True, ended_at=old_ended_at
    )
    active_one = _make_session(status=RecordingStatus.RECORDING, protected=False)
    eligible_two = _make_session(
        status=RecordingStatus.DISK_FULL, protected=False, ended_at=old_ended_at
    )
    too_recent_one = _make_session(
        status=RecordingStatus.STOPPED,
        protected=False,
        ended_at=cutoff + timedelta(seconds=1),
    )

    sessions = [
        eligible_one,
        protected_one,
        active_one,
        eligible_two,
        too_recent_one,
    ]
    criteria = RetentionCriteria(older_than=cutoff)

    result = find_eligible_sessions(sessions, criteria)

    assert result == [eligible_one, eligible_two]


def test_find_eligible_sessions_returns_empty_list_for_no_matches():
    session = _make_session(status=RecordingStatus.RECORDING, protected=False)
    criteria = RetentionCriteria(older_than=_now())

    assert find_eligible_sessions([session], criteria) == []


def test_find_eligible_sessions_handles_empty_input():
    criteria = RetentionCriteria(older_than=_now())

    assert find_eligible_sessions([], criteria) == []


# ---------------------------------------------------------------------
# 7. Read-only: never mutates the session, never deletes anything
# ---------------------------------------------------------------------


def test_is_eligible_for_cleanup_does_not_mutate_session():
    old_ended_at = _now() - timedelta(days=30)
    session = _make_session(
        status=RecordingStatus.STOPPED, protected=False, ended_at=old_ended_at
    )
    criteria = RetentionCriteria(older_than=_now())

    status_before = session.status
    protected_before = session.protected
    ended_at_before = session.ended_at

    is_eligible_for_cleanup(session, criteria)

    assert session.status == status_before
    assert session.protected == protected_before
    assert session.ended_at == ended_at_before


def test_retention_module_exposes_no_delete_capable_function():
    """Regression guard, mirroring test_storage_policy.py's own guard:
    this module must not grow a delete/remove/purge/cleanup-performing
    function — only eligibility checks. 'find_eligible_sessions' and
    'is_eligible_for_cleanup' are checks, not actions, so they're
    excluded from the forbidden-substring scan below.
    """
    import recording.retention as retention_module

    forbidden_substrings = ("delete", "remove", "purge", "unlink", "rm_")
    allowed_names = {"is_eligible_for_cleanup", "find_eligible_sessions"}

    public_names = [
        name
        for name in dir(retention_module)
        if not name.startswith("_") and callable(getattr(retention_module, name))
    ]
    assert public_names, "expected retention.py to expose public functions"

    for name in public_names:
        if name in allowed_names:
            continue
        lowered = name.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), (
            f"retention.{name} looks like a deletion function — Task 13 "
            "must not add any file-deletion capability"
        )
