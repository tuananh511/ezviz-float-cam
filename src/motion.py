"""
motion.py — Phát hiện chuyển động + chính sách tự động ghi hình (bị động).

Module THUẦN (chỉ dùng stdlib, không PySide6/vlc) — giống tinh thần các module
trong `recording/` — để test được mà không cần Qt hay camera thật.

Gồm 3 phần độc lập:

1. `get_motion_config()` — gộp config người dùng với giá trị mặc định (file
   config.json cũ chưa có mục "motion" vẫn chạy bình thường) và kiểm tra/ép
   giá trị hợp lệ.
2. `MotionDetector` — nhận ảnh xám nhỏ (bytes) từng khung, so với "nền" (trung
   bình trượt) để biết có chuyển động hay không. Chống 2 kiểu báo nhầm hay gặp
   với camera trong nhà: (a) đổi sáng toàn khung (camera tự chỉnh phơi sáng,
   chuyển IR ngày/đêm) -> coi là "đổi cảnh", không phải chuyển động; (b) nhiễu
   nén video -> cần đủ tỉ lệ điểm ảnh đổi mới tính.
3. `MotionRecordingPolicy` — máy trạng thái nhỏ: khi nào BẮT ĐẦU ghi (phải có
   chuyển động liên tiếp vài lần lấy mẫu, tránh 1 khung nhiễu) và khi nào DỪNG
   (hết chuyển động quá `post_roll_s` giây). Thời gian được truyền vào từ bên
   ngoài nên test không cần sleep.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------

DEFAULT_MOTION_CONFIG = {
    "enabled": True,
    "sensitivity": "medium",   # "low" | "medium" | "high"
    "post_roll_s": 15,         # tiếp tục ghi thêm bao lâu sau chuyển động cuối
    "stream_type": "main",     # luồng dùng để GHI tự động ("main" nét, "sub" nhẹ)
    "roi": None,               # None = cả khung; hoặc [x0, y0, x1, y1] tỉ lệ 0..1
}

# (ngưỡng chênh lệch độ sáng 0..255 để coi 1 điểm ảnh là "đổi",
#  tỉ lệ điểm ảnh đổi tối thiểu trong vùng theo dõi để coi là chuyển động)
SENSITIVITY_PRESETS = {
    "low": (40, 0.04),
    "medium": (28, 0.02),
    "high": (18, 0.008),
}

POST_ROLL_MIN_S = 5
POST_ROLL_MAX_S = 300

# Kích thước ảnh xám dùng để phát hiện (bội số của 4 để dòng quét không bị
# đệm thêm byte) — nhỏ vì chỉ cần thấy "có thay đổi lớn" chứ không cần chi tiết.
DETECT_WIDTH = 96
DETECT_HEIGHT = 54


def _valid_roi(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        return None
    return [x0, y0, x1, y1]


def get_motion_config(config: dict | None) -> dict:
    """Trả về cấu hình chuyển động ĐÃ HỢP LỆ HOÁ từ `config["motion"]` (có thể
    thiếu hẳn). Không sửa dict đầu vào."""
    raw = (config or {}).get("motion")
    if not isinstance(raw, dict):
        raw = {}
    merged = dict(DEFAULT_MOTION_CONFIG)
    merged.update({k: raw[k] for k in DEFAULT_MOTION_CONFIG if k in raw})

    merged["enabled"] = bool(merged["enabled"])

    if merged["sensitivity"] not in SENSITIVITY_PRESETS:
        merged["sensitivity"] = DEFAULT_MOTION_CONFIG["sensitivity"]

    try:
        post_roll = int(merged["post_roll_s"])
    except (TypeError, ValueError):
        post_roll = DEFAULT_MOTION_CONFIG["post_roll_s"]
    merged["post_roll_s"] = max(POST_ROLL_MIN_S, min(POST_ROLL_MAX_S, post_roll))

    if merged["stream_type"] not in ("main", "sub"):
        merged["stream_type"] = DEFAULT_MOTION_CONFIG["stream_type"]

    merged["roi"] = _valid_roi(merged["roi"])
    return merged


# ---------------------------------------------------------------------------
# Phát hiện chuyển động
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MotionResult:
    motion: bool
    changed_ratio: float
    scene_change: bool = False   # đổi sáng/cảnh toàn khung — KHÔNG tính là chuyển động
    warming_up: bool = False     # vài khung đầu, chưa có nền đáng tin


class MotionDetector:
    """So từng khung ảnh xám với nền trung bình trượt (EMA)."""

    def __init__(
        self,
        pixel_threshold: int = 28,
        min_changed_ratio: float = 0.02,
        background_alpha: float = 0.05,
        scene_change_ratio: float = 0.6,
        warmup_frames: int = 3,
        roi=None,
    ):
        self.pixel_threshold = pixel_threshold
        self.min_changed_ratio = min_changed_ratio
        self.background_alpha = background_alpha
        self.scene_change_ratio = scene_change_ratio
        self.warmup_frames = warmup_frames
        self.roi = _valid_roi(roi)
        self.reset()

    @classmethod
    def from_config(cls, motion_cfg: dict) -> "MotionDetector":
        threshold, ratio = SENSITIVITY_PRESETS[motion_cfg["sensitivity"]]
        return cls(
            pixel_threshold=threshold,
            min_changed_ratio=ratio,
            roi=motion_cfg.get("roi"),
        )

    def reset(self):
        self._bg: list[float] | None = None
        self._size: tuple[int, int] | None = None
        self._indices: list[int] = []
        self._seen = 0

    def _build_indices(self, width: int, height: int) -> list[int]:
        if self.roi is None:
            return list(range(width * height))
        x0, y0, x1, y1 = self.roi
        cx0, cx1 = int(x0 * width), max(int(x0 * width) + 1, int(round(x1 * width)))
        cy0, cy1 = int(y0 * height), max(int(y0 * height) + 1, int(round(y1 * height)))
        cx1, cy1 = min(cx1, width), min(cy1, height)
        return [y * width + x for y in range(cy0, cy1) for x in range(cx0, cx1)]

    def process(self, gray: bytes, width: int, height: int) -> MotionResult:
        if len(gray) != width * height:
            raise ValueError("kích thước dữ liệu ảnh xám không khớp width*height")

        if self._size != (width, height):
            self.reset()
            self._size = (width, height)
            self._indices = self._build_indices(width, height)

        if self._bg is None:
            self._bg = [float(v) for v in gray]
            self._seen = 1
            return MotionResult(False, 0.0, warming_up=True)

        bg = self._bg
        thr = self.pixel_threshold
        indices = self._indices
        changed = sum(1 for i in indices if abs(gray[i] - bg[i]) > thr)
        ratio = changed / len(indices) if indices else 0.0

        # "Đổi cảnh" (đổi sáng/chuyển IR) phải xét trên TOÀN KHUNG, không phải
        # riêng vùng ROI: với ROI nhỏ quanh cửa, một người đứng choán hết ROI
        # là chuyển động thật chứ không phải đổi cảnh. Khi có ROI, lấy mẫu thưa
        # (mỗi 3 điểm ảnh) toàn khung cho nhẹ.
        if self.roi is None:
            global_ratio = ratio
        else:
            sample = range(0, len(gray), 3)
            global_ratio = sum(1 for i in sample if abs(gray[i] - bg[i]) > thr) / len(sample)

        if global_ratio >= self.scene_change_ratio:
            # Đổi sáng/cảnh toàn khung: lấy khung hiện tại làm nền mới.
            self._bg = [float(v) for v in gray]
            self._seen = 1
            return MotionResult(False, global_ratio, scene_change=True, warming_up=True)

        a = self.background_alpha
        self._bg = [b + (g - b) * a for b, g in zip(bg, gray)]
        self._seen += 1

        if self._seen <= self.warmup_frames:
            return MotionResult(False, ratio, warming_up=True)
        return MotionResult(ratio >= self.min_changed_ratio, ratio)


# ---------------------------------------------------------------------------
# Chính sách bắt đầu / dừng ghi
# ---------------------------------------------------------------------------

ACTION_START = "start"
ACTION_STOP = "stop"


class MotionRecordingPolicy:
    """Quyết định bắt đầu/dừng ghi tự động từ chuỗi kết quả phát hiện.

    - Bắt đầu khi có chuyển động ở `trigger_samples` lần lấy mẫu LIÊN TIẾP.
    - Đang ghi mà còn chuyển động -> gia hạn (làm mới mốc chuyển động cuối).
    - Dừng khi đã quá `post_roll_s` giây kể từ chuyển động cuối.
    """

    def __init__(self, post_roll_s: float = 15, trigger_samples: int = 2):
        self.post_roll_s = post_roll_s
        self.trigger_samples = trigger_samples
        self._recording = False
        self._consecutive = 0
        self._last_motion = 0.0

    @property
    def recording(self) -> bool:
        return self._recording

    def update(self, motion: bool, now: float):
        """Trả về ACTION_START / ACTION_STOP / None."""
        if not self._recording:
            self._consecutive = self._consecutive + 1 if motion else 0
            if self._consecutive >= self.trigger_samples:
                self._recording = True
                self._last_motion = now
                return ACTION_START
            return None

        if motion:
            self._last_motion = now
            return None
        if now - self._last_motion >= self.post_roll_s:
            self._recording = False
            self._consecutive = 0
            return ACTION_STOP
        return None

    def notify_stopped(self):
        """Bên ngoài đã dừng ghi (lỗi ổ đĩa, rớt kết nối, tắt tính năng...)."""
        self._recording = False
        self._consecutive = 0
