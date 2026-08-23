"""
tests/test_recording_lifecycle_hardening.py

Task 10 of the Player/Recorder migration — "Recording Lifecycle
Hardening". This file does NOT re-architect anything in
src/recorder.py, src/recording/session.py, src/recording/storage.py,
src/recording/metadata.py, or src/recording/recovery.py — it is a
focused audit pass that pins down (and, for one real gap found during
the audit, regression-tests the fix for) lifecycle edge cases across
the recorder/session/metadata/storage/recovery integration:

- state-machine consistency across every reachable transition
- start()/stop() idempotency and truthfulness on every failure path
- segment rotation never racing past a terminal session, never
  double-creating a QTimer, and never resurrecting a stopped session
- StoragePolicy decisions (ALLOW/ALLOW_LOW_SPACE/DISK_FULL/
  CHECK_FAILED) are honored exactly, with no segment ever deleted
- recovery output never collides with, or is silently reused by, a
  live EmergencyRecorder session
- metadata write failures never leave VLC leaked or the session
  resurrected, and never get swallowed silently
- VLC resource cleanup on every partial-construction failure path,
  including the "media" object created by instance.media_new() (the
  one concrete bug this audit found — see
  test_start_segment_media_object_released_on_partial_setup_failure
  below: before this task, _start_segment()'s except-block cleaned up
  media_player/instance but never called media.release(), despite its
  own docstring claiming otherwise)

No real VLC binary and no real RTSP camera are used — `vlc` is fully
faked in conftest.py, same as tests/test_recorder.py.
"""

import shutil
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from recorder import EmergencyRecorder
from recording import (
    RecordingMetadataStore,
    RecordingSession,
    RecordingStatus,
)
from recording.startup import run_startup_recovery

RTSP_CFG = {
    "ip": "192.168.1.50",
    "port": 554,
    "username": "admin",
    "password": "s3cret",
    "stream_type": "sub",
    "channel": "ch1",
}


def _fake_disk_usage(total: int, used: int, free: int):
    def _inner(path):
        return SimpleNamespace(total=total, used=used, free=free)

    return _inner


_DISK_FULL_FREE = 100_000  # well under DEFAULT_MIN_FREE_BYTES (1 GiB)


def _force_disk_full(monkeypatch):
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        _fake_disk_usage(total=10_000_000_000, used=9_999_900_000, free=_DISK_FULL_FREE),
    )


def _force_check_failed(monkeypatch):
    def _boom(path):
        raise OSError("disk stat failed (test)")

    monkeypatch.setattr(shutil, "disk_usage", _boom)


# ---------------------------------------------------------------------
# 1. Repeated start() — no duplicate sessions
# ---------------------------------------------------------------------


