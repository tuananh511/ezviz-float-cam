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

import pytest

from recorder import EmergencyRecorder


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
    assert Path(rec._filepath).parent == save_dir


def test_start_falls_back_to_default_recording_dir_when_save_dir_blank(
    wired_vlc, monkeypatch, tmp_path
):
    fake_default = tmp_path / "DefaultVideos"
    monkeypatch.setattr("recorder.default_recording_dir", lambda: fake_default)

    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, save_dir="")

    assert fake_default.exists()
    assert Path(rec._filepath).parent == fake_default


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

    filename = Path(rec._filepath).name
    assert re.fullmatch(r"emergency_\d{8}_\d{6}\.mkv", filename), filename


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
