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
"""

import ctypes

from PySide6.QtWidgets import QFrame
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt, QRect, Signal

import vlc

_CHROMA = b"RV32"  # 32-bit RGB, layout byte tương thích QImage.Format_RGB32
_FALLBACK_WIDTH = 640   # chỉ dùng nếu vì lý do gì đó libVLC báo width/height = 0
_FALLBACK_HEIGHT = 360

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

    def __init__(self, rtsp_url: str, parent=None):
        super().__init__(parent)
        self.rtsp_url = rtsp_url
        self._qimage: QImage | None = None

        self._width = 0
        self._height = 0
        self._pitch = 0
        self._buf = None
        self._native_size_emitted = False

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

        self._frame_ready.connect(self.update)

        self.setMinimumSize(160, 90)
        self.setStyleSheet("background-color: black;")

    def start(self):
        media = self.instance.media_new(self.rtsp_url)
        media.add_option(":avcodec-hw=none")
        self.media_player.set_media(media)
        self.media_player.play()

    def set_rtsp_url(self, new_url: str):
        """Đổi RTSP URL đang dùng — gọi khi người dùng lưu cài đặt kết nối
        mới ở SettingsDialog (Sprint 4). Không tự start() lại, để nơi gọi
        quyết định thời điểm phát (thường sau khi stop() luồng cũ)."""
        self.rtsp_url = new_url

    def stop(self):
        self.media_player.stop()

    def is_playing(self) -> bool:
        return bool(self.media_player.is_playing())

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
