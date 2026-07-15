"""
stream_widget.py
Widget Qt nhúng video RTSP qua libVLC.
Sprint 1: chỉ cần hiển thị được stream, chưa quan tâm giao diện đẹp.
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
            "--rtsp-tcp",          # ép dùng TCP cho RTSP, ổn định hơn UDP qua NAT/wifi yếu
            "--network-caching=300",  # buffer thấp để giảm delay (ms)
        ]
        self.instance = vlc.Instance(vlc_args)
        self.media_player = self.instance.media_player_new()

        self.setMinimumSize(320, 200)
        self.setStyleSheet("background-color: black;")

    def start(self):
        media = self.instance.media_new(self.rtsp_url)
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
