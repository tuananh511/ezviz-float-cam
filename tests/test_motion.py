"""tests/test_motion.py — motion.py (thuần stdlib, không cần Qt/VLC)."""

import pytest

from motion import (
    ACTION_START,
    ACTION_STOP,
    DEFAULT_MOTION_CONFIG,
    POST_ROLL_MAX_S,
    POST_ROLL_MIN_S,
    MotionDetector,
    MotionRecordingPolicy,
    get_motion_config,
)

W, H = 96, 54


def flat(value: int) -> bytes:
    return bytes([value]) * (W * H)


def with_block(base: int, value: int, x0: int, y0: int, x1: int, y1: int) -> bytes:
    rows = []
    for y in range(H):
        row = bytearray([base]) * W
        if y0 <= y < y1:
            for x in range(x0, x1):
                row[x] = value
        rows.append(bytes(row))
    return b"".join(rows)


def warmed(**kwargs) -> MotionDetector:
    det = MotionDetector(**kwargs)
    for _ in range(det.warmup_frames + 1):
        det.process(flat(100), W, H)
    return det


# ---------------- config ----------------


def test_config_defaults_when_missing():
    assert get_motion_config({}) == DEFAULT_MOTION_CONFIG
    assert get_motion_config(None) == DEFAULT_MOTION_CONFIG


def test_config_does_not_mutate_input():
    cfg = {"motion": {"enabled": False}}
    get_motion_config(cfg)
    assert cfg == {"motion": {"enabled": False}}


def test_config_sanitizes_bad_values():
    cfg = get_motion_config({"motion": {
        "enabled": 0, "sensitivity": "ultra", "post_roll_s": "abc",
        "stream_type": "hd", "roi": [0.9, 0.1, 0.2, 0.5],
    }})
    assert cfg["enabled"] is False
    assert cfg["sensitivity"] == "medium"
    assert cfg["post_roll_s"] == DEFAULT_MOTION_CONFIG["post_roll_s"]
    assert cfg["stream_type"] == "main"
    assert cfg["roi"] is None


def test_config_clamps_post_roll():
    assert get_motion_config({"motion": {"post_roll_s": 1}})["post_roll_s"] == POST_ROLL_MIN_S
    assert get_motion_config({"motion": {"post_roll_s": 99999}})["post_roll_s"] == POST_ROLL_MAX_S


def test_config_accepts_valid_roi():
    cfg = get_motion_config({"motion": {"roi": [0.1, 0.2, 0.6, 0.9]}})
    assert cfg["roi"] == [0.1, 0.2, 0.6, 0.9]


# ---------------- detector ----------------


def test_static_scene_no_motion():
    det = warmed()
    for _ in range(10):
        assert det.process(flat(100), W, H).motion is False


def test_first_frames_are_warmup_and_never_motion():
    det = MotionDetector()
    res = det.process(with_block(100, 255, 0, 0, 40, 40), W, H)
    assert res.warming_up and not res.motion


def test_moving_block_triggers_motion():
    det = warmed()
    res = det.process(with_block(100, 255, 10, 10, 40, 40), W, H)
    assert res.motion is True
    assert res.changed_ratio > 0.1


def test_tiny_change_below_ratio_is_ignored():
    det = warmed()
    res = det.process(with_block(100, 255, 0, 0, 2, 2), W, H)  # 4 px
    assert res.motion is False


def test_small_brightness_change_below_pixel_threshold_is_ignored():
    det = warmed()
    assert det.process(flat(110), W, H).motion is False


def test_global_brightness_jump_is_scene_change_not_motion():
    det = warmed()
    res = det.process(flat(220), W, H)
    assert res.scene_change is True
    assert res.motion is False


def test_background_rebases_after_scene_change():
    det = warmed()
    det.process(flat(220), W, H)
    for _ in range(det.warmup_frames + 2):
        res = det.process(flat(220), W, H)
    assert res.motion is False
    # và chuyển động thật vẫn bị phát hiện trên nền mới
    assert det.process(with_block(220, 20, 10, 10, 40, 40), W, H).motion is True


def test_roi_ignores_motion_outside_region():
    det = warmed(roi=[0.5, 0.0, 1.0, 1.0])  # chỉ nửa phải
    assert det.process(with_block(100, 255, 0, 0, 40, 54), W, H).motion is False
    det2 = warmed(roi=[0.5, 0.0, 1.0, 1.0])
    assert det2.process(with_block(100, 255, 60, 0, 90, 54), W, H).motion is True


def test_person_filling_small_roi_is_motion_not_scene_change():
    det = warmed(roi=[0.5, 0.0, 1.0, 1.0])
    res = det.process(with_block(100, 255, 50, 0, 90, 54), W, H)  # ~83% của ROI, ~42% khung
    assert res.scene_change is False
    assert res.motion is True


def test_size_change_resets_background():
    det = warmed()
    res = det.process(bytes([100]) * (48 * 27), 48, 27)
    assert res.warming_up and not res.motion


def test_bad_buffer_length_raises():
    with pytest.raises(ValueError):
        MotionDetector().process(b"\x00" * 10, W, H)


def test_sensitivity_high_catches_what_low_misses():
    frame = with_block(100, 150, 0, 0, 30, 30)  # chênh 50, ~31% điểm ảnh -> cả hai thấy
    small = with_block(100, 125, 0, 0, 20, 20)  # chênh 25: chỉ "high" (ngưỡng 18) thấy
    low = MotionDetector.from_config(get_motion_config({"motion": {"sensitivity": "low"}}))
    high = MotionDetector.from_config(get_motion_config({"motion": {"sensitivity": "high"}}))
    for d in (low, high):
        for _ in range(d.warmup_frames + 1):
            d.process(flat(100), W, H)
    assert low.process(small, W, H).motion is False
    assert high.process(small, W, H).motion is True
    assert low.process(frame, W, H).motion is True


# ---------------- policy ----------------


def test_policy_needs_consecutive_samples_to_start():
    p = MotionRecordingPolicy(post_roll_s=10, trigger_samples=2)
    assert p.update(True, 0) is None
    assert p.update(False, 1) is None      # đứt chuỗi -> đếm lại
    assert p.update(True, 2) is None
    assert p.update(True, 3) == ACTION_START
    assert p.recording


def test_policy_stops_after_post_roll():
    p = MotionRecordingPolicy(post_roll_s=10, trigger_samples=1)
    assert p.update(True, 0) == ACTION_START
    assert p.update(False, 9.9) is None
    assert p.update(False, 10.0) == ACTION_STOP
    assert not p.recording


def test_policy_motion_extends_recording():
    p = MotionRecordingPolicy(post_roll_s=10, trigger_samples=1)
    p.update(True, 0)
    p.update(True, 8)
    assert p.update(False, 17.9) is None   # 17.9 - 8 < 10
    assert p.update(False, 18.0) == ACTION_STOP


def test_policy_can_restart_after_stop():
    p = MotionRecordingPolicy(post_roll_s=5, trigger_samples=1)
    p.update(True, 0)
    p.update(False, 5)
    assert p.update(True, 6) == ACTION_START


def test_policy_notify_stopped_resets():
    p = MotionRecordingPolicy(post_roll_s=5, trigger_samples=1)
    p.update(True, 0)
    p.notify_stopped()
    assert not p.recording
    assert p.update(False, 1) is None
