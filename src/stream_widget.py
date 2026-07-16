"""
stream_widget.py
Widget Qt hiển thị video RTSP qua libVLC.

Sprint 2 (bản fix video cuối): sau khi thử --avcodec-hw=none và
--vout=wingdi vẫn không tránh được lỗi "SetThumbNailClip failed" (xem
glass_window.py để biết thêm chi tiết lịch sử), chuyển hẳn sang render
video qua callback bộ nhớ RAM (`video_set_callbacks`) thay vì nhúng cửa sổ
native — không phụ thuộc bất kỳ module vout nào của libVLC nữa.

Bản fix méo hình (sau khi verify thực tế thấy camera bị kéo dãn/lệch tỉ
lệ): lúc đầu ép cứng buffer về 640x360 (16:9) bất kể camera thật quay tỉ lệ
gì, gây méo hình. Giờ dùng `video_set_format_callbacks()` — libVLC sẽ TỰ
BÁO đúng width/height gốc của stream (qua callback `_format_cb`), mình chỉ
ép chroma về RV32 (giữ nguyên kích thước), rồi khi vẽ (`paintEvent`) luôn
giữ đúng tỉ lệ khung hình gốc (letterbox nếu tỉ lệ khung Qt không khớp)
thay vì kéo dãn lấp đầy toàn bộ ô vuông.

Lưu ý kỹ thuật quan trọng: `vlc.cb.VideoFormatCb` (kiểu callback có sẵn của
python-vlc) khai báo tham số `chroma` là `ctypes.c_char_p` — kiểu này khi
gọi vào Python sẽ tự copy ra 1 `bytes` object, KHÔNG cho phép ghi ngược lại
vùng nhớ gốc để báo cho libVLC biết mình muốn đổi chroma. Vì vậy ở đây tự
khai báo lại kiểu callback với `chroma` là `ctypes.c_void_p` rồi dùng
`ctypes.memmove()` ghi trực tiếp 4 byte "RV32" vào đúng địa chỉ đó.
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
# có sẵn của python-vlc dùng c_char_p cho chroma — không ghi ngược được.
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

    def __init__(self, rtsp_url: str, parent=None):
        super().__init__(parent)
        self.rtsp_url = rtsp_url
        self._qimage: QImage | None = None

        self._width = 0
        self._height = 0
        self._pitch = 0
        self._buf = None

        vlc_args = [
            "--no-xlib",
            "--rtsp-tcp",
            "--network-caching=800",
            "--avcodec-hw=none",  # tắt hardware decode, tránh lỗi D3D11VA deadlock
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

        self.setMinimumSize(320, 200)
        self.setStyleSheet("background-color: black;")

    def start(self):
        media = self.instance.media_new(self.rtsp_url)
        media.add_option(":avcodec-hw=none")
        self.media_player.set_media(media)
        self.media_player.play()

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

        # căn pitch lên bội số của 32 theo khuyến nghị của libVLC (tránh lỗi
        # giả định về alignment trong 1 số decoder/filter).
        pitch = ((w * 4 + 31) // 32) * 32

        self._width = w
        self._height = h
        self._pitch = pitch
        self._buf = (ctypes.c_ubyte * (pitch * h))()

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

        # Giữ đúng tỉ lệ khung hình gốc của camera — không kéo dãn lấp đầy
        # toàn bộ ô, tránh méo hình khi tỉ lệ widget khác tỉ lệ video thật.
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
