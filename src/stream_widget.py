"""
stream_widget.py
Widget Qt hiển thị video RTSP qua libVLC.

LỊCH SỬ (Sprint 2 — quan trọng, đọc trước khi sửa gì ở file này):
Ban đầu nhúng video qua cửa sổ native (`set_hwnd`), hoạt động đúng ở Sprint 1
nhưng khi thêm Glass UI (cửa sổ frameless/translucent/bo góc) thì bị lỗi
"SetThumbNailClip failed"/"buffer deadlock" (xung đột Direct3D11 của libVLC
với loại cửa sổ này). Chuyển sang render qua buffer callback
(`video_set_callbacks` + `video_set_format_callbacks`, không nhúng cửa sổ
native nữa) — né được lỗi Direct3D nói trên. Sau đó có hiện tượng hình "lệch"
— đã nghi ngờ nhiều hướng (pitch, ép --vout=vmem...) nhưng RỐT CUỘC nguyên
nhân thật nằm ở lớp UI (`glass_window.py`): phần margin viền kính + letterbox
giữ tỉ lệ chồng lên nhau gây cảm giác lệch, không phải bug ở file này. Vẫn
giữ lại `--vout=vmem` vì đây là fix đúng/cần thiết cho 1 lỗi thật đã gặp
(libVLC tự mở thêm 1 cửa sổ video song song nếu không ép rõ module này).

LỊCH SỬ (Sprint bổ sung — tự động kết nối lại + màn hình "mất tín hiệu"):
Trước đây khi RTSP rớt kết nối (mất mạng, camera tắt...), app không có cơ
chế phát hiện/khôi phục nào — cửa sổ chỉ đứng hình (thường trông như "đen
sì" vì frame cuối cùng không còn ý nghĩa, người dùng khó phân biệt "đang
xem" hay "đã rớt mạng"). Thêm 2 lớp phát hiện mất kết nối (dùng CẢ HAI vì
mỗi cách chỉ bắt được 1 kiểu lỗi khác nhau):
  1. Lắng nghe event thật từ libVLC (`MediaPlayerEncounteredError`,
     `MediaPlayerEndReached`) — bắt được lỗi rõ ràng (sai mật khẩu, server
     đóng kết nối...). Các callback này chạy trên THREAD RIÊNG của libVLC,
     không được đụng trực tiếp vào Qt GUI — nên chỉ emit Signal rỗng, Qt tự
     đưa việc xử lý thật (queued) về đúng thread chính.
  2. "Watchdog" (QTimer ở thread chính) theo dõi thời điểm frame gần nhất
     — nếu quá lâu không có frame mới (mất mạng kiểu "im lặng", không có
     event lỗi nào cả) thì vẫn coi là rớt kết nối. Đây là lưới an toàn cho
     trường hợp (1) không bắt được.
Khi phát hiện rớt kết nối: tự thử kết nối lại vài lần (có backoff tăng dần),
trong lúc đó hiển thị màn hình "ĐANG KẾT NỐI LẠI" (nhiễu TV + đếm số lần
thử). Nếu vẫn thất bại sau số lần thử tối đa, chuyển sang màn hình "MẤT TÍN
HIỆU" và tiếp tục tự thử lại ở tần suất thưa hơn (không giới hạn số lần) —
tự khôi phục khi camera/mạng có lại mà không cần người dùng làm gì.
"""

import ctypes
import os
import time

from PySide6.QtWidgets import QFrame
from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtCore import Qt, QRect, QTimer, Signal

import vlc

_CHROMA = b"RV32"  # 32-bit RGB, layout byte tương thích QImage.Format_RGB32
_FALLBACK_WIDTH = 640   # chỉ dùng nếu vì lý do gì đó libVLC báo width/height = 0
_FALLBACK_HEIGHT = 360

# ---- cấu hình tự kết nối lại ----
MAX_RETRIES = 5  # số lần thử "dồn dập" trước khi coi là "mất tín hiệu"
# thời gian chờ (ms) trước mỗi lần thử, tăng dần (backoff) — lần cuối lặp lại
# giá trị cuối danh sách nếu MAX_RETRIES lớn hơn độ dài danh sách này.
RETRY_DELAYS_MS = [1500, 3000, 5000, 8000, 12000]
SLOW_RETRY_INTERVAL_MS = 15000  # sau khi hết lượt thử dồn dập, thử lại mỗi 15s
WATCHDOG_INTERVAL_MS = 2000
FRAME_STALE_TIMEOUT_S = 6.0  # không có frame mới trong ngần này -> coi như rớt
NOISE_INTERVAL_MS = 150  # tốc độ "nhiễu TV" nhấp nháy khi mất tín hiệu
_NOISE_W, _NOISE_H = 64, 36  # nhỏ + phóng to lúc vẽ, đủ giống nhiễu TV thật

