"""
stream_widget.py
Widget Qt hiển thị video RTSP qua libVLC.

Sprint 2 (bản fix cuối): sau khi thử --avcodec-hw=none và --vout=wingdi vẫn
không tránh được lỗi "direct3d11 vout display error: SetThumbNailClip
failed" (GPU NVIDIA GTX 1060 + cửa sổ frameless/translucent — VLC dùng
Direct3D11 làm vout mặc định và ép qua --vout khác không có tác dụng đáng
tin cậy, theo xác nhận của chính dev VLC), chuyển hẳn sang cách nhúng khác:

- Dùng `video_set_callbacks()` + `video_set_format()` của libVLC: libVLC sẽ
  decode & tự scale video về đúng RENDER_WIDTH x RENDER_HEIGHT, ghi thẳng
  từng frame (định dạng RV32 — tương thích byte-order với QImage.Format_RGB32)
  vào 1 buffer bộ nhớ RAM do mình cấp, thay vì tự vẽ trực tiếp lên 1 cửa sổ
  native (set_hwnd) như trước.
- StreamWidget copy buffer đó thành QImage rồi tự `paintEvent` vẽ lên — vì
  vậy KHÔNG còn phụ thuộc bất kỳ module vout nào (Direct3D11/wingdi/...) của
  libVLC nữa, tránh hoàn toàn nhóm lỗi tương thích cửa sổ đã gặp.
- Đánh đổi: nặng CPU hơn (video phải copy qua RAM, không render thẳng GPU),
  nhưng ổn định — theo đúng tài liệu chính thức của libVLC, cách này "kém
  hiệu quả hơn nhúng cửa sổ native" nhưng luôn hoạt động độc lập với loại
  cửa sổ đích.
"""

import ctypes

from PySide6.QtWidgets import QFrame
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt, Signal

import vlc

# Kích thước khung hình nội bộ mà libVLC sẽ scale video về trước khi đưa
# vào buffer. Không cần khớp đúng độ phân giải thật của camera — libVLC tự
# scale (giống hệt việc phát rồi resize video trong 1 cửa sổ bất kỳ).
RENDER_WIDTH = 640
RENDER_HEIGHT = 360
_CHROMA = "RV32"  # 32-bit RGB, layout byte tương thích QImage.Format_RGB32


class StreamWidget(QFrame):
    _frame_ready = Signal()

    def __init__(self, rtsp_url: str, parent=None):
        super().__init__(parent)
        self.rtsp_url = rtsp_url
        self._qimage: QImage | None = None

        pitch = RENDER_WIDTH * 4
        self._pitch = pitch
        # buffer RAM dùng chung giữa lock_cb (ghi) và display_cb (đọc) —
        # libVLC tự đảm bảo gọi lock -> ghi -> unlock -> display tuần tự
        # trên cùng 1 luồng nội bộ cho mỗi frame nên không cần lock riêng.
        self._buf = (ctypes.c_ubyte * (pitch * RENDER_HEIGHT))()

        vlc_args = [
            "--no-xlib",
            "--rtsp-tcp",
            "--network-caching=800",
            "--avcodec-hw=none",  # tắt hardware decode, tránh lỗi D3D11VA deadlock
        ]
        self.instance = vlc.Instance(vlc_args)
        self.media_player = self.instance.media_player_new()

        # Giữ tham chiếu tới các callback (bắt buộc — nếu không giữ, ctypes
        # sẽ garbage-collect trampoline và libVLC gọi vào vùng nhớ đã giải
        # phóng, gây crash khó hiểu).
        self._c_lock = vlc.VideoLockCb(self._on_lock)
        self._c_unlock = vlc.VideoUnlockCb(self._on_unlock)
        self._c_display = vlc.VideoDisplayCb(self._on_display)

        self.media_player.video_set_format(_CHROMA, RENDER_WIDTH, RENDER_HEIGHT, pitch)
        self.media_player.video_set_callbacks(self._c_lock, self._c_unlock, self._c_display, None)

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

    def _on_lock(self, opaque, planes):
        planes[0] = ctypes.cast(self._buf, ctypes.c_void_p)
        return None

    def _on_unlock(self, opaque, picture, planes):
        return None

    def _on_display(self, opaque, picture):
        img = QImage(
            bytes(self._buf), RENDER_WIDTH, RENDER_HEIGHT, self._pitch,
            QImage.Format_RGB32,
        )
        self._qimage = img.copy()
        self._frame_ready.emit()

    # ---------- vẽ trên luồng chính Qt ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._qimage is not None:
            painter.drawImage(self.rect(), self._qimage)
        else:
            painter.fillRect(self.rect(), Qt.black)
