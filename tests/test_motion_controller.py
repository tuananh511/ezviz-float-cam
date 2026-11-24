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
    """Khung xám phẳng; nếu có `block` (x, y, w, h) thì vẽ vào đó các vạch trắng
    (vật CÓ cấu trúc, như người) — một mảng trắng đồng nhất sẽ bị coi là vệt
    sáng và bị bỏ qua (bù sáng cục bộ)."""
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(QColor(gray, gray, gray))
    if block:
        x0, y0, bw, bh = block
        p = QPainter(img)
        for x in range(x0, x0 + bw, 8):
            p.fillRect(x, y0, 4, bh, QColor(255, 255, 255))
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

    def write_preroll_clip(self, data):
        self.preroll_written = getattr(self, "preroll_written", []) + [data]
        return True


class FakePreRoll:
    def __init__(self, clip=b"CLIP"):
        self.clip = clip
        self.configured = []
        self.snapshots = []
        self.shut = False

    def configure(self, rtsp_cfg, pre_roll_s):
        self.configured.append((rtsp_cfg, pre_roll_s))

    def snapshot(self, pre_roll_s):
        self.snapshots.append(pre_roll_s)
        return self.clip

    def shutdown(self):
        self.shut = True


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

MOTION_BLOCK = (20, 10, 90, 80)  # vùng lớn có vạch, chắc chắn vượt ngưỡng
MOTION_TICKS = 8                 # 4 s chuyển động: đủ lâu hơn min_duration_s mặc định (2 s)


def push_motion(ctrl, clock, stream, ticks=MOTION_TICKS):
    stream.frame = make_frame(100, MOTION_BLOCK)
    for _ in range(ticks):
        ctrl._tick()
        clock.advance(0.5)


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
    push_motion(ctrl, clock, stream)
    assert rec.is_recording()
    assert len(rec.start_calls) == 1
    assert rec.start_calls[0][1] == "D:/rec"


def test_recording_stops_after_post_roll_when_motion_ends():
    ctrl, stream, rec, clock, _ = make_controller()
    settle(ctrl, clock)
    push_motion(ctrl, clock, stream)
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
    push_motion(ctrl, clock, stream)
    assert rec.start_calls == []


def test_disabling_via_config_stops_running_auto_recording():
    ctrl, stream, rec, clock, cfg = make_controller()
    settle(ctrl, clock)
    push_motion(ctrl, clock, stream)
    assert rec.is_recording()
    cfg["motion"]["enabled"] = False
    ctrl.apply_config()
    assert rec.is_recording() is False


def test_failed_start_backs_off_instead_of_retrying_every_tick():
    ctrl, stream, rec, clock, _ = make_controller()
    rec.fail_start = True
    settle(ctrl, clock)
    push_motion(ctrl, clock, stream, ticks=12)
    assert len(rec.start_calls) == 1
    assert ctrl.last_error is not None
    # sau thời gian nghỉ thì được thử lại
    clock.advance(ERROR_BACKOFF_S)
    stream.frame = make_frame(100)
    for _ in range(4):
        ctrl._tick()
        clock.advance(0.5)
    push_motion(ctrl, clock, stream)
    assert len(rec.start_calls) >= 2


def test_recorder_dying_mid_session_is_detected_and_suspended():
    ctrl, stream, rec, clock, _ = make_controller()
    settle(ctrl, clock)
    push_motion(ctrl, clock, stream)
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
    push_motion(ctrl, clock, stream)
    ctrl.shutdown()
    assert rec.is_recording() is False


# ---------------- chuyển động ngắn / ánh sáng / camera xoay ----------------


def test_brief_motion_shorter_than_min_duration_does_not_record():
    ctrl, stream, rec, clock, _ = make_controller()
    settle(ctrl, clock)
    push_motion(ctrl, clock, stream, ticks=2)        # ~1 giây (< 2 giây mặc định)
    stream.frame = make_frame(100)
    for _ in range(10):
        ctrl._tick()
        clock.advance(0.5)
    assert rec.start_calls == []


def test_min_duration_is_configurable():
    cfg = {**CONFIG, "motion": {"enabled": True, "post_roll_s": 10, "min_duration_s": 0.5}}
    ctrl, stream, rec, clock, _ = make_controller(cfg)
    settle(ctrl, clock)
    push_motion(ctrl, clock, stream, ticks=2)
    assert rec.is_recording()


