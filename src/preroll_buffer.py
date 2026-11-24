"""
preroll_buffer.py — bộ đệm cuốn chiếu để ghi được cả đoạn TRƯỚC khi phát hiện
chuyển động ("pre-roll").

Một phiên libVLC riêng chạy liên tục trên luồng NHẸ (sub) của camera, ghi
vào thư mục tạm bằng bộ cắt đoạn `livehttp` của VLC (chỉ giữ vài đoạn gần
nhất, VLC tự xoá đoạn cũ). Khi phát hiện chuyển động, `snapshot()` ghép các
đoạn gần nhất thành một khối MPEG-TS để ghi vào thư mục phiên (xem
recording/preroll.py và EmergencyRecorder.write_preroll_clip()).

Đánh đổi (cần biết): thêm MỘT kết nối RTSP liên tục tới camera + ghi đĩa liên
tục một lượng nhỏ (bằng bitrate luồng nhẹ, ghi đè liên tục trong thư mục tạm).
Vì vậy mặc định TẮT (`motion.pre_roll_s = 0`). Bộ đệm không có tiếng (TS không
chứa được âm thanh G.711 của camera) và có thể hở khoảng 1–3 giây giữa cuối
đoạn đệm và lúc bản ghi chính bắt đầu.

Mọi lỗi ở đây chỉ làm mất tính năng pre-roll (ghi tự động vẫn chạy bình
thường) — không bao giờ làm sập app.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import vlc
from PySide6.QtCore import QObject, QTimer

from config_loader import build_rtsp_url
from recording.preroll import (
    SEG_LEN_S,
    build_buffer_sout,
    clear_buffer_dir,
    list_segments,
    read_clip,
    select_recent_segments,
)

WATCHDOG_INTERVAL_MS = 5000
RESTART_BACKOFF_S = 15.0


def default_buffer_dir() -> Path:
    return Path(tempfile.gettempdir()) / "EzvizFloatCam" / "preroll"


class PreRollBuffer(QObject):
    def __init__(self, parent=None, *, buffer_dir=None, clock=time.monotonic):
        super().__init__(parent)
        self._dir = Path(buffer_dir) if buffer_dir else default_buffer_dir()
        self._clock = clock
        self._instance = None
        self._player = None
        self._media = None
        self._wanted: tuple[str, int] | None = None   # (rtsp_url, pre_roll_s) mong muốn
        self._running_for: tuple[str, int] | None = None
        self._retry_at = 0.0
        self.last_error: str | None = None

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self._check)

    # ---------- cấu hình ----------

    @property
    def buffer_dir(self) -> Path:
        return self._dir

    def configure(self, rtsp_cfg: dict | None, pre_roll_s: int):
        """Đặt cấu hình mong muốn: pre_roll_s <= 0 hoặc không có rtsp_cfg thì tắt;
        ngược lại bật (hoặc khởi động lại nếu địa chỉ/độ dài đổi)."""
        if not rtsp_cfg or pre_roll_s <= 0:
            self._wanted = None
            self._watchdog.stop()
            self._stop_player()
            return
        cfg = dict(rtsp_cfg)
        cfg["stream_type"] = "sub"          # luôn dùng luồng nhẹ cho bộ đệm
        wanted = (build_rtsp_url(cfg), int(pre_roll_s))
        if wanted == self._wanted and self.is_running():
            return
        self._wanted = wanted
        self._retry_at = 0.0
        self._watchdog.start()
        self._start_player()

    def is_running(self) -> bool:
        return self._player is not None

    def shutdown(self):
        self._wanted = None
        self._watchdog.stop()
        self._stop_player()

    # ---------- đoạn đệm ----------

    def snapshot(self, pre_roll_s: int) -> bytes:
        """Ghép các đoạn đệm gần nhất (đủ phủ `pre_roll_s` giây). Rỗng nếu bộ
        đệm chưa chạy / chưa có đoạn nào."""
        if not self.is_running():
            return b""
        try:
            segs = select_recent_segments(list_segments(self._dir), pre_roll_s, SEG_LEN_S)
            return read_clip(segs)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"không đọc được bộ đệm: {exc}"
            return b""

    # ---------- VLC ----------

    def _start_player(self):
        self._stop_player()
        if self._wanted is None:
            return
        url, pre_roll_s = self._wanted
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            clear_buffer_dir(self._dir)   # dọn file sót lần chạy trước
            instance = vlc.Instance(["--no-xlib", "--rtsp-tcp", "--quiet"])
            player = instance.media_player_new()
            media = instance.media_new(url)
            media.add_option(":sout=" + build_buffer_sout(self._dir, pre_roll_s))
            media.add_option(":sout-keep")
            media.add_option(":no-audio")
            player.set_media(media)
            player.play()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self._retry_at = self._clock() + RESTART_BACKOFF_S
            print(f"[WARN] Bộ đệm pre-roll không khởi động được: {exc}")
            return
        self._instance, self._player, self._media = instance, player, media
        self._running_for = self._wanted
        self.last_error = None

    def _stop_player(self):
        player, instance, media = self._player, self._instance, self._media
        self._player = self._instance = self._media = None
        self._running_for = None
        for obj, method in ((player, "stop"), (player, "release"),
                            (media, "release"), (instance, "release")):
            if obj is None:
                continue
            try:
                getattr(obj, method)()
            except Exception:  # noqa: BLE001
                pass
        clear_buffer_dir(self._dir)

    def _check(self):
        """Mỗi vài giây: nếu phiên VLC đã chết (rớt kết nối, camera khởi động
        lại...) thì khởi động lại sau một khoảng nghỉ."""
        if self._wanted is None:
            return
        if self._player is not None:
            try:
                state = self._player.get_state()
            except Exception:  # noqa: BLE001
                state = None
            if state not in (vlc.State.Ended, vlc.State.Error, vlc.State.Stopped, None):
                return
            self._stop_player()
            self._retry_at = self._clock() + RESTART_BACKOFF_S
            return
        if self._clock() >= self._retry_at:
            self._start_player()