# Tự khai báo lại 2 kiểu callback này (khác với vlc.cb.VideoFormatCb) vì bản
# có sẵn của python-vlc dùng c_char_p cho chroma — không cho phép ghi ngược
# lại giá trị mới vào đúng vùng nhớ mà libVLC cấp (xem giải thích trong
# _on_format()).
_FormatCb = ctypes.CFUNCTYPE(
    ctypes.c_uint,                    # trả về: số buffer cấp phát (0 = lỗi)
    ctypes.POINTER(ctypes.c_void_p),  # opaque (in/out)
    ctypes.c_void_p,                  # chroma: con trỏ 4 byte (in/out)
    ctypes.POINTER(ctypes.c_uint),    # width (in/out)
    ctypes.POINTER(ctypes.c_uint),    # height (in/out)
    ctypes.POINTER(ctypes.c_uint),    # pitches[] (out)
    ctypes.POINTER(ctypes.c_uint),    # lines[] (out)
)
_CleanupCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p)


class StreamWidget(QFrame):
    _frame_ready = Signal()
    # Phát ra đúng 1 lần khi biết được kích thước gốc thật của video (từ
    # libVLC báo về) — GlassWindow lắng nghe để khoá tỉ lệ cửa sổ theo đúng
    # tỉ lệ camera, tránh phải letterbox (viền đen thừa).
    native_size_ready = Signal(int, int)
    # "connecting" | "connected" | "reconnecting" | "no_signal" | "stopped"
    connection_state_changed = Signal(str)

    # cầu nối từ thread libVLC về thread Qt chính (xem giải thích ở đầu file)
    _vlc_error_evt = Signal()
    _vlc_end_evt = Signal()
    _frame_ok_evt = Signal()

    def __init__(self, rtsp_url: str, parent=None):
        super().__init__(parent)
        self.rtsp_url = rtsp_url
        self._qimage: QImage | None = None

        self._width = 0
        self._height = 0
        self._pitch = 0
        self._buf = None
        self._native_size_emitted = False

        # ---- trạng thái kết nối / tự thử lại ----
        self._state: str | None = None  # None = chưa từng start()
        self._user_stopped = True
        self._retry_count = 0
        self._reconnect_in_progress = False
        self._last_frame_time = time.monotonic()
        self._noise_image: QImage | None = None

        vlc_args = [
            "--no-xlib",
            "--rtsp-tcp",
            "--network-caching=800",
            "--avcodec-hw=none",  # tắt hardware decode, tránh lỗi D3D11VA deadlock
            # QUAN TRỌNG: ép rõ ràng chỉ dùng đúng module vout "vmem" (render
            # qua bộ nhớ, đúng cái mà video_set_callbacks() cần). Nếu không
            # ép, libVLC có thể tự mở THÊM 1 cửa sổ video thật chạy song song
            # (đã gặp thật: log "Failed to set on top" + quay lại lỗi D3D11
            # "buffer deadlock prevented").
            "--vout=vmem",
        ]
        self.instance = vlc.Instance(vlc_args)
        self.media_player = self.instance.media_player_new()

        # Giữ tham chiếu tới mọi callback (bắt buộc — nếu không giữ, ctypes
        # sẽ garbage-collect trampoline và libVLC gọi vào vùng nhớ đã giải
        # phóng, gây crash khó hiểu).
        self._c_lock = vlc.cb.VideoLockCb(self._on_lock)
        self._c_unlock = vlc.cb.VideoUnlockCb(self._on_unlock)
        self._c_display = vlc.cb.VideoDisplayCb(self._on_display)
        self._c_format = _FormatCb(self._on_format)
        self._c_cleanup = _CleanupCb(self._on_cleanup)

        self.media_player.video_set_callbacks(self._c_lock, self._c_unlock, self._c_display, None)
        self.media_player.video_set_format_callbacks(self._c_format, self._c_cleanup)

        # Event thật từ libVLC — chạy trên thread riêng của libVLC, chỉ được
        # phép emit Signal ở đây (xử lý thật nằm trong slot ở thread chính).
        event_manager = self.media_player.event_manager()
        event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_vlc_error_thread)
        event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_vlc_end_thread)

        self._frame_ready.connect(self.update)
        self._vlc_error_evt.connect(self._begin_reconnect)
        self._vlc_end_evt.connect(self._begin_reconnect)
        self._frame_ok_evt.connect(self._on_frame_ok)

        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.timeout.connect(self._check_watchdog)

        self._noise_timer = QTimer(self)
        self._noise_timer.timeout.connect(self._regen_noise)

        self.setMinimumSize(160, 90)
        self.setStyleSheet("background-color: black;")

    # ---------- điều khiển phát/dừng ----------

    def start(self):
        self._user_stopped = False
        self._retry_count = 0
        self._reconnect_in_progress = False
        self._last_frame_time = time.monotonic()
        if self._state != "connected":
            self._set_state("connecting")
        self._play_media()
        if not self.watchdog_timer.isActive():
            self.watchdog_timer.start(WATCHDOG_INTERVAL_MS)

    def _play_media(self):
        media = self.instance.media_new(self.rtsp_url)
        media.add_option(":avcodec-hw=none")
        self.media_player.set_media(media)
        self.media_player.play()

    def set_rtsp_url(self, new_url: str):
        """Đổi RTSP URL đang dùng — gọi khi người dùng lưu cài đặt kết nối
        mới ở SettingsDialog (Sprint 4). Không tự start() lại, để nơi gọi
        quyết định thời điểm phát (thường sau khi stop() luồng cũ)."""
        self.rtsp_url = new_url
        self._retry_count = 0

    def stop(self):
        self._user_stopped = True
        self._reconnect_in_progress = False
        self.watchdog_timer.stop()
        self._noise_timer.stop()
        self.media_player.stop()
        self._set_state("stopped")

    def is_playing(self) -> bool:
        return bool(self.media_player.is_playing())

    def get_connection_state(self) -> str:
        """'connecting' | 'connected' | 'reconnecting' | 'no_signal' |
        'stopped' — dùng cho chấm trạng thái (GlassWindow) và về sau nếu
        cần hiện thêm ở tray."""
        return self._state or "stopped"

    def set_muted(self, muted: bool):
        """Bật/tắt tiếng — chỉ ảnh hưởng audio output, không đụng gì tới
        pipeline video (video_set_callbacks) ở trên."""
        self.media_player.audio_set_mute(muted)

    def is_muted(self) -> bool:
        return bool(self.media_player.audio_get_mute())

    # ---------- tự kết nối lại (chạy hoàn toàn trên thread chính Qt) ----------

    def _set_state(self, state: str):
        if state == self._state:
            return
        self._state = state
        if state in ("reconnecting", "no_signal"):
            # xoá frame cũ ngay — tránh hiện hình đứng hình gây hiểu lầm là
            # "vẫn đang xem bình thường", đúng yêu cầu ban đầu (không hiện
            # đen sì / hình cũ mập mờ mà báo rõ ràng đang mất tín hiệu).
            self._qimage = None
            if not self._noise_timer.isActive():
                self._regen_noise()
                self._noise_timer.start(NOISE_INTERVAL_MS)
        else:
            self._noise_timer.stop()
        self.connection_state_changed.emit(state)
        self.update()

    def _on_vlc_error_thread(self, event):
        self._vlc_error_evt.emit()

    def _on_vlc_end_thread(self, event):
        self._vlc_end_evt.emit()

    def _on_frame_ok(self):
        self._retry_count = 0
        self._reconnect_in_progress = False
        self._set_state("connected")

    def _check_watchdog(self):
        if self._user_stopped or self._reconnect_in_progress:
            return
        if self._state == "no_signal":
            # đã có lịch tự thử lại thưa riêng (SLOW_RETRY_INTERVAL_MS) do
            # _begin_reconnect() hẹn, watchdog không cần can thiệp thêm.
            return
        stale = (time.monotonic() - self._last_frame_time) > FRAME_STALE_TIMEOUT_S
        if stale:
            self._begin_reconnect()

    def _begin_reconnect(self):
        if self._user_stopped or self._reconnect_in_progress:
            return
        self._reconnect_in_progress = True
        self.media_player.stop()
        if self._retry_count < MAX_RETRIES:
            self._set_state("reconnecting")
            idx = min(self._retry_count, len(RETRY_DELAYS_MS) - 1)
            delay = RETRY_DELAYS_MS[idx]
            self._retry_count += 1
        else:
            self._set_state("no_signal")
            delay = SLOW_RETRY_INTERVAL_MS
        QTimer.singleShot(delay, self._do_reconnect_attempt)

    def _do_reconnect_attempt(self):
        self._reconnect_in_progress = False
        if self._user_stopped:
            return
        self._last_frame_time = time.monotonic()
        self._play_media()

    # ---------- nhiễu TV cho màn hình "mất tín hiệu" ----------

    def _regen_noise(self):
        buf = os.urandom(_NOISE_W * _NOISE_H)
        img = QImage(buf, _NOISE_W, _NOISE_H, _NOISE_W, QImage.Format_Grayscale8)
        self._noise_image = img.copy()  # copy() để buf cục bộ giải phóng an toàn
        self.update()

    # ---------- callback libVLC (chạy trên luồng nội bộ của libVLC, không
    # được đụng trực tiếp vào Qt GUI ở đây — chỉ ghi buffer / emit signal) ----------

    def _on_format(self, opaque, chroma_ptr, width_ptr, height_ptr, pitches_ptr, lines_ptr):
        w = width_ptr[0]
        h = height_ptr[0]
        if not w or not h:
            w, h = _FALLBACK_WIDTH, _FALLBACK_HEIGHT
            width_ptr[0] = w
            height_ptr[0] = h

        # KHÔNG làm tròn/căn lề pitch — dùng đúng width*4 (đã verify: làm
        # tròn lên bội số 32 từng gây hiểu nhầm là "lệch hình", dù nguyên
        # nhân thật nằm ở lớp UI — nhưng width*4 vẫn là giá trị đúng/an toàn
        # nhất, khớp các ví dụ tham khảo, nên giữ nguyên không làm tròn).
        pitch = w * 4

        self._width = w
        self._height = h
        self._pitch = pitch
        self._buf = (ctypes.c_ubyte * (pitch * h))()

        print(f"[INFO] Camera stream kích thước gốc: {w}x{h}")

        if not self._native_size_emitted:
            self._native_size_emitted = True
            self.native_size_ready.emit(w, h)

        ctypes.memmove(chroma_ptr, _CHROMA, 4)
        pitches_ptr[0] = pitch
        lines_ptr[0] = h
        return 1  # cấp 1 buffer

    def _on_cleanup(self, opaque):
        self._buf = None

    def _on_lock(self, opaque, planes):
        if self._buf is not None:
            planes[0] = ctypes.cast(self._buf, ctypes.c_void_p)
        return None

    def _on_unlock(self, opaque, picture, planes):
        return None

    def _on_display(self, opaque, picture):
        self._last_frame_time = time.monotonic()
        if self._state != "connected":
            self._frame_ok_evt.emit()
        if self._buf is None or not self._width or not self._height:
            return
        img = QImage(
            bytes(self._buf), self._width, self._height, self._pitch,
            QImage.Format_RGB32,
        )
        self._qimage = img.copy()
        self._frame_ready.emit()

    # ---------- vẽ trên luồng chính Qt ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        target = self.rect()

        if self._state in ("reconnecting", "no_signal"):
            self._paint_no_signal(painter, target)
            return

        painter.fillRect(target, Qt.black)

        img = self._qimage
        if img is None or img.width() == 0 or img.height() == 0:
            return

        # Giữ đúng tỉ lệ khung hình gốc (letterbox nếu tỉ lệ widget lệch tỉ
        # lệ video thật — bình thường ở lần vẽ đầu tiên trước khi
        # GlassWindow kịp khoá tỉ lệ cửa sổ theo native_size_ready).
        img_ratio = img.width() / img.height()
        target_ratio = target.width() / target.height() if target.height() else img_ratio

        if img_ratio > target_ratio:
            draw_w = target.width()
            draw_h = max(1, int(draw_w / img_ratio))
        else:
            draw_h = target.height()
            draw_w = max(1, int(draw_h * img_ratio))

        x = target.x() + (target.width() - draw_w) // 2
        y = target.y() + (target.height() - draw_h) // 2
        painter.drawImage(QRect(x, y, draw_w, draw_h), img)

    def _paint_no_signal(self, painter: QPainter, target: QRect):
        """Màn hình 'mất tín hiệu' — nhiễu TV kiểu cũ (dễ nhận ra ngay từ xa,
        khác hẳn với 1 khung hình đứng yên/đen sì dễ gây hiểu lầm là app bị
        treo hoặc vẫn đang xem bình thường)."""
        painter.fillRect(target, QColor(12, 12, 14))

        if self._noise_image is not None:
            painter.save()
            painter.setOpacity(0.5)
            painter.drawImage(target, self._noise_image)
            painter.restore()

        painter.fillRect(target, QColor(0, 0, 0, 140))

        title = "MẤT TÍN HIỆU" if self._state == "no_signal" else "ĐANG KẾT NỐI LẠI"
        if self._state == "reconnecting":
            sub = f"Đang thử lại... (lần {self._retry_count}/{MAX_RETRIES})"
        else:
            sub = "Sẽ tự kết nối lại khi có tín hiệu"

        title_size = max(9, min(16, target.height() // 10))
        sub_size = max(7, min(11, target.height() // 16))

        title_font = QFont(painter.font())
        title_font.setBold(True)
        title_font.setPointSize(title_size)
        painter.setFont(title_font)
        painter.setPen(QColor(235, 235, 235))
        title_rect = QRect(target.x(), target.center().y() - title_size - 6, target.width(), title_size + 10)
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignVCenter, title)

        sub_font = QFont(painter.font())
        sub_font.setBold(False)
        sub_font.setPointSize(sub_size)
        painter.setFont(sub_font)
        painter.setPen(QColor(190, 190, 190))
        sub_rect = QRect(target.x(), title_rect.bottom(), target.width(), sub_size + 12)
        painter.drawText(sub_rect, Qt.AlignHCenter | Qt.AlignTop, sub)