def test_repeated_start_calls_never_create_a_second_session(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    session = rec._session
    session_dir = rec._session_dir

    for _ in range(3):
        rec.start(RTSP_CFG, save_dir=str(tmp_path))

    assert rec._session is session
    assert rec._session_dir == session_dir
    assert len(session.segments) == 1


# ---------------------------------------------------------------------
# 2. Repeated stop() — idempotent, no resurrection
# ---------------------------------------------------------------------


def test_repeated_stop_calls_are_safe_and_do_not_resurrect_session(
    tmp_path, wired_vlc
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    stopped = []
    rec.recording_stopped.connect(stopped.append)

    for _ in range(4):
        rec.stop()

    assert len(stopped) == 1
    assert rec.is_recording() is False
    assert rec._session.status == RecordingStatus.STOPPED
    # calling stop() again after STOPPED must not re-finalize/re-persist
    # a second segment or flip status away from STOPPED
    assert len(rec._session.segments) == 1
    assert rec._session.segments[0].completed is True


# ---------------------------------------------------------------------
# 3. stop() after at least one rotation
# ---------------------------------------------------------------------


def test_stop_after_rotation_finalizes_the_second_segment_only_once(
    tmp_path, segment_vlc
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    first_segment = rec._session.segments[0]

    rec._rotate_segment()
    second_segment = rec._session.segments[1]
    assert second_segment is not first_segment
    assert not second_segment.completed

    rec.stop()

    assert rec._session.status == RecordingStatus.STOPPED
    assert len(rec._session.segments) == 2
    assert first_segment.completed is True
    assert second_segment.completed is True
    # stop() must not have rotated a THIRD segment into existence
    assert len(segment_vlc) == 2

    loaded = RecordingMetadataStore(rec._session_dir).load()
    assert loaded.status == RecordingStatus.STOPPED
    assert len(loaded.segments) == 2
    assert all(s.completed for s in loaded.segments)


# ---------------------------------------------------------------------
# 4. Rotation must never fire (or create a segment) once the session is
#    terminal — covers all three terminal outcomes it could plausibly
#    be called against.
# ---------------------------------------------------------------------


def test_rotate_segment_after_stop_is_a_pure_noop(tmp_path, segment_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    rec.stop()
    segment_count = len(rec._session.segments)

    rec._rotate_segment()  # simulates a stale/late timer firing after stop()

    assert rec._session.status == RecordingStatus.STOPPED
    assert len(rec._session.segments) == segment_count
    assert len(segment_vlc) == 1
    assert rec.is_recording() is False


def test_rotate_segment_after_disk_full_is_a_pure_noop(
    tmp_path, segment_vlc, monkeypatch
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    _force_disk_full(monkeypatch)
    rec._rotate_segment()  # transitions the session to DISK_FULL
    assert rec._session.status == RecordingStatus.DISK_FULL
    segment_count = len(rec._session.segments)

    rec._rotate_segment()  # a stale timer firing again must still no-op

    assert rec._session.status == RecordingStatus.DISK_FULL
    assert len(rec._session.segments) == segment_count
    assert len(segment_vlc) == 1


def test_rotate_segment_after_failed_via_check_state_is_a_pure_noop(
    tmp_path, wired_vlc, fake_vlc
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    wired_vlc.media_player.get_state.return_value = fake_vlc.State.Error
    rec._check_state()  # transitions the session to FAILED
    assert rec._session.status == RecordingStatus.FAILED
    segment_count = len(rec._session.segments)

    rec._rotate_segment()

    assert rec._session.status == RecordingStatus.FAILED
    assert len(rec._session.segments) == segment_count
    assert rec.is_recording() is False


# ---------------------------------------------------------------------
# 5. Storage denial during rotation — DISK_FULL / CHECK_FAILED
# ---------------------------------------------------------------------


def test_storage_denial_disk_full_during_rotation_keeps_prior_segment_and_stops_timers(
    tmp_path, segment_vlc, monkeypatch
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    first_segment = rec._session.segments[0]
    _force_disk_full(monkeypatch)

    rec._rotate_segment()

    assert rec._session.status == RecordingStatus.DISK_FULL
    assert rec._session.segments == [first_segment]
    assert first_segment.completed is True
    assert len(segment_vlc) == 1  # no second VLC graph created
    assert not rec._watchdog.isActive()
    assert not rec._segment_timer.isActive()
    assert rec._start_time is None


def test_storage_denial_check_failed_during_rotation_never_allows_next_segment(
    tmp_path, segment_vlc, monkeypatch
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    first_segment = rec._session.segments[0]
    _force_check_failed(monkeypatch)

    rec._rotate_segment()

    assert rec._session.status == RecordingStatus.FAILED
    assert rec._session.segments == [first_segment]
    assert len(segment_vlc) == 1
    assert not rec._watchdog.isActive()
    assert not rec._segment_timer.isActive()


# ---------------------------------------------------------------------
# 6. start() failure before any VLC resource is created — no leftover
#    timers, no VLC instance, truthful (STARTING) session state.
# ---------------------------------------------------------------------


def test_start_vlc_failure_before_first_segment_leaves_no_active_timers(
    tmp_path, fake_vlc
):
    fake_vlc.Instance.side_effect = RuntimeError("libvlc init failed")

    rec = EmergencyRecorder()
    with pytest.raises(RuntimeError):
        rec.start(RTSP_CFG, save_dir=str(tmp_path))

    assert rec._session.status == RecordingStatus.STARTING
    assert not rec._watchdog.isActive()
    assert not rec._segment_timer.isActive()
    assert rec._start_time is None
    assert rec.is_recording() is False


def test_start_disk_full_before_any_vlc_leaves_no_active_timers(
    tmp_path, fake_vlc, monkeypatch
):
    _force_disk_full(monkeypatch)

    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    assert rec._session.status == RecordingStatus.DISK_FULL
    assert not rec._watchdog.isActive()
    assert not rec._segment_timer.isActive()
    fake_vlc.Instance.assert_not_called()


# ---------------------------------------------------------------------
# 7. VLC resource cleanup — the concrete bug this audit found: the
#    "media" object (instance.media_new()) was never released on a
#    partial-construction failure, only media_player/instance were.
# ---------------------------------------------------------------------


def test_start_segment_media_object_released_on_partial_setup_failure(
    tmp_path, fake_vlc
):
    """media is created successfully, but a later step (add_option) on
    it fails — the media object itself must still be release()d, not
    just media_player/instance, before the exception propagates."""
    instance_mock = MagicMock(name="vlc_instance")
    media_player_mock = MagicMock(name="media_player")
    media_mock = MagicMock(name="media")
    instance_mock.media_player_new.return_value = media_player_mock
    instance_mock.media_new.return_value = media_mock
    media_mock.add_option.side_effect = RuntimeError("add_option failed")
    fake_vlc.Instance.return_value = instance_mock

    rec = EmergencyRecorder()
    with pytest.raises(RuntimeError, match="add_option failed"):
        rec.start(RTSP_CFG, save_dir=str(tmp_path))

    media_mock.release.assert_called_once()
    media_player_mock.stop.assert_called_once()
    media_player_mock.release.assert_called_once()
    instance_mock.release.assert_called_once()
    assert rec.instance is None
    assert rec.media_player is None
    assert rec.is_recording() is False
    assert rec._session.status == RecordingStatus.STARTING


def test_start_segment_media_object_released_when_play_fails(tmp_path, fake_vlc):
    """Same as above but failing at the very last step (play()), so
    every one of the three VLC resources (Instance/MediaPlayer/Media)
    has already been created and must all be released."""
    instance_mock = MagicMock(name="vlc_instance")
    media_player_mock = MagicMock(name="media_player")
    media_mock = MagicMock(name="media")
    instance_mock.media_player_new.return_value = media_player_mock
    instance_mock.media_new.return_value = media_mock
    media_player_mock.play.side_effect = RuntimeError("play failed")
    fake_vlc.Instance.return_value = instance_mock

    rec = EmergencyRecorder()
    with pytest.raises(RuntimeError, match="play failed"):
        rec.start(RTSP_CFG, save_dir=str(tmp_path))

    media_mock.release.assert_called_once()
    media_player_mock.stop.assert_called_once()
    media_player_mock.release.assert_called_once()
    instance_mock.release.assert_called_once()


def test_start_segment_media_not_released_when_never_created(tmp_path, fake_vlc):
    """If instance.media_new() itself is what fails, media was never
    created — nothing to release() for it, and the mock is never even
    touched."""
    instance_mock = MagicMock(name="vlc_instance")
    media_player_mock = MagicMock(name="media_player")
    instance_mock.media_player_new.return_value = media_player_mock
    instance_mock.media_new.side_effect = RuntimeError("media_new failed")
    fake_vlc.Instance.return_value = instance_mock

    rec = EmergencyRecorder()
    with pytest.raises(RuntimeError, match="media_new failed"):
        rec.start(RTSP_CFG, save_dir=str(tmp_path))

    media_player_mock.stop.assert_called_once()
    media_player_mock.release.assert_called_once()
    instance_mock.release.assert_called_once()
    assert rec._session.status == RecordingStatus.STARTING


def test_rotation_media_object_released_on_partial_setup_failure_for_next_segment(
    tmp_path, segment_vlc, fake_vlc
):
    """Same media-leak bug, but exercised through _rotate_segment()'s
    call to _start_segment() for the SECOND segment, to confirm the fix
    also covers the rotation path (same _start_segment() code, but
    worth pinning down explicitly since rotation has its own except
    branch around the call)."""
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    assert len(segment_vlc) == 1

    next_instance = MagicMock(name="vlc_instance_1")
    next_media_player = MagicMock(name="media_player_1")
    next_media = MagicMock(name="media_1")
    next_instance.media_player_new.return_value = next_media_player
    next_instance.media_new.return_value = next_media
    next_media.add_option.side_effect = RuntimeError("add_option failed")
    fake_vlc.Instance.side_effect = None
    fake_vlc.Instance.return_value = next_instance

    errors = []
    rec.recording_error.connect(errors.append)

    rec._rotate_segment()  # must not raise: rotation catches this itself

    assert len(errors) == 1
    assert rec._session.status == RecordingStatus.FAILED
    next_media.release.assert_called_once()
    next_media_player.stop.assert_called_once()
    next_media_player.release.assert_called_once()
    next_instance.release.assert_called_once()
    assert rec.instance is None
    assert rec.media_player is None
    assert not rec._segment_timer.isActive()
    assert not rec._watchdog.isActive()


# ---------------------------------------------------------------------
# 8. Metadata write failures — never resurrect, never leak VLC, never
#    silently swallowed (an error is always emitted).
# ---------------------------------------------------------------------


def test_metadata_failure_during_stop_leaves_truthful_stopped_state(
    tmp_path, wired_vlc, monkeypatch
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    def _boom(session):
        raise OSError("disk write failed (test)")

    monkeypatch.setattr(rec._metadata_store, "save", _boom)

    errors = []
    rec.recording_error.connect(errors.append)

    rec.stop()  # must not raise

    assert rec._session.status == RecordingStatus.STOPPED
    assert rec.is_recording() is False
    assert rec.instance is None
    assert rec.media_player is None
    assert len(errors) == 1


def test_metadata_failure_during_rotation_finalize_then_disk_full_denial_stays_truthful(
    tmp_path, segment_vlc, monkeypatch
):
    """Both the "finalize" persist (right after the old segment is
    released) AND the "failure" persist (right after transitioning to
    DISK_FULL) fail — the in-memory session must still end up truthful
    (DISK_FULL, no new VLC, timers stopped) even though session.json on
    disk never got either write."""
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    def _boom(session):
        raise OSError("disk write failed (test)")

    monkeypatch.setattr(rec._metadata_store, "save", _boom)
    _force_disk_full(monkeypatch)

    errors = []
    rec.recording_error.connect(errors.append)

    rec._rotate_segment()

    assert rec._session.status == RecordingStatus.DISK_FULL
    assert rec.is_recording() is False
    assert rec.instance is None
    assert rec.media_player is None
    assert not rec._watchdog.isActive()
    assert not rec._segment_timer.isActive()
    # two metadata failures (finalize + failure) plus the DISK_FULL
    # recording_error itself
    assert len(errors) == 3


# ---------------------------------------------------------------------
# 9. No active timers after any terminal failure (watchdog-detected
#    error path specifically, since it is exercised least elsewhere).
# ---------------------------------------------------------------------


def test_no_active_timers_after_check_state_detects_terminal_failure(
    tmp_path, wired_vlc, fake_vlc
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    assert rec._watchdog.isActive()
    assert rec._segment_timer.isActive()

    wired_vlc.media_player.get_state.return_value = fake_vlc.State.Error
    rec._check_state()

    assert rec._session.status == RecordingStatus.FAILED
    assert not rec._watchdog.isActive()
    assert not rec._segment_timer.isActive()


# ---------------------------------------------------------------------
# 10. Recovery interaction — a recovered terminal session is never
#     reused by a live EmergencyRecorder, and its metadata always
#     reloads cleanly through the same RecordingMetadataStore recorder
#     uses.
# ---------------------------------------------------------------------


def test_recovered_session_reloads_through_recording_metadata_store(tmp_path):
    session_dir = tmp_path / "emergency_abc123"
    session_dir.mkdir(parents=True)
    session = RecordingSession(session_id="abc123")
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    RecordingMetadataStore(session_dir).save(session)

    report = run_startup_recovery(str(tmp_path))
    assert len(report.recovered) == 1

    # Recovery must not have produced metadata that RecordingMetadataStore
    # (the same store class EmergencyRecorder relies on) cannot load.
    reloaded = RecordingMetadataStore(session_dir).load()
    assert reloaded.status == RecordingStatus.FAILED
    assert reloaded.session_id == "abc123"


def test_start_after_recovery_creates_independent_session_not_reusing_recovered_one(
    tmp_path, wired_vlc
):
    base_dir = tmp_path / "recordings"
    base_dir.mkdir()
    old_dir = base_dir / "emergency_deadbeef"
    old_dir.mkdir()
    old_session = RecordingSession(session_id="deadbeef")
    old_session.transition_to(RecordingStatus.STARTING)
    old_session.transition_to(RecordingStatus.RECORDING)
    RecordingMetadataStore(old_dir).save(old_session)

    report = run_startup_recovery(str(base_dir))
    assert len(report.recovered) == 1
    assert report.recovered[0].session.status == RecordingStatus.FAILED

    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(base_dir))

    # A brand new session/session_id, never the recovered FAILED one.
    assert rec._session.session_id != "deadbeef"
    assert rec._session.status == RecordingStatus.RECORDING

    # The recovered session's own metadata is left exactly as recovery
    # wrote it — start() never touches another session's directory.
    still_recovered = RecordingMetadataStore(old_dir).load()
    assert still_recovered.status == RecordingStatus.FAILED
    assert still_recovered.session_id == "deadbeef"
