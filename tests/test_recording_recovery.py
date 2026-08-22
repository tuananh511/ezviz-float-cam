"""
tests/test_recording_recovery.py

Focused unit tests for src/recording/recovery.py (recover_session,
recover_all, discover_session_dirs) — Task 8 of the Player/Recorder
migration (crash/session recovery).

Like test_recording_session.py, test_recording_metadata.py and
test_storage_policy.py, this module is standard-library only: no
PySide6, no VLC, and all filesystem access goes through tmp_path
(pytest's built-in temp directory fixture) — no writes outside the
test's own sandbox.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from recording import (
    RecordingMetadataStore,
    RecordingSegment,
    RecordingSession,
    RecordingStatus,
    RecoveryOutcome,
    SESSION_DIR_PREFIX,
    discover_session_dirs,
    recover_all,
    recover_session,
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


def _write_mkv(session_dir, name, size_bytes=0):
    path = session_dir / name
    path.write_bytes(b"\x00" * size_bytes)
    return path


# ---------------------------------------------------------------------
# 1. Discovery: valid sessions found, unrelated entries ignored
# ---------------------------------------------------------------------


def test_discover_finds_valid_emergency_session_dirs(tmp_path):
    d1 = _make_session_dir(tmp_path, "session-one")
    d2 = _make_session_dir(tmp_path, "session-two")
    _persist(d1, RecordingSession())
    _persist(d2, RecordingSession())

    found = discover_session_dirs(tmp_path)

    assert sorted(p.name for p in found) == sorted([d1.name, d2.name])


def test_discover_ignores_unrelated_directories_and_files(tmp_path):
    _make_session_dir(tmp_path, "real-session")
    (tmp_path / "not_a_session_dir").mkdir()
    (tmp_path / "random_file.txt").write_text("hello")
    (tmp_path / "emergency_session_but_a_file.json").write_text("{}")

    found = discover_session_dirs(tmp_path)

    assert [p.name for p in found] == [f"{SESSION_DIR_PREFIX}real-session"]


def test_discover_returns_empty_list_for_missing_base_dir(tmp_path):
    missing = tmp_path / "does_not_exist"
    assert discover_session_dirs(missing) == []


# ---------------------------------------------------------------------
# 2. Recovering interrupted sessions: STARTING / RECORDING / STOPPING
# ---------------------------------------------------------------------


def test_recover_session_starting_becomes_failed(tmp_path):
    session_dir = _make_session_dir(tmp_path, "s1")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    _persist(session_dir, session)

    result = recover_session(session_dir)

    assert result.outcome == RecoveryOutcome.RECOVERED
    assert result.session.status == RecordingStatus.FAILED
    assert result.session.error is not None
    assert "STARTING" in result.session.error
    assert result.session.ended_at is not None

    # Persisted back to disk.
    reloaded = RecordingMetadataStore(session_dir).load()
    assert reloaded.status == RecordingStatus.FAILED


def test_recover_session_recording_with_completed_segments(tmp_path):
    session_dir = _make_session_dir(tmp_path, "s2")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)

    seg = RecordingSegment(path=str(session_dir / "0001.mkv"), started_at=_utcnow())
    seg.mark_completed(size_bytes=5000)
    session.add_segment(seg)
    session.recalculate_total_bytes()
    _write_mkv(session_dir, "0001.mkv", size_bytes=5000)
    _persist(session_dir, session)

    result = recover_session(session_dir)

    assert result.outcome == RecoveryOutcome.RECOVERED
    assert result.session.status == RecordingStatus.FAILED
    assert len(result.session.segments) == 1
    assert result.session.segments[0].completed is True
    assert result.session.segments[0].size_bytes == 5000
    assert result.session.total_bytes == 5000


def test_recover_session_stopping_becomes_failed(tmp_path):
    session_dir = _make_session_dir(tmp_path, "s3")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    session.transition_to(RecordingStatus.STOPPING)
    _persist(session_dir, session)

    result = recover_session(session_dir)

    assert result.outcome == RecoveryOutcome.RECOVERED
    assert result.session.status == RecordingStatus.FAILED
    assert "STOPPING" in result.session.error


# ---------------------------------------------------------------------
# 3. Terminal sessions are preserved, not "recovered" again
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "terminal_status",
    [RecordingStatus.STOPPED, RecordingStatus.FAILED, RecordingStatus.DISK_FULL],
)
def test_terminal_sessions_are_reported_and_untouched(tmp_path, terminal_status):
    session_dir = _make_session_dir(tmp_path, "term")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    if terminal_status == RecordingStatus.STOPPED:
        session.transition_to(RecordingStatus.RECORDING)
        session.transition_to(RecordingStatus.STOPPING)
        session.transition_to(RecordingStatus.STOPPED)
    else:
        session.transition_to(terminal_status)
    store = _persist(session_dir, session)

    before_mtime = (session_dir / "session.json").stat().st_mtime_ns
    before_raw = (session_dir / "session.json").read_text(encoding="utf-8")

    result = recover_session(session_dir)

    assert result.outcome == RecoveryOutcome.ALREADY_TERMINAL
    assert result.session.status == terminal_status

    after_raw = (session_dir / "session.json").read_text(encoding="utf-8")
    assert after_raw == before_raw  # byte-for-byte untouched


# ---------------------------------------------------------------------
# 4. Reconciling segment file sizes / total_bytes recalculation
# ---------------------------------------------------------------------


def test_recover_populates_missing_size_bytes_from_stat(tmp_path):
    session_dir = _make_session_dir(tmp_path, "s4")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)

    seg = RecordingSegment(path=str(session_dir / "seg.mkv"), started_at=_utcnow())
    # Marked completed but size_bytes was never recorded (0).
    seg.mark_completed(size_bytes=0)
    session.add_segment(seg)
    _write_mkv(session_dir, "seg.mkv", size_bytes=42_000)
    _persist(session_dir, session)

    result = recover_session(session_dir)

    assert result.session.segments[0].size_bytes == 42_000
    assert result.session.total_bytes == 42_000


def test_recover_recalculates_total_bytes_across_multiple_segments(tmp_path):
    session_dir = _make_session_dir(tmp_path, "s5")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)

    seg1 = RecordingSegment(path=str(session_dir / "a.mkv"), started_at=_utcnow())
    seg1.mark_completed(size_bytes=1000)
    seg2 = RecordingSegment(path=str(session_dir / "b.mkv"), started_at=_utcnow())
    seg2.mark_completed(size_bytes=2000)
    # An incomplete, still-being-written segment — must NOT be counted.
    seg3 = RecordingSegment(path=str(session_dir / "c.mkv"), started_at=_utcnow())

    session.add_segment(seg1)
    session.add_segment(seg2)
    session.add_segment(seg3)

    _write_mkv(session_dir, "a.mkv", size_bytes=1000)
    _write_mkv(session_dir, "b.mkv", size_bytes=2000)
    _write_mkv(session_dir, "c.mkv", size_bytes=500)  # partial, in-progress file

    _persist(session_dir, session)

    result = recover_session(session_dir)

    assert result.session.total_bytes == 3000
    # The incomplete segment is not fabricated into "completed".
    incomplete = [s for s in result.session.segments if s.path.endswith("c.mkv")][0]
    assert incomplete.completed is False
    assert incomplete.ended_at is None


def test_recover_does_not_fabricate_completion_for_incomplete_segment(tmp_path):
    session_dir = _make_session_dir(tmp_path, "s6")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)

    seg = RecordingSegment(path=str(session_dir / "live.mkv"), started_at=_utcnow())
    session.add_segment(seg)
    _write_mkv(session_dir, "live.mkv", size_bytes=999)
    _persist(session_dir, session)

    result = recover_session(session_dir)

    seg_after = result.session.segments[0]
    assert seg_after.completed is False
    assert seg_after.ended_at is None
    assert seg_after.size_bytes == 0
    assert result.session.total_bytes == 0


# ---------------------------------------------------------------------
# 5. ended_at preservation
# ---------------------------------------------------------------------


def test_recover_preserves_existing_ended_at(tmp_path):
    session_dir = _make_session_dir(tmp_path, "s7")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    session.transition_to(RecordingStatus.STOPPING)

    fixed_ended_at = _utcnow() - timedelta(hours=1)
    # STOPPING has no ended_at by default (only set on entering an end
    # state); simulate a session that somehow already recorded one.
    session.ended_at = fixed_ended_at
    _persist(session_dir, session)

    result = recover_session(session_dir)

    # microsecond precision preserved through JSON round-trip
    assert abs((result.session.ended_at - fixed_ended_at).total_seconds()) < 0.001


def test_recover_sets_ended_at_when_missing(tmp_path):
    session_dir = _make_session_dir(tmp_path, "s8")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    assert session.ended_at is None
    _persist(session_dir, session)

    result = recover_session(session_dir)

    assert result.session.ended_at is not None


# ---------------------------------------------------------------------
# 6. Missing / invalid session.json, malformed session directories
# ---------------------------------------------------------------------


def test_recover_session_missing_session_json_is_invalid(tmp_path):
    session_dir = _make_session_dir(tmp_path, "no-meta")
    # No session.json written at all.

    result = recover_session(session_dir)

    assert result.outcome == RecoveryOutcome.INVALID
    assert result.session is None
    assert result.error is not None


def test_recover_session_malformed_json_is_invalid(tmp_path):
    session_dir = _make_session_dir(tmp_path, "bad-json")
    (session_dir / "session.json").write_text("{not valid json", encoding="utf-8")

    result = recover_session(session_dir)

    assert result.outcome == RecoveryOutcome.INVALID
    assert result.error is not None


def test_recover_session_missing_required_field_is_invalid(tmp_path):
    session_dir = _make_session_dir(tmp_path, "missing-field")
    session = RecordingSession()
    _persist(session_dir, session)

    raw = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    del raw["status"]
    (session_dir / "session.json").write_text(json.dumps(raw), encoding="utf-8")

    result = recover_session(session_dir)

    assert result.outcome == RecoveryOutcome.INVALID
    assert "status" in result.error


def test_discover_includes_emergency_dir_with_no_session_json(tmp_path):
    # Discovery filters by name only; a malformed/empty session dir is
    # still surfaced (as INVALID via recover_session), never silently
    # dropped at the discovery stage.
    session_dir = _make_session_dir(tmp_path, "empty-dir")

    found = discover_session_dirs(tmp_path)
    assert session_dir in found


# ---------------------------------------------------------------------
# 7. One bad session does not block recovery of another
# ---------------------------------------------------------------------


def test_recover_all_one_bad_session_does_not_block_others(tmp_path):
    good_dir = _make_session_dir(tmp_path, "good")
    good_session = RecordingSession()
    good_session.transition_to(RecordingStatus.STARTING)
    _persist(good_dir, good_session)

    bad_dir = _make_session_dir(tmp_path, "bad")
    (bad_dir / "session.json").write_text("{not valid json", encoding="utf-8")

    report = recover_all(tmp_path)

    assert len(report.recovered) == 1
    assert report.recovered[0].session_dir == good_dir
    assert len(report.invalid) == 1
    assert report.invalid[0].session_dir == bad_dir


def test_recover_all_structured_report_categorizes_all_outcomes(tmp_path):
    recovering_dir = _make_session_dir(tmp_path, "recovering")
    recovering_session = RecordingSession()
    recovering_session.transition_to(RecordingStatus.STARTING)
    _persist(recovering_dir, recovering_session)

    terminal_dir = _make_session_dir(tmp_path, "terminal")
    terminal_session = RecordingSession()
    terminal_session.transition_to(RecordingStatus.STARTING)
    terminal_session.transition_to(RecordingStatus.FAILED, error="disk write error")
    _persist(terminal_dir, terminal_session)

    invalid_dir = _make_session_dir(tmp_path, "invalid")
    (invalid_dir / "session.json").write_text("nonsense", encoding="utf-8")

    report = recover_all(tmp_path)

    assert {r.session_dir for r in report.recovered} == {recovering_dir}
    assert {r.session_dir for r in report.already_terminal} == {terminal_dir}
    assert {r.session_dir for r in report.invalid} == {invalid_dir}
    assert report.failed == []
    assert len(report.results) == 3


# ---------------------------------------------------------------------
# 8. Idempotency: running recovery twice does not mutate an already
#    recovered terminal session again
# ---------------------------------------------------------------------


def test_recover_all_is_idempotent(tmp_path):
    session_dir = _make_session_dir(tmp_path, "idempotent")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    _persist(session_dir, session)

    first_report = recover_all(tmp_path)
    assert len(first_report.recovered) == 1

    raw_after_first = (session_dir / "session.json").read_text(encoding="utf-8")

    second_report = recover_all(tmp_path)
    assert len(second_report.recovered) == 0
    assert len(second_report.already_terminal) == 1

    raw_after_second = (session_dir / "session.json").read_text(encoding="utf-8")
    assert raw_after_first == raw_after_second


# ---------------------------------------------------------------------
# 9. No deletion of .mkv files, ever
# ---------------------------------------------------------------------


def test_recover_never_deletes_mkv_files(tmp_path):
    session_dir = _make_session_dir(tmp_path, "keep-files")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)

    seg = RecordingSegment(path=str(session_dir / "keep.mkv"), started_at=_utcnow())
    seg.mark_completed(size_bytes=10)
    session.add_segment(seg)
    mkv_path = _write_mkv(session_dir, "keep.mkv", size_bytes=10)
    # An orphan .mkv with no matching segment metadata at all.
    orphan_path = _write_mkv(session_dir, "orphan.mkv", size_bytes=77)

    _persist(session_dir, session)

    recover_session(session_dir)

    assert mkv_path.exists()
    assert orphan_path.exists()


def test_recover_all_never_deletes_any_mkv_across_multiple_sessions(tmp_path):
    dirs_and_files = []
    for i in range(3):
        d = _make_session_dir(tmp_path, f"multi-{i}")
        s = RecordingSession()
        s.transition_to(RecordingStatus.STARTING)
        _persist(d, s)
        f = _write_mkv(d, "seg.mkv", size_bytes=100)
        dirs_and_files.append(f)

    recover_all(tmp_path)

    for f in dirs_and_files:
        assert f.exists()


# ---------------------------------------------------------------------
# 10. No VLC / PySide6 dependency anywhere in the recovery module
# ---------------------------------------------------------------------


def test_recovery_module_source_has_no_vlc_or_pyside_imports():
    import recording.recovery as recovery_module

    source_path = recovery_module.__file__
    with open(source_path, "r", encoding="utf-8") as f:
        source = f.read()

    assert "import vlc" not in source
    assert "from vlc" not in source
    assert "import PySide6" not in source
    assert "from PySide6" not in source


def test_recovery_module_does_not_import_vlc_or_pyside_at_runtime():
    # The fake `vlc` module is installed globally by tests/conftest.py for
    # the whole suite (so `import recorder` works elsewhere); what matters
    # here is that recording.recovery itself never references it or
    # PySide6 anywhere in its own namespace/module graph dependency, which
    # the source-scan test above already verifies directly. This test
    # additionally confirms recording.recovery can be used without
    # PySide6's QtCore machinery being involved at all.
    import recording.recovery as recovery_module

    assert not hasattr(recovery_module, "vlc")
    assert not hasattr(recovery_module, "PySide6")


# ---------------------------------------------------------------------
# 11. Reading actual persisted JSON on disk (not just mocks)
# ---------------------------------------------------------------------


def test_recovered_session_json_on_disk_reflects_failed_status(tmp_path):
    session_dir = _make_session_dir(tmp_path, "on-disk-check")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    _persist(session_dir, session)

    recover_session(session_dir)

    raw = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    assert raw["status"] == "FAILED"
    assert raw["ended_at"] is not None
    assert raw["error"] is not None


def test_recovered_session_json_on_disk_has_recalculated_total_bytes(tmp_path):
    session_dir = _make_session_dir(tmp_path, "on-disk-bytes")
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)

    seg = RecordingSegment(path=str(session_dir / "x.mkv"), started_at=_utcnow())
    seg.mark_completed(size_bytes=0)
    session.add_segment(seg)
    _write_mkv(session_dir, "x.mkv", size_bytes=12_345)
    _persist(session_dir, session)

    recover_session(session_dir)

    raw = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    assert raw["total_bytes"] == 12_345
    assert raw["segments"][0]["size_bytes"] == 12_345
