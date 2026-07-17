"""
tray.py — Sprint 3: System tray

Icon khay hệ thống + menu chuột phải:
  - Hiện/Ẩn cửa sổ
  - Bật/Tắt stream (play/pause)
  - Cài đặt... (placeholder, sẽ nối logic thật ở Sprint 4)
  - Thoát

Icon được vẽ động bằng QPainter (không cần file ảnh rời phải đóng gói theo
exe) — 1 vòng tròn glass đơn giản, đổi màu theo trạng thái stream (xanh khi
đang phát, xám khi dừng).
"""

from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction
from PySide6.QtCore import Qt, QTimer


def _make_icon(color: QColor) -> QIcon:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    margin = 4
    painter.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)
    painter.setBrush(QColor(255, 255, 255, 60))
    painter.drawEllipse(
        margin + 10, margin + 8,
        size - margin * 2 - 28, size - margin * 2 - 28,
    )
    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, app: QApplication):
        self._icon_on = _make_icon(QColor(64, 200, 110))
        self._icon_off = _make_icon(QColor(140, 140, 140))
        super().__init__(self._icon_off, app)
        self.window = window
        self.app = app
        self.setToolTip("EzvizFloatCam")

        self.menu = QMenu()

        self.action_toggle_show = QAction("Ẩn cửa sổ", self.menu)
        self.action_toggle_show.triggered.connect(self._toggle_window)
        self.menu.addAction(self.action_toggle_show)

        self.action_toggle_stream = QAction("Tắt stream", self.menu)
        self.action_toggle_stream.triggered.connect(self._toggle_stream)
        self.menu.addAction(self.action_toggle_stream)

        self.menu.addSeparator()

        # Sprint 4 sẽ mở dialog nhập IP/user/pass thật ở đây — tạm khoá.
        self.action_settings = QAction("Cài đặt... (sắp có ở Sprint 4)", self.menu)
        self.action_settings.setEnabled(False)
        self.menu.addAction(self.action_settings)

        self.menu.addSeparator()

        self.action_quit = QAction("Thoát", self.menu)
        self.action_quit.triggered.connect(self._quit)
        self.menu.addAction(self.action_quit)

        self.setContextMenu(self.menu)
        self.activated.connect(self._on_activated)

        # đồng bộ icon + label theo trạng thái thật (stream/cửa sổ) mỗi giây,
        # vì các thay đổi này có thể tới từ nơi khác (vd Alt+F4 ẩn cửa sổ,
        # hoặc stream tự rớt kết nối) chứ không chỉ từ chính menu khay.
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(1000)

        self.show()

    # ---------- hành động ----------

    def _toggle_window(self):
        if self.window.isVisible():
            self.window.hide()
        else:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
        self._refresh_status()

    def _toggle_stream(self):
        if self.window.stream_widget.is_playing():
            self.window.stream_widget.stop()
        else:
            self.window.stream_widget.start()
        self._refresh_status()

    def _quit(self):
        self._status_timer.stop()
        self.hide()  # ẩn icon khay ngay, tránh icon "ma" còn sót lại
        self.window.request_quit()
        self.app.quit()

    def _on_activated(self, reason):
        # click trái / double-click trên icon khay -> hiện/ẩn cửa sổ
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._toggle_window()

    # ---------- đồng bộ trạng thái ----------

    def _refresh_status(self):
        is_playing = self.window.stream_widget.is_playing()
        self.setIcon(self._icon_on if is_playing else self._icon_off)
        self.action_toggle_stream.setText("Tắt stream" if is_playing else "Bật stream")
        self.action_toggle_show.setText(
            "Ẩn cửa sổ" if self.window.isVisible() else "Hiện cửa sổ"
        )
