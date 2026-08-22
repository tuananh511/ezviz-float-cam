"""
tests/test_recorder.py

Characterization tests for src/recorder.EmergencyRecorder.

Goal: pin down the CURRENT behavior of EmergencyRecorder (as of the
read-only architecture audit) so a future Player/Recorder refactor can be
regression-tested against a known-good baseline — not to judge whether
that behavior is ideal. Where the current implementation has a real gap
(see test_start_vlc_instance_creation_failure_propagates_uncaught), the
test documents the gap explicitly rather than asserting it "should" behave
better; fixing it is left to the refactor.

No real VLC binary and no real RTSP camera are used — `vlc` is fully faked
in conftest.py.
"""

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from recorder import SEGMENT_DURATION_S, EmergencyRecorder
from recording import RecordingStatus


RTSP_CFG = {
    "ip": "192.168.1.50",
    "port": 554,
    "username": "admin",
    "password": "s3cret",
    "stream_type": "sub",  # deliberately "sub" — start() must force "main"
    "channel": "ch1",
}


# ---------------------------------------------------------------------
# 1. Initial state
# ---------------------------------------------------------------------


def test_initial_state_not_recording():
    rec = EmergencyRecorder()
    assert rec.is_recording() is False
    assert rec.elapsed_seconds() == 0


# ---------------------------------------------------------------------
# 2. is_recording()
# ---------------------------------------------------------------------


