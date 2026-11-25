"""
motion_controller.py — Tự động ghi hình khi phát hiện chuyển động.

Nối 3 thứ lại với nhau:
  - StreamWidget.latest_frame()   -> khung hình đang xem (luồng "sub" nhẹ)
  - motion.MotionDetector/Policy  -> "có chuyển động không / khi nào ghi / dừng"
  - một EmergencyRecorder RIÊNG   -> ghi file .mkv (phiên libVLC riêng, thư mục
                                     phiên riêng `emergency_motion_<id>/`)

Recorder tự động là một đối tượng ĐỘC LẬP với recorder ghi tay (nút REC):
bấm/tắt REC thủ công không đụng tới ghi tự động và ngược lại; hai bên ghi vào
hai thư mục phiên khác nhau nên không bao giờ ghi đè file của nhau.

Ghi chú: ghi bắt đầu SAU khi phát hiện chuyển động (cần vài khung liên tiếp để
loại nhiễu), nên vài giây đầu của sự kiện có thể không có trong file. Muốn có
"pre-roll" phải ghi liên tục vào bộ đệm — chưa làm ở bản này.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QImage

from motion import (
    ACTION_START,
    ACTION_STOP,
    DETECT_HEIGHT,
    DETECT_WIDTH,
    MotionDetector,
    MotionRecordingPolicy,
    get_motion_config,
)

SAMPLE_INTERVAL_MS = 500          # lấy mẫu ~2 khung/giây — đủ cho cửa ra vào
ERROR_BACKOFF_S = 60.0            # lỗi ghi (đầy đĩa, rớt luồng...) -> nghỉ rồi mới thử lại


def frame_to_gray_bytes(image: QImage, width: int = DETECT_WIDTH, height: int = DETECT_HEIGHT) -> bytes:
    """Thu nhỏ khung hình về ảnh xám width x height, trả về bytes liền mạch
    (không có byte đệm cuối dòng)."""
    small = image.scaled(
        width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
    ).convertToFormat(QImage.Format_Grayscale8)
    stride = small.bytesPerLine()
    raw = bytes(small.constBits())
    if stride == width:
        return raw[: width * height]
    return b"".join(raw[y * stride : y * stride + width] for y in range(height))


class MotionRecordingController(QObject):
    state_changed = Signal()

    def __init__(self, stream_widget, recorder, get_config, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self._stream = stream_widget
        self._recorder = recorder
        self._get_config = get_config      # callable trả về dict config đầy đủ
        self._clock = clock

        self._cfg = get_motion_config(self._get_config())
        self._detector = MotionDetector.from_config(self._cfg)
        self._policy = MotionRecordingPolicy(post_roll_s=self._cfg["post_roll_s"])
        self._suspended_until = 0.0
        self.last_error: str | None = None
        self.last_error_at = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(SAMPLE_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    # ---------- vòng đời ----------

    def start(self):
        if not self._timer.isActive():
            self._timer.start()

    def shutdown(self):
        """Gọi khi thoát app: dừng lấy mẫu và dừng ghi tự động đang chạy."""
        self._timer.stop()
        self._stop_recording()

    # ---------- cấu hình ----------

    def is_enabled(self) -> bool:
        return self._cfg["enabled"]

    def apply_config(self):
        """Đọc lại cấu hình (sau khi người dùng đổi ở Cài đặt / menu khay)."""
        self._cfg = get_motion_config(self._get_config())
        self._detector = MotionDetector.from_config(self._cfg)
        self._policy.post_roll_s = self._cfg["post_roll_s"]
        self._recorder.stream_type = self._cfg["stream_type"]
        if not self._cfg["enabled"]:
            self._stop_recording()
        self.state_changed.emit()

    # ---------- trạng thái cho UI ----------

    def is_recording(self) -> bool:
        return self._recorder.is_recording()

    def elapsed_seconds(self) -> int:
        return self._recorder.elapsed_seconds()

    # ---------- nội bộ ----------

    def _stop_recording(self):
        if self._recorder.is_recording():
            self._recorder.stop()
        self._policy.notify_stopped()
        self.state_changed.emit()

    def _fail(self, message: str, now: float):
        self.last_error = message
        self.last_error_at = now
        self._suspended_until = now + ERROR_BACKOFF_S
        self._policy.notify_stopped()
        print(f"[WARN] Ghi tự động theo chuyển động: {message}")
        self.state_changed.emit()

    def _tick(self):
        if not self._cfg["enabled"]:
            return
        now = self._clock()
        if now < self._suspended_until:
            return

        # Recorder tự dừng vì lỗi (đầy đĩa, mất luồng...) trong khi chính sách
        # vẫn nghĩ là đang ghi -> đồng bộ lại và nghỉ một lúc, tránh vòng lặp
        # bật/tắt liên tục.
        if self._policy.recording and not self._recorder.is_recording():
            self._fail("phiên ghi đã dừng do lỗi (đầy đĩa hoặc mất luồng)", now)
            return

        frame = self._stream.latest_frame()
        motion = False
        if frame is not None and not frame.isNull():
            gray = frame_to_gray_bytes(frame)
            motion = self._detector.process(gray, DETECT_WIDTH, DETECT_HEIGHT).motion

        action = self._policy.update(motion, now)
        if action == ACTION_START:
            self._start_recording(now)
        elif action == ACTION_STOP:
            self._stop_recording()

    def _start_recording(self, now: float):
        config = self._get_config()
        rtsp_cfg = config.get("rtsp", {})
        save_dir = config.get("recording", {}).get("save_dir", "")
        try:
            self._recorder.start(rtsp_cfg, save_dir)
        except Exception as exc:  # noqa: BLE001 — lỗi VLC có thể là nhiều loại
            self._fail(f"không bắt đầu được: {exc}", now)
            return
        if not self._recorder.is_recording():
            # start() trả về mà không ghi (vd lỗi thư mục / đầy đĩa) —
            # recording_error đã được emit từ recorder.
            self._fail("không bắt đầu được phiên ghi", now)
            return
        self.state_changed.emit()
