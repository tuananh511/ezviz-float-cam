"""
tests/test_storage_policy.py

Focused unit tests for src/recording/storage.py (StoragePolicy,
StorageDecision, StorageCheckResult, DiskStatError) and the Task 4
extension to RecordingSession (recalculate_total_bytes) — Task 4 of the
Player/Recorder migration.

Like test_recording_session.py, this module is standard-library only:
no PySide6, no VLC, no real filesystem writes (shutil.disk_usage is
monkeypatched so the results are deterministic and don't depend on the
actual free space of whatever machine runs the suite).
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from recording import (
    DEFAULT_LOW_FREE_BYTES,
    DEFAULT_MIN_FREE_BYTES,
    DiskStatError,
    InvalidTransitionError,
    RecordingSegment,
    RecordingSession,
    RecordingStatus,
    StorageCheckResult,
    StorageDecision,
    StoragePolicy,
)


def _usage(total: int, used: int, free: int) -> SimpleNamespace:
    """Build an object shaped like shutil.disk_usage()'s namedtuple."""
    return SimpleNamespace(total=total, used=used, free=free)


def _patch_disk_usage(monkeypatch, *, free: int, total: int = 500 * 1024 ** 3):
    """Monkeypatch shutil.disk_usage (as looked up from storage.py) to
    return a fixed `free` value regardless of the path passed in."""

    def fake_disk_usage(path):
        return _usage(total=total, used=total - free, free=free)

    monkeypatch.setattr(shutil, "disk_usage", fake_disk_usage)


# ---------------------------------------------------------------------
# 1. Enough disk space -> ALLOW
# ---------------------------------------------------------------------


def test_check_allows_when_plenty_of_free_space(tmp_path, monkeypatch):
    _patch_disk_usage(monkeypatch, free=DEFAULT_LOW_FREE_BYTES + 1)
    policy = StoragePolicy(tmp_path)

    result = policy.check()

    assert result.decision is StorageDecision.ALLOW
    assert result.allows_new_segment() is True
    assert policy.may_start_new_segment() is True
    assert result.error is None
    assert result.free_bytes == DEFAULT_LOW_FREE_BYTES + 1


# ---------------------------------------------------------------------
# 2. Low but still sufficient space -> ALLOW_LOW_SPACE (distinct from
#    plain ALLOW and from DISK_FULL)
# ---------------------------------------------------------------------


def test_check_distinguishes_low_space_from_plenty_and_from_full(
    tmp_path, monkeypatch
):
    # Strictly between the two thresholds.
    free = (DEFAULT_MIN_FREE_BYTES + DEFAULT_LOW_FREE_BYTES) // 2
    _patch_disk_usage(monkeypatch, free=free)
    policy = StoragePolicy(tmp_path)

    result = policy.check()

    assert result.decision is StorageDecision.ALLOW_LOW_SPACE
    assert result.decision is not StorageDecision.ALLOW
    assert result.decision is not StorageDecision.DISK_FULL
    assert result.allows_new_segment() is True
    assert policy.may_start_new_segment() is True


# ---------------------------------------------------------------------
# 3. Below the safety threshold -> reject (DISK_FULL)
# ---------------------------------------------------------------------


def test_check_rejects_when_below_min_free_bytes(tmp_path, monkeypatch):
    _patch_disk_usage(monkeypatch, free=DEFAULT_MIN_FREE_BYTES - 1)
    policy = StoragePolicy(tmp_path)

    result = policy.check()

    assert result.decision is StorageDecision.DISK_FULL
    assert result.allows_new_segment() is False
    assert policy.may_start_new_segment() is False
    assert "an toàn" in result.reason or result.reason  # a real reason is set
    assert result.error is None  # this is a policy decision, not a failure


def test_check_rejects_when_essentially_zero_free_space(tmp_path, monkeypatch):
    _patch_disk_usage(monkeypatch, free=0)
    policy = StoragePolicy(tmp_path)

    result = policy.check()

    assert result.decision is StorageDecision.DISK_FULL
    assert policy.may_start_new_segment() is False


# ---------------------------------------------------------------------
# 4. Filesystem stat failure is handled explicitly, not swallowed
# ---------------------------------------------------------------------


