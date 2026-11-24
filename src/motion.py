"""
motion.py — Phát hiện chuyển động + chính sách tự động ghi hình (bị động).

Module THUẦN (chỉ dùng stdlib, không PySide6/vlc) — giống tinh thần các module
trong `recording/` — để test được mà không cần Qt hay camera thật.

Gồm 3 phần độc lập:

1. `get_motion_config()` — gộp config người dùng với giá trị mặc định (file
   config.json cũ chưa có mục "motion" vẫn chạy bình thường) và kiểm tra/ép
   giá trị hợp lệ.
2. `MotionDetector` — nhận ảnh xám nhỏ (bytes) từng khung, so với "nền" (trung
   bình trượt) để biết có chuyển động hay không. Chống các kiểu báo nhầm hay
   gặp với camera trong nhà:
   (a) đổi sáng toàn khung (camera tự chỉnh phơi sáng, chuyển IR ngày/đêm) ->
       coi là "đổi cảnh", không phải chuyển động;
   (b) nhiễu nén video -> cần đủ tỉ lệ điểm ảnh đổi mới tính;
   (c) ÁNH SÁNG cục bộ (đèn cửa, đèn pha xe quét qua): so sánh sau khi trừ độ
       lệch sáng trung bình của từng ô nhỏ (`light_compensation`), nên chỉ phần
       CẤU TRÚC hình ảnh đổi (người/vật đi vào) mới tính, vệt sáng thì bỏ qua;
   (d) CAMERA TỰ XOAY (theo dõi chuyển động, tự quay về vị trí, quét 360°): khi
       gần như toàn khung đổi liên tục, coi là "camera di chuyển" và tạm dừng
       phát hiện thêm `settle_frames` khung sau lần di chuyển cuối.
3. `MotionRecordingPolicy` — máy trạng thái nhỏ: khi nào BẮT ĐẦU ghi (phải có
   chuyển động kéo dài đủ lâu — `min_duration_s` — nên một vệt sáng/lia máy
   thoáng qua bị bỏ qua) và khi nào DỪNG
   (hết chuyển động quá `post_roll_s` giây). Thời gian được truyền vào từ bên
   ngoài nên test không cần sleep.
"""

from __future__ import annotations

