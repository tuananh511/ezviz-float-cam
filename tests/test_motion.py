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


def test_config_new_keys_have_defaults():
    cfg = get_motion_config({})
    assert cfg["min_duration_s"] == 2.0
    assert cfg["ignore_light_changes"] is True
    assert cfg["camera_settle_s"] == 10
    assert cfg["pre_roll_s"] == 0


def test_config_clamps_new_keys():
    cfg = get_motion_config({"motion": {"min_duration_s": 0, "camera_settle_s": 9999,
                                        "pre_roll_s": 500}})
    assert cfg["min_duration_s"] == 0.5
    assert cfg["camera_settle_s"] == 120
    assert cfg["pre_roll_s"] == 30
    bad = get_motion_config({"motion": {"min_duration_s": "x", "pre_roll_s": None,
                                        "ignore_light_changes": 0}})
    assert bad["min_duration_s"] == 2.0 and bad["pre_roll_s"] == 0
    assert bad["ignore_light_changes"] is False


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


def striped(base: int, value: int, x0: int, y0: int, x1: int, y1: int) -> bytes:
    """Vùng có cấu trúc (cột sáng/tối xen kẽ) — kiểu thay đổi mà bù sáng cục bộ
    KHÔNG loại bỏ (khác với một vệt sáng đều)."""
    rows = []
    for y in range(H):
        row = bytearray([base]) * W
        if y0 <= y < y1:
            for x in range(x0, x1):
                if x % 2 == 0:
                    row[x] = value
        rows.append(bytes(row))
    return b"".join(rows)


def test_sensitivity_high_catches_what_low_misses():
    weak = striped(100, 150, 0, 0, 20, 20)      # lệch 50, trừ độ lệch ô còn ~25: chỉ "high" (ngưỡng 18) thấy
    strong = striped(100, 255, 0, 0, 30, 30)    # lệch rất lớn: cả "low" cũng thấy
    low = MotionDetector.from_config(get_motion_config({"motion": {"sensitivity": "low"}}))
    high = MotionDetector.from_config(get_motion_config({"motion": {"sensitivity": "high"}}))
    for d in (low, high):
        for _ in range(d.warmup_frames + 1):
            d.process(flat(100), W, H)
    assert low.process(weak, W, H).motion is False
    assert high.process(weak, W, H).motion is True
    assert low.process(strong, W, H).motion is True


# ---------------- ánh sáng (đèn cửa, đèn pha) ----------------


def light_ramp(base: int, amplitude: int) -> bytes:
    """Vệt sáng mượt: sáng dần từ trái sang phải (0 .. amplitude), như đèn rọi vào tường."""
    row = bytes(min(255, base + round(amplitude * x / (W - 1))) for x in range(W))
    return row * H


def test_smooth_light_change_is_ignored_with_light_compensation():
    det = warmed()
    assert det.process(light_ramp(100, 45), W, H).motion is False


def test_same_light_change_triggers_when_compensation_is_off():
    det = warmed(light_compensation=False)
    assert det.process(light_ramp(100, 45), W, H).motion is True


def test_block_aligned_uniform_brightening_is_ignored():
    det = warmed()
    res = det.process(with_block(100, 190, 8, 6, 48, 36), W, H)  # trùng đúng lưới ô 8x6
    assert res.motion is False


def test_structured_change_is_still_detected_with_light_compensation():
    det = warmed()
    assert det.process(striped(100, 255, 10, 10, 50, 40), W, H).motion is True


def test_light_compensation_config_flag_reaches_detector():
    off = MotionDetector.from_config(get_motion_config({"motion": {"ignore_light_changes": False}}))
    on = MotionDetector.from_config(get_motion_config({}))
    assert off.light_compensation is False and on.light_compensation is True


# ---------------- camera tự xoay ----------------


def textured_world(seed: int = 7, width: int = 400) -> list[list[int]]:
    """Cảnh rộng có hoa văn ngẫu nhiên (xác định), để mô phỏng camera lia ngang."""
    state = seed
    rows = []
    for _ in range(H):
        row = []
        for _ in range(width):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            row.append(60 + (state >> 16) % 140)
        rows.append(row)
    return rows


def view(world, offset: int) -> bytes:
    return b"".join(bytes(row[offset:offset + W]) for row in world)


def settled_detector(**kw):
    det = MotionDetector(settle_frames=kw.pop("settle_frames", 6), **kw)
    world = textured_world()
    for _ in range(det.warmup_frames + 2):
        det.process(view(world, 0), W, H)
    return det, world


def test_camera_panning_is_not_motion():
    det, world = settled_detector()
    results = [det.process(view(world, 3 * k), W, H) for k in range(1, 12)]
    assert not any(r.motion for r in results)
    assert any(r.scene_change for r in results)


def test_motion_is_suppressed_while_camera_settles_then_resumes():
    det, world = settled_detector(settle_frames=4)
    for k in range(1, 6):
        det.process(view(world, 3 * k), W, H)          # camera xoay
    still = view(world, 15)
    during = [det.process(still, W, H) for _ in range(4)]
    assert not any(r.motion for r in during)
    # sau khi ổn định, một chuyển động thật lại được phát hiện
    for _ in range(3):
        det.process(still, W, H)
    moving = bytearray(still)
    for y in range(10, 40):
        for x in range(20, 50):
            moving[y * W + x] = 255 - moving[y * W + x]
    assert det.process(bytes(moving), W, H).motion is True


def test_small_moving_object_is_not_mistaken_for_camera_movement():
    det = warmed()
    results = []
    for k in range(6):
        results.append(det.process(with_block(100, 255, 5 + 3 * k, 10, 35 + 3 * k, 40), W, H))
    assert not any(r.scene_change for r in results)
    assert any(r.motion for r in results)


def test_camera_move_ratio_also_catches_slow_continuous_change():
    det, world = settled_detector(settle_frames=0)
    flagged = [det.process(view(world, 2 * k), W, H).scene_change for k in range(1, 8)]
    assert any(flagged)


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


def test_policy_window_tolerates_a_gap_between_motion_samples():
    p = MotionRecordingPolicy(post_roll_s=10, trigger_samples=3, window=5)
    assert p.update(True, 0) is None
    assert p.update(False, 1) is None      # người đứng lại một nhịp
    assert p.update(True, 2) is None
    assert p.update(True, 3) == ACTION_START


def test_policy_window_forgets_old_samples():
    p = MotionRecordingPolicy(post_roll_s=10, trigger_samples=3, window=4)
    for t, m in enumerate([True, False, False, False, False, True, True]):
        assert p.update(m, t) is None      # chỉ 2 mẫu "có" trong cửa sổ 4 gần nhất
    assert p.update(True, 7) == ACTION_START


def test_policy_brief_flash_shorter_than_min_duration_is_ignored():
    p = MotionRecordingPolicy(post_roll_s=10, trigger_samples=4, window=6)
    seq = [False, True, True, False, False, False, False]   # vệt sáng ~1 giây
    assert all(p.update(m, t) is None for t, m in enumerate(seq))


def test_policy_configure_keeps_recording_state():
    p = MotionRecordingPolicy(post_roll_s=10, trigger_samples=1)
    p.update(True, 0)
    p.configure(post_roll_s=30, trigger_samples=4, window=6)
    assert p.recording is True
    assert p.update(False, 29.9) is None
    assert p.update(False, 30.0) == ACTION_STOP
