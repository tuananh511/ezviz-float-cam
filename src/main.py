"""
main.py — Sprint 2: Glass UI
Entry point: nạp config, dựng RTSP URL, mở cửa sổ kính mờ nổi (GlassWindow)
always-on-top, tự phát stream sau khi cửa sổ đã hiện ra.
"""

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from config_loader import load_config, build_rtsp_url
from glass_window import GlassWindow


def main():
    app = QApplication(sys.argv)

    config = load_config()
    rtsp_url = build_rtsp_url(config["rtsp"])
    print(f"[INFO] Đang kết nối tới: {rtsp_url}")

    window = GlassWindow(config, rtsp_url)
    window.show()

    # bắt đầu phát sau khi cửa sổ đã hiện ra (tránh lỗi bind window handle quá sớm)
    QTimer.singleShot(300, window.stream_widget.start)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