from collections import deque
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
    "min_duration_s": 2.0,     # chuyển động phải kéo dài ít nhất bấy lâu mới bắt đầu ghi
    "ignore_light_changes": True,   # bỏ qua thay đổi ánh sáng (đèn cửa, đèn pha...)
    "camera_settle_s": 10,     # camera tự xoay -> tạm dừng phát hiện bấy lâu sau lần xoay cuối
    "pre_roll_s": 0,           # ghi thêm đoạn TRƯỚC chuyển động (0 = tắt, cần bộ đệm)
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
MIN_DURATION_MIN_S = 0.5
MIN_DURATION_MAX_S = 10.0
CAMERA_SETTLE_MAX_S = 120
PRE_ROLL_MAX_S = 30

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

    try:
        min_dur = float(merged["min_duration_s"])
    except (TypeError, ValueError):
        min_dur = DEFAULT_MOTION_CONFIG["min_duration_s"]
    merged["min_duration_s"] = max(MIN_DURATION_MIN_S, min(MIN_DURATION_MAX_S, min_dur))

    merged["ignore_light_changes"] = bool(merged["ignore_light_changes"])

    for key, hi in (("camera_settle_s", CAMERA_SETTLE_MAX_S), ("pre_roll_s", PRE_ROLL_MAX_S)):
        try:
            value = int(merged[key])
        except (TypeError, ValueError):
            value = DEFAULT_MOTION_CONFIG[key]
        merged[key] = max(0, min(hi, value))
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

    # Kích thước ô dùng để bù sáng cục bộ (trên ảnh 96x54 -> lưới 12x9 ô).
    BLOCK_W = 8
    BLOCK_H = 6

    def __init__(
        self,
        pixel_threshold: int = 28,
        min_changed_ratio: float = 0.02,
        background_alpha: float = 0.05,
        scene_change_ratio: float = 0.6,
        warmup_frames: int = 3,
        roi=None,
        light_compensation: bool = True,
        move_ratio: float = 0.3,
        move_run: int = 2,
        settle_frames: int = 0,
    ):
        self.pixel_threshold = pixel_threshold
        self.min_changed_ratio = min_changed_ratio
        self.background_alpha = background_alpha
        self.scene_change_ratio = scene_change_ratio
        self.warmup_frames = warmup_frames
        self.roi = _valid_roi(roi)
        self.light_compensation = light_compensation
        # "Camera di chuyển": >= move_ratio điểm ảnh khác KHUNG TRƯỚC, liên tiếp
        # move_run lần lấy mẫu (một người đi ngang gần camera hiếm khi làm đổi
        # >30% khung hình liên tục như vậy, còn camera xoay thì có).
        self.move_ratio = move_ratio
        self.move_run = move_run
        self.settle_frames = settle_frames
        self.reset()

    @classmethod
    def from_config(cls, motion_cfg: dict, sample_interval_s: float = 0.5) -> "MotionDetector":
        threshold, ratio = SENSITIVITY_PRESETS[motion_cfg["sensitivity"]]
        settle = int(round(motion_cfg.get("camera_settle_s", 0) / sample_interval_s))
        return cls(
            pixel_threshold=threshold,
            min_changed_ratio=ratio,
            roi=motion_cfg.get("roi"),
            light_compensation=motion_cfg.get("ignore_light_changes", True),
            settle_frames=settle,
        )

    def reset(self):
        self._bg: list[float] | None = None
        self._prev: bytes | None = None
        self._size: tuple[int, int] | None = None
        self._indices: list[int] = []
        self._sample: range = range(0)
        self._blk: list[int] = []
        self._blk_size: list[int] = []
        self._seen = 0
        self._big_run = 0
        self._settle_left = 0

    def _prepare(self, width: int, height: int):
        self._size = (width, height)
        self._indices = self._build_indices(width, height)
        self._sample = range(0, width * height, 2)
        cols = -(-width // self.BLOCK_W)
        self._blk = [
            (y // self.BLOCK_H) * cols + (x // self.BLOCK_W)
            for y in range(height) for x in range(width)
        ]
        counts = [0] * (max(self._blk) + 1)
        for b in self._blk:
            counts[b] += 1
        self._blk_size = counts

    def _build_indices(self, width: int, height: int) -> list[int]:
        if self.roi is None:
            return list(range(width * height))
        x0, y0, x1, y1 = self.roi
        cx0, cx1 = int(x0 * width), max(int(x0 * width) + 1, int(round(x1 * width)))
        cy0, cy1 = int(y0 * height), max(int(y0 * height) + 1, int(round(y1 * height)))
        cx1, cy1 = min(cx1, width), min(cy1, height)
        return [y * width + x for y in range(cy0, cy1) for x in range(cx0, cx1)]

    def _changed_count(self, gray: bytes, bg: list[float]) -> int:
        thr = self.pixel_threshold
        indices = self._indices
        if not self.light_compensation:
            return sum(1 for i in indices if abs(gray[i] - bg[i]) > thr)
        # Bù sáng cục bộ: trừ độ lệch sáng TRUNG BÌNH của từng ô nhỏ trước khi
        # so sánh, nên vệt sáng (đèn cửa, đèn pha) làm cả ô sáng lên đều không
        # được tính là chuyển động; người/vật đi vào làm đổi CẤU TRÚC trong ô thì vẫn tính.
        blk = self._blk
        sums = [0.0] * len(self._blk_size)
        for i, b in enumerate(blk):
            sums[b] += gray[i] - bg[i]
        offsets = [sums[b] / self._blk_size[b] for b in range(len(sums))]
        return sum(1 for i in indices if abs(gray[i] - bg[i] - offsets[blk[i]]) > thr)

    def process(self, gray: bytes, width: int, height: int) -> MotionResult:
        if len(gray) != width * height:
            raise ValueError("kích thước dữ liệu ảnh xám không khớp width*height")

        if self._size != (width, height):
            self.reset()
            self._prepare(width, height)

        if self._bg is None:
            self._bg = [float(v) for v in gray]
            self._prev = gray
            self._seen = 1
            return MotionResult(False, 0.0, warming_up=True)

        bg = self._bg
        prev = self._prev
        thr = self.pixel_threshold
        sample = self._sample
        n = len(sample)
        # Đổi cảnh / camera di chuyển: xét trên ảnh THÔ, toàn khung, bất kể ROI.
        bg_ratio = sum(1 for i in sample if abs(gray[i] - bg[i]) > thr) / n
        prev_ratio = sum(1 for i in sample if abs(gray[i] - prev[i]) > thr) / n
        self._prev = gray
        self._big_run = self._big_run + 1 if prev_ratio >= self.move_ratio else 0

        if bg_ratio >= self.scene_change_ratio or self._big_run >= self.move_run:
            # Đổi sáng toàn khung hoặc camera đang xoay: lấy khung hiện tại làm
            # nền mới và tạm dừng phát hiện `settle_frames` khung.
            self._bg = [float(v) for v in gray]
            self._seen = 1
            self._big_run = 0
            self._settle_left = self.settle_frames
            return MotionResult(False, max(bg_ratio, prev_ratio), scene_change=True, warming_up=True)

        if self._settle_left > 0:
            # Đang "ổn định" sau khi camera xoay/đổi cảnh: nền thích nghi nhanh.
            self._settle_left -= 1
            self._bg = [b + (g - b) * 0.5 for b, g in zip(bg, gray)]
            return MotionResult(False, bg_ratio, warming_up=True)

        changed = self._changed_count(gray, bg)
        ratio = changed / len(self._indices) if self._indices else 0.0

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

    - Bắt đầu khi có chuyển động ở ít nhất `trigger_samples` trong `window`
      lần lấy mẫu gần nhất (mặc định window = trigger_samples, tức phải LIÊN
      TIẾP). Đặt window lớn hơn để chịu được vài lần lấy mẫu "đứng yên" xen
      giữa khi người đi chậm.
    - Đang ghi mà còn chuyển động -> gia hạn (làm mới mốc chuyển động cuối).
    - Dừng khi đã quá `post_roll_s` giây kể từ chuyển động cuối.
    """

    def __init__(self, post_roll_s: float = 15, trigger_samples: int = 2, window: int | None = None):
        self._recording = False
        self._last_motion = 0.0
        self.configure(post_roll_s, trigger_samples, window)

    def configure(self, post_roll_s: float, trigger_samples: int, window: int | None = None):
        """Đổi tham số mà KHÔNG làm mất trạng thái đang ghi."""
        self.post_roll_s = post_roll_s
        self.trigger_samples = max(1, trigger_samples)
        self.window = max(self.trigger_samples, window or self.trigger_samples)
        self._recent: deque[bool] = deque(maxlen=self.window)

    @property
    def recording(self) -> bool:
        return self._recording

    def update(self, motion: bool, now: float):
        """Trả về ACTION_START / ACTION_STOP / None."""
        if not self._recording:
            self._recent.append(bool(motion))
            if sum(self._recent) >= self.trigger_samples:
                self._recording = True
                self._last_motion = now
                self._recent.clear()
                return ACTION_START
            return None

        if motion:
            self._last_motion = now
            return None
        if now - self._last_motion >= self.post_roll_s:
            self._recording = False
            self._recent.clear()
            return ACTION_STOP
        return None

    def notify_stopped(self):
        """Bên ngoài đã dừng ghi (lỗi ổ đĩa, rớt kết nối, tắt tính năng...)."""
        self._recording = False
        self._recent.clear()
