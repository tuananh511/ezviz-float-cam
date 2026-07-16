"""
stream_widget.py
Widget Qt nhúng video RTSP qua libVLC.

Sprint 2: đổi video output sang wingdi (GDI) vì Direct3D11 vout mặc định
không tương thích với cửa sổ frameless/translucent của Glass UI — gây màn
hình đen (có tiếng, không hình) do "buffer deadlock" ở decoder D3D11VA.
"""

import sys
import vlc
from PySide6.QtWidgets import QFrame
from PySide6.QtCore import Qt


class StreamWidget(QFrame):
    def __init__(self, rtsp_url: str, parent=None):
        super().__init__(parent)
        self.rtsp_url = rtsp_url

        # Khởi tạo VLC instance với tham số giảm độ trễ cho RTSP
        vlc_args = [
            "--no-xlib",
            "--rtsp-tcp",
            "--network-caching=800",   # tăng buffer để giảm giật khi CPU decode nặng hơn GPU
            "--avcodec-hw=none",       # tắt hardware decode (D3D11VA) — bắt buộc phải tắt khi nhúng
                                        # video vào cửa sổ frameless/translucent (Sprint 2 Glass UI),
                                        # nếu không sẽ bị "buffer deadlock prevented" + màn hình đen
            "--vout=wingdi",           # ép dùng GDI video output thay vì Direct3D11 mặc định.
                                        # Direct3D11 vout không tương thích tốt với cửa sổ layered/
                                        # translucent (WS_EX_LAYERED) → gây màn hình đen dù có tiếng.
                                        # wingdi nặng CPU hơn nhưng ổn định, đủ dùng cho cửa sổ nhỏ.
        ]
        self.instance = vlc.Instance(vlc_args)
        self.media_player = self.instance.media_player_new()

        self.setMinimumSize(320, 200)
        self.setStyleSheet("background-color: black;")

    def start(self):
        media = self.instance.media_new(self.rtsp_url)
        # Đặt lại lần nữa ở cấp media (phòng trường hợp option cấp instance
        # không được decoder áp dụng đúng lúc mở stream RTSP).
        media.add_option(":avcodec-hw=none")
        self.media_player.set_media(media)
        self._bind_output_window()
        self.media_player.play()

    def stop(self):
        self.media_player.stop()

    def _bind_output_window(self):
        """Gắn output video của VLC vào đúng widget này theo từng OS."""
        win_id = int(self.winId())
        if sys.platform.startswith("win"):
            self.media_player.set_hwnd(win_id)
        elif sys.platform.startswith("linux"):
            self.media_player.set_xwindow(win_id)
        elif sys.platform == "darwin":
            self.media_player.set_nsobject(win_id)

    def is_playing(self) -> bool:
        return bool(self.media_player.is_playing())
