"""tests/test_motion_controller.py — MotionRecordingController (stream/recorder giả)."""

import pytest
from PySide6.QtGui import QColor, QImage, QPainter

from motion_controller import (
    ERROR_BACKOFF_S,
    MotionRecordingController,
    frame_to_gray_bytes,
)
from motion import DETECT_HEIGHT, DETECT_WIDTH

W, H = 192, 108


def make_frame(gray: int, block=None) -> QImage:
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(QColor(gray, gray, gray))
    if block:
        p = QPainter(img)
        p.fillRect(*block, QColor(255, 255, 255))
        p.end()
    return img


class FakeStream:
    def __init__(self):
        self.frame = make_frame(100)

    def latest_frame(self):
        return self.frame


class FakeRecorder:
    def __init__(self):
        self.stream_type = "main"
        self._recording = False
        self.start_calls = []
        self.stop_calls = 0
        self.fail_start = False

    def is_recording(self):
        return self._recording

    def elapsed_seconds(self):
        return 3

    def start(self, rtsp_cfg, save_dir=""):
        self.start_calls.append((dict(rtsp_cfg), save_dir))
        if self.fail_start:
            return  # mô phỏng đầy đĩa: start() trả về mà không ghi
        self._recording = True

    def stop(self):
        self.stop_calls += 1
        self._recording = False


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


CONFIG = {
    "rtsp": {"ip": "1.2.3.4", "port": 554, "username": "admin", "password": "x",
             "stream_type": "sub", "channel": "ch1"},
    "recording": {"save_dir": "D:/rec"},
    "motion": {"enabled": True, "sensitivity": "medium", "post_roll_s": 10},
}

MOTION_BLOCK = (20, 10, 90, 80)  # vùng lớn, chắc chắn vượt ngưỡng


def make_controller(config=None):
    stream, rec, clock = FakeStream(), FakeRecorder(), Clock()
    cfg = config if config is not None else {k: (dict(v) if isinstance(v, dict) else v) for k, v in CONFIG.items()}
    ctrl = MotionRecordingController(stream, rec, lambda: cfg, clock=clock)
    return ctrl, stream, rec, clock, cfg


def settle(ctrl, clock, n=6):
    """Cho detector qua giai đoạn khởi động trên cảnh tĩnh."""
    for _ in range(n):
        ctrl._tick()
        clock.advance(0.5)


def test_frame_to_gray_bytes_size():
    gray = frame_to_gray_bytes(make_frame(128))
    assert len(gray) == DETECT_WIDTH * DETECT_HEIGHT
    assert abs(gray[0] - 128) <= 2


def test_static_scene_never_starts_recording():
    ctrl, stream, rec, clock, _ = make_controller()
    settle(ctrl, clock, 20)
    assert rec.start_calls == []


def test_motion_starts_auto_recording_with_configured_dirs():
    ctrl, stream, rec, clock, _ = make_controller()
    settle(ctrl, clock)
    stream.frame = make_frame(100, MOTION_BLOCK)
    for _ in range(3):
        ctrl._tick()
        clock.advance(0.5)
    assert rec.is_recording()
    assert len(rec.start_calls) == 1
    assert rec.start_calls[0][1] == "D:/rec"


def test_recording_stops_after_post_roll_when_motion_ends():
    ctrl, stream, rec, clock, _ = make_controller()
    settle(ctrl, clock)
    stream.frame = make_frame(100, MOTION_BLOCK)
    for _ in range(3):
        ctrl._tick()
        clock.advance(0.5)
    assert rec.is_recording()

    stream.frame = make_frame(100)  # hết chuyển động
    for _ in range(40):             # 20 giây > post_roll 10s
        ctrl._tick()
        clock.advance(0.5)
    assert rec.is_recording() is False
    assert rec.stop_calls == 1


def test_no_frame_counts_as_no_motion():
    ctrl, stream, rec, clock, _ = make_controller()
    stream.frame = None
    for _ in range(10):
        ctrl._tick()
        clock.advance(0.5)
    assert rec.start_calls == []


def test_disabled_does_nothing():
    cfg = {**CONFIG, "motion": {"enabled": False}}
    ctrl, stream, rec, clock, _ = make_controller(cfg)
    settle(ctrl, clock)
    stream.frame = make_frame(100, MOTION_BLOCK)
    for _ in range(5):
        ctrl._tick()
        clock.advance(0.5)
    assert rec.start_calls == []


def test_disabling_via_config_stops_running_auto_recording():
    ctrl, stream, rec, clock, cfg = make_controller()
    settle(ctrl, clock)
    stream.frame = make_frame(100, MOTION_BLOCK)
    for _ in range(3):
        ctrl._tick()
        clock.advance(0.5)
    assert rec.is_recording()
    cfg["motion"]["enabled"] = False
    ctrl.apply_config()
    assert rec.is_recording() is False


def test_failed_start_backs_off_instead_of_retrying_every_tick():
    ctrl, stream, rec, clock, _ = make_controller()
    rec.fail_start = True
    settle(ctrl, clock)
    stream.frame = make_frame(100, MOTION_BLOCK)
    for _ in range(10):
        ctrl._tick()
        clock.advance(0.5)
    assert len(rec.start_calls) == 1
    assert ctrl.last_error is not None
    # sau thời gian nghỉ thì được thử lại
    clock.advance(ERROR_BACKOFF_S)
    stream.frame = make_frame(100)
    for _ in range(4):
        ctrl._tick()
        clock.advance(0.5)
    stream.frame = make_frame(100, MOTION_BLOCK)
    for _ in range(4):
        ctrl._tick()
        clock.advance(0.5)
    assert len(rec.start_calls) >= 2


def test_recorder_dying_mid_session_is_detected_and_suspended():
    ctrl, stream, rec, clock, _ = make_controller()
    settle(ctrl, clock)
    stream.frame = make_frame(100, MOTION_BLOCK)
    for _ in range(3):
        ctrl._tick()
        clock.advance(0.5)
    assert rec.is_recording()
    rec._recording = False  # recorder tự dừng vì lỗi (đầy đĩa/mất luồng)
    ctrl._tick()
    assert ctrl.last_error is not None
    calls = len(rec.start_calls)
    for _ in range(10):     # đang nghỉ -> không bật lại ngay
        ctrl._tick()
        clock.advance(0.5)
    assert len(rec.start_calls) == calls


def test_apply_config_propagates_stream_type_to_recorder():
    ctrl, stream, rec, clock, cfg = make_controller()
    cfg["motion"]["stream_type"] = "sub"
    ctrl.apply_config()
    assert rec.stream_type == "sub"


def test_shutdown_stops_running_recording():
    ctrl, stream, rec, clock, _ = make_controller()
    settle(ctrl, clock)
    stream.frame = make_frame(100, MOTION_BLOCK)
    for _ in range(3):
        ctrl._tick()
        clock.advance(0.5)
    ctrl.shutdown()
    assert rec.is_recording() is False