def test_smooth_light_change_does_not_record():
    ctrl, stream, rec, clock, _ = make_controller()
    settle(ctrl, clock)
    # đèn cửa: sáng dần từ trái sang phải
    img = QImage(W, H, QImage.Format_RGB32)
    for x in range(W):
        v = 100 + round(45 * x / (W - 1))
        for y in range(H):
            img.setPixelColor(x, y, QColor(v, v, v))
    stream.frame = img
    for _ in range(16):
        ctrl._tick()
        clock.advance(0.5)
    assert rec.start_calls == []


def test_camera_panning_does_not_start_recording():
    ctrl, stream, rec, clock, _ = make_controller()
    # cảnh rộng có hoa văn; camera lia ngang qua nó
    state, world = 11, []
    for _ in range(H):
        row = []
        for _ in range(W * 3):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            row.append(60 + (state >> 16) % 140)
        world.append(row)

    def view(offset):
        img = QImage(W, H, QImage.Format_RGB32)
        for y in range(H):
            for x in range(W):
                v = world[y][offset + x]
                img.setPixelColor(x, y, QColor(v, v, v))
        return img

    stream.frame = view(0)
    settle(ctrl, clock)
    for k in range(1, 40):                      # ~20 giây camera xoay
        stream.frame = view(min(6 * k, W * 2 - 1))
        ctrl._tick()
        clock.advance(0.5)
    assert rec.start_calls == []


# ---------------- pre-roll ----------------


def make_with_preroll(config=None, clip=b"CLIP"):
    cfg = config if config is not None else {k: (dict(v) if isinstance(v, dict) else v) for k, v in CONFIG.items()}
    cfg["motion"] = {**cfg["motion"], "pre_roll_s": 6}
    stream, rec, clock, pre = FakeStream(), FakeRecorder(), Clock(), FakePreRoll(clip)
    ctrl = MotionRecordingController(stream, rec, lambda: cfg, clock=clock, preroll=pre)
    return ctrl, stream, rec, clock, pre, cfg


def test_preroll_clip_is_taken_at_trigger_and_written_after_start():
    ctrl, stream, rec, clock, pre, _ = make_with_preroll()
    settle(ctrl, clock)
    push_motion(ctrl, clock, stream)
    assert rec.is_recording()
    assert pre.snapshots == [6]
    assert rec.preroll_written == [b"CLIP"]


def test_preroll_not_requested_when_disabled():
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in CONFIG.items()}
    stream, rec, clock, pre = FakeStream(), FakeRecorder(), Clock(), FakePreRoll()
    ctrl = MotionRecordingController(stream, rec, lambda: cfg, clock=clock, preroll=pre)
    settle(ctrl, clock)
    push_motion(ctrl, clock, stream)
    assert rec.is_recording()
    assert pre.snapshots == [] and not hasattr(rec, "preroll_written")


def test_empty_preroll_clip_is_not_written():
    ctrl, stream, rec, clock, pre, _ = make_with_preroll(clip=b"")
    settle(ctrl, clock)
    push_motion(ctrl, clock, stream)
    assert rec.is_recording()
    assert not hasattr(rec, "preroll_written")


def test_start_configures_preroll_buffer_from_config():
    ctrl, stream, rec, clock, pre, cfg = make_with_preroll()
    ctrl.start()
    assert pre.configured[-1] == (cfg["rtsp"], 6)
    ctrl.shutdown()


def test_disabling_motion_turns_preroll_buffer_off():
    ctrl, stream, rec, clock, pre, cfg = make_with_preroll()
    ctrl.start()
    cfg["motion"]["enabled"] = False
    ctrl.apply_config()
    assert pre.configured[-1] == (None, 0)
    ctrl.shutdown()


def test_preroll_zero_seconds_turns_buffer_off():
    ctrl, stream, rec, clock, pre, cfg = make_with_preroll()
    cfg["motion"]["pre_roll_s"] = 0
    ctrl.apply_config()
    assert pre.configured[-1] == (None, 0)


def test_shutdown_shuts_the_preroll_buffer_down():
    ctrl, stream, rec, clock, pre, cfg = make_with_preroll()
    ctrl.shutdown()
    assert pre.shut is True