def test_is_recording_true_after_start_false_after_stop(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    assert rec.is_recording() is False

    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    assert rec.is_recording() is True

    rec.stop()
    assert rec.is_recording() is False


# ---------------------------------------------------------------------
# 3. start() creates the expected recording target/path and transitions
#    to a recording state on success
# ---------------------------------------------------------------------


def test_start_creates_target_dir_and_transitions_to_recording(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    save_dir = tmp_path / "recordings"
    assert not save_dir.exists()

    started_paths = []
    rec.recording_started.connect(started_paths.append)

    rec.start(RTSP_CFG, save_dir=str(save_dir))

    assert save_dir.exists() and save_dir.is_dir()
    assert rec.is_recording() is True
    assert started_paths == [rec._filepath]
    # CHANGED (Task 3): segmented recording gives each session its own
    # save_dir/emergency_<session_id>/ subdirectory instead of writing the
    # file directly into save_dir — the segment's parent is now the
    # session directory, which itself lives inside save_dir.
    session_dir = Path(rec._filepath).parent
    assert session_dir.parent == save_dir
    assert session_dir.name == f"emergency_{rec._session.session_id}"


def test_start_falls_back_to_default_recording_dir_when_save_dir_blank(
    wired_vlc, monkeypatch, tmp_path
):
    fake_default = tmp_path / "DefaultVideos"
    monkeypatch.setattr("recorder.default_recording_dir", lambda: fake_default)

    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir="")

    assert fake_default.exists()
    # CHANGED (Task 3): same reasoning as
    # test_start_creates_target_dir_and_transitions_to_recording above —
    # the segment now lives one level deeper, inside the session
    # subdirectory, not directly inside the resolved base directory.
    session_dir = Path(rec._filepath).parent
    assert session_dir.parent == fake_default


def test_start_second_call_while_recording_is_ignored(tmp_path, wired_vlc):
    """is_recording() guard at the top of start() — calling start() again
    while already recording must not create a second recording/session."""
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    first_path = rec._filepath

    started_paths = []
    rec.recording_started.connect(started_paths.append)
    rec.start(RTSP_CFG, save_dir=str(tmp_path))  # ignored — already recording

    assert rec._filepath == first_path
    assert started_paths == []


# ---------------------------------------------------------------------
# 4. start() failure paths
# ---------------------------------------------------------------------


def test_start_mkdir_failure_stays_safe_and_emits_recording_error(
    tmp_path, wired_vlc, monkeypatch
):
    rec = EmergencyRecorder()

    def _boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", _boom)

    errors = []
    rec.recording_error.connect(errors.append)
    started = []
    rec.recording_started.connect(started.append)

    rec.start(RTSP_CFG, save_dir=str(tmp_path / "nope"))

    assert rec.is_recording() is False
    assert rec.instance is None
    assert rec.media_player is None
    assert len(errors) == 1
    assert "Không tạo được thư mục lưu ghi hình" in errors[0]
    assert started == []
    # mkdir failure short-circuits before any VLC setup is attempted
    from recorder import vlc as recorder_vlc

    recorder_vlc.Instance.assert_not_called()


def test_start_vlc_instance_creation_failure_propagates_uncaught(tmp_path, fake_vlc):
    """Documents CURRENT (not necessarily desired) behavior: unlike the
    mkdir failure above, a failure creating the VLC instance is NOT caught
    anywhere in start() — it propagates as a raw exception out of start().
    No recording_error is emitted for this path today. Recorder happens to
    remain in a technically safe not-recording state, but only because the
    exception occurs before self.instance/self.media_player are assigned —
    not because of explicit error handling."""
    fake_vlc.Instance.side_effect = RuntimeError("libvlc init failed")

    rec = EmergencyRecorder()
    errors = []
    rec.recording_error.connect(errors.append)

    with pytest.raises(RuntimeError, match="libvlc init failed"):
        rec.start(RTSP_CFG, save_dir=str(tmp_path))

    assert rec.is_recording() is False
    assert rec.instance is None
    assert rec.media_player is None
    assert errors == []


# ---------------------------------------------------------------------
# 5. stop() idempotent / safe when not recording
# ---------------------------------------------------------------------


def test_stop_is_noop_when_never_started():
    rec = EmergencyRecorder()
    stopped = []
    rec.recording_stopped.connect(stopped.append)

    rec.stop()  # must not raise

    assert rec.is_recording() is False
    assert stopped == []


def test_stop_called_twice_after_start_is_safe(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    stopped = []
    rec.recording_stopped.connect(stopped.append)

    rec.stop()
    rec.stop()  # second call: no-op — must not raise or double-emit

    assert len(stopped) == 1
    assert rec.is_recording() is False


# ---------------------------------------------------------------------
# 6. stop() cleans up the current VLC media player/instance
# ---------------------------------------------------------------------


def test_stop_releases_media_player_and_instance(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    expected_path = rec._filepath

    stopped_paths = []
    rec.recording_stopped.connect(stopped_paths.append)

    rec.stop()

    wired_vlc.media_player.stop.assert_called_once()
    wired_vlc.media_player.release.assert_called_once()
    wired_vlc.instance.release.assert_called_once()
    assert rec.media_player is None
    assert rec.instance is None
    assert rec._start_time is None
    assert not rec._watchdog.isActive()
    assert stopped_paths == [expected_path]


# ---------------------------------------------------------------------
# 7. MAIN stream is used, regardless of the configured stream_type
# ---------------------------------------------------------------------


def test_start_forces_main_stream_regardless_of_configured_stream_type(
    tmp_path, wired_vlc
):
    rec = EmergencyRecorder()
    rtsp_cfg = dict(RTSP_CFG, stream_type="sub")

    rec.start(rtsp_cfg, save_dir=str(tmp_path))

    (url_used,), _kwargs = wired_vlc.instance.media_new.call_args
    assert "/main/av_stream" in url_used
    assert "/sub/av_stream" not in url_used
    # the caller's config dict must not be mutated in place
    assert rtsp_cfg["stream_type"] == "sub"


# ---------------------------------------------------------------------
# 8. MKV output behavior preserved
# ---------------------------------------------------------------------


def test_start_uses_mkv_mux_sout_option(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    sout_calls = [
        call.args[0]
        for call in wired_vlc.media.add_option.call_args_list
        if call.args and call.args[0].startswith(":sout=")
    ]
    assert len(sout_calls) == 1
    assert "mux=mkv" in sout_calls[0]
    assert "access=file" in sout_calls[0]
    assert rec._filepath.endswith(".mkv")

    keep_calls = [
        call.args[0]
        for call in wired_vlc.media.add_option.call_args_list
        if call.args == (":sout-keep",)
    ]
    assert len(keep_calls) == 1


# ---------------------------------------------------------------------
# 9. Recording filename format preserved
# ---------------------------------------------------------------------


def test_recording_filename_format(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    # CHANGED (Task 3): the "emergency_" prefix + session id now live in
    # the SESSION DIRECTORY name (emergency_<session_id>/), matching the
    # task spec's example layout, so the per-segment filename itself is
    # just the sortable timestamp (e.g. 20260821_173000.mkv).
    segment_path = Path(rec._filepath)
    assert re.fullmatch(r"\d{8}_\d{6}(_\d{2})?\.mkv", segment_path.name), segment_path.name
    assert segment_path.parent.name == f"emergency_{rec._session.session_id}"


# ---------------------------------------------------------------------
# 10. recording_error signal behavior
# ---------------------------------------------------------------------


def test_check_state_emits_recording_error_and_cleans_up_on_vlc_error(
    tmp_path, wired_vlc, fake_vlc
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    expected_path = rec._filepath

    errors = []
    rec.recording_error.connect(errors.append)

    wired_vlc.media_player.get_state.return_value = fake_vlc.State.Error
    rec._check_state()  # invoked directly instead of waiting on the real 500ms QTimer

    assert len(errors) == 1
    assert expected_path in errors[0]
    assert rec.is_recording() is False
    assert not rec._watchdog.isActive()


def test_check_state_is_noop_when_not_recording():
    rec = EmergencyRecorder()
    rec._check_state()  # media_player is None — must not raise
    assert rec.is_recording() is False


# ---------------------------------------------------------------------
# 11. Architecture contract: EmergencyRecorder must not depend on
#     GlassWindow / any UI window lifecycle
# ---------------------------------------------------------------------


def test_recorder_module_does_not_import_glass_window_or_qtwidgets():
    """Static regression guard: EmergencyRecorder must remain usable from a
    future headless controller (tray-only mode, background service, etc.)
    without any GlassWindow existing. If a future change adds a
    glass_window/GlassWindow or QtWidgets dependency to recorder.py, this
    test fails immediately instead of the coupling being discovered later
    during the Player/Recorder refactor."""
    import ast

    recorder_path = Path(__file__).resolve().parent.parent / "src" / "recorder.py"
    tree = ast.parse(recorder_path.read_text(encoding="utf-8"))

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)

    assert not any(
        "glass_window" in name or "GlassWindow" in name for name in imported_names
    )
    assert not any(name.startswith("PySide6.QtWidgets") for name in imported_names)


def test_recorder_functions_fully_without_any_window_or_widget_created(
    tmp_path, wired_vlc
):
    """Functional companion to the static check above: run a full
    start()/stop() recording lifecycle in a process where glass_window was
    never imported and no QWidget of any kind was ever constructed —
    demonstrating EmergencyRecorder's lifecycle is independent of window
    visibility/lifecycle, matching the intended architecture (see audit:
    closeEvent() only stops the recorder on real app quit, never on
    hide/Alt+F4)."""
    assert "glass_window" not in sys.modules, (
        "glass_window must not need to be imported for the recorder to work"
    )

    rec = EmergencyRecorder(parent=None)
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    assert rec.is_recording() is True

    rec.stop()
    assert rec.is_recording() is False


# ---------------------------------------------------------------------
# 12. Task 3 — segmented emergency recording
# ---------------------------------------------------------------------


def test_segment_duration_defaults_to_300_seconds():
    assert SEGMENT_DURATION_S == 300


def test_segment_timer_interval_matches_segment_duration(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    assert rec._segment_timer.interval() == SEGMENT_DURATION_S * 1000


def test_start_creates_session_subdirectory(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    session_dir = tmp_path / f"emergency_{rec._session.session_id}"
    assert session_dir.exists() and session_dir.is_dir()
    assert Path(rec._filepath).parent == session_dir


def test_start_session_has_first_segment(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    assert len(rec._session.segments) == 1
    first_segment = rec._session.segments[0]
    assert first_segment.path == rec._filepath
    assert first_segment.completed is False
    assert rec._session.status == RecordingStatus.RECORDING


def test_segment_rotation_creates_second_segment_same_session(tmp_path, segment_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    first_path = rec._filepath
    session_id = rec._session.session_id

    rec._rotate_segment()

    assert rec.is_recording() is True
    assert rec._session.session_id == session_id
    assert len(rec._session.segments) == 2
    assert rec._filepath != first_path
    assert Path(rec._filepath).parent == Path(first_path).parent


def test_segment_rotation_finalizes_previous_segment_before_next_starts(
    tmp_path, segment_vlc
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    first_segment = rec._session.segments[0]
    assert first_segment.completed is False

    rec._rotate_segment()

    assert first_segment.completed is True
    assert first_segment.ended_at is not None
    # segment 0's player must be stopped/released (finalized) before
    # segment 1's VLC instance gets created
    segment_vlc[0].media_player.stop.assert_called_once()
    segment_vlc[0].media_player.release.assert_called_once()
    segment_vlc[0].instance.release.assert_called_once()
    assert len(segment_vlc) == 2
    assert rec._session.segments[1].completed is False


def test_only_one_rotation_timer_exists(tmp_path, segment_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    timer = rec._segment_timer
    assert timer.isActive()
    assert timer.isSingleShot()

    rec._rotate_segment()
    rec._rotate_segment()

    # same QTimer object reused for every rotation — never a second timer
    assert rec._segment_timer is timer
    assert timer.isActive()
    assert timer.isSingleShot()


def test_stop_stops_rotation_timer(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    assert rec._segment_timer.isActive()

    rec.stop()

    assert not rec._segment_timer.isActive()


def test_stop_finalizes_session(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    session = rec._session

    rec.stop()

    assert session.status == RecordingStatus.STOPPED
    assert session.ended_at is not None
    assert session.segments[-1].completed is True


def test_stop_does_not_create_another_segment(tmp_path, segment_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    rec.stop()

    assert len(rec._session.segments) == 1
    assert len(segment_vlc) == 1


def test_starting_recorder_twice_does_not_create_multiple_sessions(
    tmp_path, wired_vlc
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    session = rec._session

    rec.start(RTSP_CFG, save_dir=str(tmp_path))  # ignored — already recording

    assert rec._session is session
    assert len(session.segments) == 1


def test_failure_starting_next_segment_transitions_failed_and_emits_error(
    tmp_path, fake_vlc
):
    good_instance = MagicMock(name="vlc_instance_ok")
    good_media_player = MagicMock(name="media_player_ok")
    good_media = MagicMock(name="media_ok")
    good_instance.media_player_new.return_value = good_media_player
    good_instance.media_new.return_value = good_media
    good_media_player.get_state.return_value = fake_vlc.State.Playing

    fake_vlc.Instance.side_effect = [
        good_instance,
        RuntimeError("libvlc init failed for next segment"),
    ]

    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))

    errors = []
    rec.recording_error.connect(errors.append)

    rec._rotate_segment()  # second segment fails to start

    assert rec.is_recording() is False
    assert rec.instance is None
    assert rec.media_player is None
    assert len(errors) == 1
    assert rec._session.status == RecordingStatus.FAILED
    assert not rec._segment_timer.isActive()
    assert not rec._watchdog.isActive()
    # the first segment's player was released before the failed attempt
    # to start the second one
    good_media_player.stop.assert_called_once()
    good_media_player.release.assert_called_once()


# ---------------------------------------------------------------------
# 13. Task 3 fix — finalize-after-stop ordering, _start_segment() leak safety
# ---------------------------------------------------------------------


def test_rotation_stops_and_releases_old_player_before_finalizing_segment(
    tmp_path, segment_vlc, monkeypatch
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    first_segment = rec._session.segments[0]

    call_order = []
    segment_vlc[0].media_player.stop.side_effect = lambda: call_order.append(
        "player_stop"
    )
    segment_vlc[0].media_player.release.side_effect = lambda: call_order.append(
        "player_release"
    )
    segment_vlc[0].instance.release.side_effect = lambda: call_order.append(
        "instance_release"
    )
    original_mark_completed = first_segment.mark_completed

    def _tracked_mark_completed(*args, **kwargs):
        call_order.append("mark_completed")
        return original_mark_completed(*args, **kwargs)

    monkeypatch.setattr(first_segment, "mark_completed", _tracked_mark_completed)

    rec._rotate_segment()

    assert call_order == [
        "player_stop",
        "player_release",
        "instance_release",
        "mark_completed",
    ]
    assert first_segment.completed is True


def test_stop_stops_and_releases_player_before_finalizing_segment(
    tmp_path, wired_vlc, monkeypatch
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    segment = rec._session.segments[0]

    call_order = []
    wired_vlc.media_player.stop.side_effect = lambda: call_order.append(
        "player_stop"
    )
    wired_vlc.media_player.release.side_effect = lambda: call_order.append(
        "player_release"
    )
    wired_vlc.instance.release.side_effect = lambda: call_order.append(
        "instance_release"
    )
    original_mark_completed = segment.mark_completed

    def _tracked_mark_completed(*args, **kwargs):
        call_order.append("mark_completed")
        return original_mark_completed(*args, **kwargs)

    monkeypatch.setattr(segment, "mark_completed", _tracked_mark_completed)

    rec.stop()

    assert call_order == [
        "player_stop",
        "player_release",
        "instance_release",
        "mark_completed",
    ]
    assert segment.completed is True


def test_check_state_error_stops_and_releases_player_before_finalizing_segment(
    tmp_path, wired_vlc, monkeypatch
):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir=str(tmp_path))
    segment = rec._session.segments[0]
    wired_vlc.media_player.get_state.return_value = "Error"  # == fake vlc.State.Error

    call_order = []
    wired_vlc.media_player.stop.side_effect = lambda: call_order.append(
        "player_stop"
    )
    wired_vlc.media_player.release.side_effect = lambda: call_order.append(
        "player_release"
    )
    wired_vlc.instance.release.side_effect = lambda: call_order.append(
        "instance_release"
    )
    original_mark_completed = segment.mark_completed

    def _tracked_mark_completed(*args, **kwargs):
        call_order.append("mark_completed")
        return original_mark_completed(*args, **kwargs)

    monkeypatch.setattr(segment, "mark_completed", _tracked_mark_completed)

    rec._check_state()

    assert call_order == [
        "player_stop",
        "player_release",
        "instance_release",
        "mark_completed",
    ]
    assert segment.completed is True
    assert rec._session.status == RecordingStatus.FAILED


def test_start_segment_cleans_up_local_resources_on_setup_failure(tmp_path, fake_vlc):
    instance_mock = MagicMock(name="vlc_instance")
    media_player_mock = MagicMock(name="media_player")
    media_mock = MagicMock(name="media")
    instance_mock.media_player_new.return_value = media_player_mock
    instance_mock.media_new.return_value = media_mock
    media_player_mock.play.side_effect = RuntimeError("play failed")
    fake_vlc.Instance.return_value = instance_mock

    rec = EmergencyRecorder()

    with pytest.raises(RuntimeError):
        rec.start(RTSP_CFG, save_dir=str(tmp_path))

    # The locally-created media player/instance must be cleaned up before
    # the exception propagates (Task 1 characterization: start() still
    # lets the exception itself escape uncaught for the first segment).
    media_player_mock.stop.assert_called_once()
    media_player_mock.release.assert_called_once()
    instance_mock.release.assert_called_once()
    assert rec.instance is None
    assert rec.media_player is None
    assert rec.is_recording() is False


def test_start_segment_cleans_up_instance_when_media_player_new_fails(
    tmp_path, fake_vlc
):
    instance_mock = MagicMock(name="vlc_instance")
    instance_mock.media_player_new.side_effect = RuntimeError("player_new failed")
    fake_vlc.Instance.return_value = instance_mock

    rec = EmergencyRecorder()

    with pytest.raises(RuntimeError):
        rec.start(RTSP_CFG, save_dir=str(tmp_path))

    # media_player was never created, so only the instance needs releasing.
    instance_mock.release.assert_called_once()
    assert rec.instance is None
    assert rec.media_player is None
    assert rec.is_recording() is False
