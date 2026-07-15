"""
main.py — Sprint 1: Core RTSP viewer
Mục tiêu: verify camera Ezviz C6N sống qua RTSP, hiển thị trong cửa sổ Qt bình thường.
Chưa làm giao diện đẹp (bo góc, glass, always-on-top) — để dành Sprint 2.
"""

import sys
from PySide6.QtWidgets import QMainWindow, QApplication, QVBoxLayout, QWidget, QLabel
from PySide6.QtCore import QTimer

from config_loader import load_config, build_rtsp_url
from stream_widget import StreamWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EzvizFloatCam — Sprint 1 (test viewer)")

        config = load_config()
        rtsp_url = build_rtsp_url(config["rtsp"])
        print(f"[INFO] Đang kết nối tới: {rtsp_url}")

        self.status_label = QLabel("Đang kết nối...")
        self.stream_widget = StreamWidget(rtsp_url)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.status_label)
        layout.addWidget(self.stream_widget)
        self.setCentralWidget(central)

        w, h = config["window"]["width"], config["window"]["height"]
        self.resize(w, h + 30)  # +30 cho label trạng thái

        # bắt đầu phát sau khi cửa sổ đã hiện ra (tránh lỗi bind window handle quá sớm)
        QTimer.singleShot(300, self.stream_widget.start)

        # kiểm tra trạng thái mỗi giây để cập nhật label
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)

    def _update_status(self):
        if self.stream_widget.is_playing():
            self.status_label.setText("✅ Đang phát stream")
        else:
            self.status_label.setText("⏳ Đang chờ kết nối / kiểm tra lại RTSP URL, user, pass...")

    def closeEvent(self, event):
        self.stream_widget.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