def test_check_reports_check_failed_on_stat_error(tmp_path, monkeypatch):
    underlying = OSError("simulated stat failure")

    def failing_disk_usage(path):
        raise underlying

    monkeypatch.setattr(shutil, "disk_usage", failing_disk_usage)
    policy = StoragePolicy(tmp_path)

    result = policy.check()

    assert result.decision is StorageDecision.CHECK_FAILED
    # A CHECK_FAILED result must NEVER be treated as "safe to proceed".
    assert result.allows_new_segment() is False
    assert policy.may_start_new_segment() is False
    # The original error must be preserved, not swallowed.
    assert result.error is not None
    assert isinstance(result.error, DiskStatError)
    assert result.error.__cause__ is underlying
    assert result.free_bytes is None


def test_check_does_not_raise_on_real_existing_path():
    """check() must return a StorageCheckResult (never raise) for an
    ordinary, real, existing path — exercised here without monkeypatching
    disk_usage at all, using the real filesystem. The stat-failure path
    itself (an OSError from disk_usage) is covered by
    test_check_reports_check_failed_on_stat_error above."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        policy = StoragePolicy(tmp)
        result = policy.check()  # real disk_usage call, no monkeypatch
        assert isinstance(result, StorageCheckResult)
        assert result.decision in (
            StorageDecision.ALLOW,
            StorageDecision.ALLOW_LOW_SPACE,
            StorageDecision.DISK_FULL,
        )


# ---------------------------------------------------------------------
# 5. Boundary conditions of the free-space thresholds
# ---------------------------------------------------------------------


def test_boundary_free_exactly_at_min_threshold_is_low_space_not_full(
    tmp_path, monkeypatch
):
    """free == min_free_bytes must NOT be DISK_FULL — the safety
    threshold is a "less than" cutoff, so being exactly at the floor is
    still (barely) safe."""
    _patch_disk_usage(monkeypatch, free=DEFAULT_MIN_FREE_BYTES)
    policy = StoragePolicy(tmp_path)

    result = policy.check()

    assert result.decision is not StorageDecision.DISK_FULL
    assert result.decision is StorageDecision.ALLOW_LOW_SPACE
    assert result.allows_new_segment() is True


def test_boundary_free_one_byte_below_min_threshold_is_full(tmp_path, monkeypatch):
    _patch_disk_usage(monkeypatch, free=DEFAULT_MIN_FREE_BYTES - 1)
    policy = StoragePolicy(tmp_path)

    assert policy.check().decision is StorageDecision.DISK_FULL


def test_boundary_free_exactly_at_low_threshold_is_allow_not_low_space(
    tmp_path, monkeypatch
):
    _patch_disk_usage(monkeypatch, free=DEFAULT_LOW_FREE_BYTES)
    policy = StoragePolicy(tmp_path)

    result = policy.check()

    assert result.decision is StorageDecision.ALLOW
    assert result.decision is not StorageDecision.ALLOW_LOW_SPACE


def test_boundary_free_one_byte_below_low_threshold_is_low_space(
    tmp_path, monkeypatch
):
    _patch_disk_usage(monkeypatch, free=DEFAULT_LOW_FREE_BYTES - 1)
    policy = StoragePolicy(tmp_path)

    assert policy.check().decision is StorageDecision.ALLOW_LOW_SPACE


def test_custom_thresholds_are_respected_instead_of_defaults(tmp_path, monkeypatch):
    _patch_disk_usage(monkeypatch, free=500)
    policy = StoragePolicy(tmp_path, min_free_bytes=100, low_free_bytes=1000)

    assert policy.check().decision is StorageDecision.ALLOW_LOW_SPACE

    _patch_disk_usage(monkeypatch, free=50)
    assert policy.check().decision is StorageDecision.DISK_FULL


def test_constructor_rejects_low_threshold_below_min_threshold(tmp_path):
    with pytest.raises(ValueError):
        StoragePolicy(tmp_path, min_free_bytes=1000, low_free_bytes=999)


def test_constructor_rejects_negative_min_free_bytes(tmp_path):
    with pytest.raises(ValueError):
        StoragePolicy(tmp_path, min_free_bytes=-1)


def test_constructor_accepts_equal_thresholds(tmp_path, monkeypatch):
    """low_free_bytes == min_free_bytes is a degenerate-but-valid config
    (no separate 'low space' band) — not an error."""
    policy = StoragePolicy(tmp_path, min_free_bytes=1000, low_free_bytes=1000)
    _patch_disk_usage(monkeypatch, free=1000)
    assert policy.check().decision is StorageDecision.ALLOW


# ---------------------------------------------------------------------
# 6. recording_dir need not exist yet
# ---------------------------------------------------------------------


def test_check_works_when_recording_dir_does_not_exist_yet(tmp_path, monkeypatch):
    """recorder.py only mkdir()s the recording directory when a
    recording actually starts — the policy must still be able to check
    free space (of the nearest existing ancestor) beforehand."""
    not_yet_created = tmp_path / "emergency_some-session-id"
    assert not not_yet_created.exists()
    _patch_disk_usage(monkeypatch, free=DEFAULT_LOW_FREE_BYTES + 1)

    policy = StoragePolicy(not_yet_created)
    result = policy.check()

    assert result.decision is StorageDecision.ALLOW
    # It must have stat'd an ancestor that actually exists (tmp_path),
    # not the non-existent recording_dir itself.
    assert result.checked_path == tmp_path


# ---------------------------------------------------------------------
# 7. Policy never deletes anything — active session segments are safe
#    by construction, not just by a runtime check
# ---------------------------------------------------------------------


def test_storage_policy_exposes_no_delete_capable_method():
    """Regression guard: StoragePolicy must not grow a delete/remove/
    purge/cleanup method. The 'never delete an active session's segment'
    requirement is met by StoragePolicy having no deletion capability at
    all, not by a conditional that could later be weakened."""
    forbidden_substrings = ("delete", "remove", "purge", "cleanup", "unlink", "rm_")
    public_methods = [
        name
        for name in dir(StoragePolicy)
        if not name.startswith("_") and callable(getattr(StoragePolicy, name))
    ]
    assert public_methods, "expected StoragePolicy to have public methods"
    for name in public_methods:
        lowered = name.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), (
            f"StoragePolicy.{name} looks like a deletion method — Task 4 "
            "must not add any auto-delete capability"
        )


def test_checking_disk_space_never_touches_an_active_session_segments(
    tmp_path, monkeypatch
):
    _patch_disk_usage(monkeypatch, free=DEFAULT_MIN_FREE_BYTES - 1)  # DISK_FULL
    policy = StoragePolicy(tmp_path)

    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    active_segment = RecordingSegment(
        path=str(tmp_path / "active.mkv"), started_at=datetime.now(timezone.utc)
    )
    session.add_segment(active_segment)

    for _ in range(5):
        policy.check()  # repeated DISK_FULL checks

    # The active session's segment list is completely untouched.
    assert session.segments == [active_segment]
    assert session.segments[0] is active_segment
    assert Path(active_segment.path) == tmp_path / "active.mkv"


# ---------------------------------------------------------------------
# 8. apply_to_session: DISK_FULL decision drives the session state
#    machine; other decisions leave the session alone
# ---------------------------------------------------------------------


def test_apply_to_session_transitions_recording_session_to_disk_full(
    tmp_path, monkeypatch
):
    _patch_disk_usage(monkeypatch, free=DEFAULT_MIN_FREE_BYTES - 1)
    policy = StoragePolicy(tmp_path)

    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)

    result = policy.apply_to_session(session)

    assert result.decision is StorageDecision.DISK_FULL
    assert session.status is RecordingStatus.DISK_FULL
    assert session.error == result.reason
    assert session.ended_at is not None


def test_apply_to_session_does_not_try_to_create_a_new_segment():
    """No new-segment creation happens anywhere in this module — the
    absence of any 'create segment'/VLC call is itself the guarantee
    that a DISK_FULL decision never results in a new segment attempt.
    This is exercised implicitly by every test above never observing
    recorder/VLC objects; this test just documents the module's public
    surface stays limited to check()/may_start_new_segment()/
    apply_to_session()."""
    public_api = {
        name
        for name in dir(StoragePolicy)
        if not name.startswith("_") and callable(getattr(StoragePolicy, name))
    }
    assert public_api == {"check", "may_start_new_segment", "apply_to_session"}


@pytest.mark.parametrize(
    "decision_free_bytes",
    [DEFAULT_LOW_FREE_BYTES + 1, (DEFAULT_MIN_FREE_BYTES + DEFAULT_LOW_FREE_BYTES) // 2],
)
def test_apply_to_session_leaves_session_untouched_when_allowed(
    tmp_path, monkeypatch, decision_free_bytes
):
    _patch_disk_usage(monkeypatch, free=decision_free_bytes)
    policy = StoragePolicy(tmp_path)

    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)

    policy.apply_to_session(session)

    assert session.status is RecordingStatus.RECORDING
    assert session.error is None
    assert session.ended_at is None


def test_apply_to_session_leaves_session_untouched_on_check_failed(
    tmp_path, monkeypatch
):
    def failing_disk_usage(path):
        raise OSError("simulated failure")

    monkeypatch.setattr(shutil, "disk_usage", failing_disk_usage)
    policy = StoragePolicy(tmp_path)

    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)

    result = policy.apply_to_session(session)

    assert result.decision is StorageDecision.CHECK_FAILED
    assert session.status is RecordingStatus.RECORDING
    assert session.error is None


def test_apply_to_session_propagates_invalid_transition_instead_of_swallowing(
    tmp_path, monkeypatch
):
    """A session that isn't RECORDING can't legally go to DISK_FULL
    (see session.py's _ALLOWED_TRANSITIONS). apply_to_session must not
    hide that behind a silent no-op — it's a caller bug to fix, not a
    condition to swallow."""
    _patch_disk_usage(monkeypatch, free=DEFAULT_MIN_FREE_BYTES - 1)
    policy = StoragePolicy(tmp_path)

    session = RecordingSession()  # still IDLE
    with pytest.raises(InvalidTransitionError):
        policy.apply_to_session(session)


# ---------------------------------------------------------------------
# 9. RecordingSession.recalculate_total_bytes (Task 4's minimal
#    extension to the session domain model)
# ---------------------------------------------------------------------


def test_recalculate_total_bytes_sums_only_completed_segments():
    session = RecordingSession()
    done = RecordingSegment(
        path="/tmp/a.mkv", started_at=datetime.now(timezone.utc)
    )
    done.mark_completed(size_bytes=1024)
    session.add_segment(done)

    total = session.recalculate_total_bytes()

    assert total == 1024
    assert session.total_bytes == 1024


def test_recalculate_total_bytes_excludes_incomplete_segment():
    session = RecordingSession()
    done = RecordingSegment(
        path="/tmp/a.mkv", started_at=datetime.now(timezone.utc)
    )
    done.mark_completed(size_bytes=1024)
    session.add_segment(done)

    pending = RecordingSegment(
        path="/tmp/b.mkv", started_at=datetime.now(timezone.utc)
    )
    # Simulate a partially-written file's on-disk size that hasn't been
    # finalized yet — must NOT be counted until mark_completed() runs.
    pending.size_bytes = 777
    session.add_segment(pending)

    total = session.recalculate_total_bytes()

    assert total == 1024
    assert session.total_bytes == 1024


def test_recalculate_total_bytes_updates_after_second_segment_completes():
    session = RecordingSession()
    seg1 = RecordingSegment(path="/tmp/a.mkv", started_at=datetime.now(timezone.utc))
    seg1.mark_completed(size_bytes=1000)
    session.add_segment(seg1)
    session.recalculate_total_bytes()
    assert session.total_bytes == 1000

    seg2 = RecordingSegment(path="/tmp/b.mkv", started_at=datetime.now(timezone.utc))
    session.add_segment(seg2)  # still incomplete
    assert session.recalculate_total_bytes() == 1000  # unchanged

    seg2.mark_completed(size_bytes=500)
    assert session.recalculate_total_bytes() == 1500


def test_recalculate_total_bytes_on_empty_session_is_zero():
    session = RecordingSession()
    assert session.recalculate_total_bytes() == 0


# ---------------------------------------------------------------------
# 10. No dependency on PySide6/VLC (mirrors the guard in
#     test_recording_session.py, scoped to storage.py specifically)
# ---------------------------------------------------------------------


def test_storage_module_imports_no_pyside6_or_vlc():
    import ast

    storage_file = (
        Path(__file__).resolve().parent.parent / "src" / "recording" / "storage.py"
    )
    tree = ast.parse(storage_file.read_text(encoding="utf-8"))
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)

    forbidden_prefixes = ("PySide6", "vlc", "shiboken6")
    offending = [
        name
        for name in imported_names
        if any(name == p or name.startswith(p + ".") for p in forbidden_prefixes)
    ]
    assert not offending, f"storage.py imports forbidden module(s): {offending}"
