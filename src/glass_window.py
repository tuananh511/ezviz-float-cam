"""
glass_window.py — Sprint 2: Glass UI (bản cuối)

Cửa sổ nổi: frameless, always-on-top, bo góc, nền translucent bán trong
suốt (không dùng acrylic blur thật — xem lý do trong showEvent()).

Video (StreamWidget) phủ kín sát viền cửa sổ (không có margin/viền kính
riêng — theo lựa chọn thiết kế cuối cùng, video edge-to-edge, 4 góc video bị
chính vùng mask bo tròn của cửa sổ cắt theo).

Cửa sổ tự khoá tỉ lệ khung hình theo đúng tỉ lệ thật của camera (báo qua
StreamWidget.native_size_ready) khi resize — để không bao giờ phải hiện viền
đen letterbox thừa.
"""

import sys

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPoint, QRect, QTimer
from PySide6.QtGui import QPainter, QColor, QCursor, QPainterPath, QRegion

from stream_widget import StreamWidget
from config_loader import save_config
from windows_blur import enable_acrylic_blur

MIN_WIDTH = 200
MIN_HEIGHT = 120
GRIP_SIZE = 18  # vùng tay cầm resize ở góc dưới-phải, tính bằng pixel
DOT_INSET = 14  # khoảng cách chấm trạng thái tới góc, tránh bị vùng bo góc cắt

# Đã THỬ và XÁC NHẬN: acrylic blur thật (SetWindowCompositionAttribute) được
# DWM vẽ trên toàn bộ hình chữ nhật của cửa sổ, KHÔNG tôn trọng vùng bo góc
# (setMask/window region) ở tầng Qt/USER32 — nên khi bật blur, 4 góc luôn
# hiện ra vuông dù mask đã đúng. Đây là giới hạn đã biết của API không chính
# thức này. Vì bo góc là yêu cầu quan trọng hơn, mặc định TẮT blur thật, chỉ
# dùng nền bán trong suốt do chính Qt vẽ (paintEvent) — tôn trọng bo góc
# hoàn hảo vì không có tầng DWM nào can thiệp.
ENABLE_ACRYLIC_BLUR = False


class _Overlay(QWidget):
    """
    Lớp phủ trong suốt nằm TRÊN CÙNG toàn bộ cửa sổ, dùng để bắt sự kiện
    chuột cho việc kéo-thả / resize ở bất kỳ đâu (kể cả trên vùng video),
    đồng thời vẽ chấm trạng thái kết nối + gợi ý tay cầm resize.
    """

    def __init__(self, glass_window: "GlassWindow"):
        super().__init__(glass_window)
        self.glass_window = glass_window
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self.glass_window.paint_status_dot(painter)
        self.glass_window.paint_resize_grip(painter)

    def mousePressEvent(self, event):
        self.glass_window.handle_mouse_press(event)

    def mouseMoveEvent(self, event):
        self.glass_window.handle_mouse_move(event)

    def mouseReleaseEvent(self, event):
        self.glass_window.handle_mouse_release(event)


class GlassWindow(QWidget):
    def __init__(self, config: dict, rtsp_url: str):
        super().__init__()
        self.config = config
        win_cfg = config.get("window", {})
        self.corner_radius = win_cfg.get("corner_radius", 16)
        self.opacity = win_cfg.get("opacity", 0.95)

        # Video phủ kín sát viền cửa sổ — không có margin riêng.
        self.video_margin = 0

        # Tỉ lệ khung hình thật của camera (width/height) — chưa biết cho
        # tới khi StreamWidget báo qua native_size_ready(). None = chưa biết,
        # cho phép resize tự do tạm thời.
        self._video_aspect: float | None = None
        self._had_saved_size = (
            win_cfg.get("width") is not None and win_cfg.get("height") is not None
        )

        self.setWindowTitle("EzvizFloatCam")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Window
        )

        w = win_cfg.get("width", 320)
        h = win_cfg.get("height", 200)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self.resize(w, h)
        self._restore_position(win_cfg)

        self.stream_widget = StreamWidget(rtsp_url, self)
        self.stream_widget.native_size_ready.connect(self._on_video_native_size)
        self.overlay = _Overlay(self)

        self._drag_pos: QPoint | None = None
        self._resizing = False
        self._resize_start_geo: QRect | None = None
        self._resize_start_mouse: QPoint | None = None

        self._blur_enabled = False
        # Chỉ True khi người dùng chọn "Thoát" ở menu khay hệ thống — xem
        # closeEvent()/request_quit() bên dưới.
        self._quitting = False

        self._layout_children()

        # cập nhật chấm trạng thái mỗi giây (dot xanh = đang phát, đỏ = chưa)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.overlay.update)
        self.status_timer.start(1000)

    # ---------- vị trí ban đầu ----------

    def _restore_position(self, win_cfg: dict):
        pos_x = win_cfg.get("pos_x")
        pos_y = win_cfg.get("pos_y")
        if pos_x is not None and pos_y is not None:
            self.move(int(pos_x), int(pos_y))
            return
        screen = self.screen() if hasattr(self, "screen") else None
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.right() - self.width() - 24, geo.top() + 24)

    # ---------- khoá tỉ lệ khung hình theo camera ----------

    def _on_video_native_size(self, w: int, h: int):
        if not w or not h:
            return
        self._video_aspect = w / h
        # Nếu cửa sổ chưa từng có kích thước người dùng tự lưu trước đó
        # (lần đầu chạy), tự động chỉnh cửa sổ về đúng tỉ lệ camera ngay khi
        # biết được — tránh phải hiện viền đen letterbox ngay từ đầu.
        if not self._had_saved_size:
            target_w = self.width()
            target_h = max(MIN_HEIGHT, int(round(target_w / self._video_aspect)))
            self.resize(target_w, target_h)

    # ---------- layout & hiển thị ----------

    def _layout_children(self):
        rect = self.rect()
        inner = rect.adjusted(
            self.video_margin, self.video_margin,
            -self.video_margin, -self.video_margin,
        )
        self.stream_widget.setGeometry(inner)
        self.overlay.setGeometry(rect)
        self.overlay.raise_()
        self._update_mask()

    def _update_mask(self):
        path = QPainterPath()
        path.addRoundedRect(
            0, 0, self.width(), self.height(),
            self.corner_radius, self.corner_radius,
        )
        region = QRegion(path.toFillPolygon().toPolygon())
        self.setMask(region)

    def resizeEvent(self, event):
        self._layout_children()
        super().resizeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if ENABLE_ACRYLIC_BLUR and not self._blur_enabled and sys.platform.startswith("win"):
            self._blur_enabled = enable_acrylic_blur(int(self.winId()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(
            0, 0, self.width(), self.height(),
            self.corner_radius, self.corner_radius,
        )

        if self._blur_enabled:
            bg_color = QColor(20, 20, 20, int(255 * 0.25))
        else:
            bg_color = QColor(24, 24, 28, int(255 * self.opacity))

        painter.fillPath(path, bg_color)

        border_color = QColor(255, 255, 255, 40)
        painter.setPen(border_color)
        painter.drawPath(path)

    def paint_status_dot(self, painter: QPainter):
        is_playing = self.stream_widget.is_playing()
        color = QColor(64, 200, 110) if is_playing else QColor(220, 70, 70)
        radius = 5
        cx = DOT_INSET
        cy = DOT_INSET
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPoint(cx, cy), radius, radius)

    def paint_resize_grip(self, painter: QPainter):
        grip_color = QColor(255, 255, 255, 90)
        painter.setPen(Qt.NoPen)
        painter.setBrush(grip_color)
        x0 = self.width() - GRIP_SIZE
        y0 = self.height() - GRIP_SIZE
        for i in range(3):
            offset = i * 5
            painter.drawEllipse(
                QPoint(x0 + GRIP_SIZE - 4 - offset, y0 + GRIP_SIZE - 4),
                2, 2,
            )
            painter.drawEllipse(
                QPoint(x0 + GRIP_SIZE - 4, y0 + GRIP_SIZE - 4 - offset),
                2, 2,
            )

    # ---------- kéo-thả & resize (nhận sự kiện từ overlay) ----------

    def _grip_rect(self) -> QRect:
        return QRect(
            self.width() - GRIP_SIZE, self.height() - GRIP_SIZE,
            GRIP_SIZE, GRIP_SIZE,
        )

    def handle_mouse_press(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()
        if self._grip_rect().contains(pos):
            self._resizing = True
            self._resize_start_geo = self.geometry()
            self._resize_start_mouse = event.globalPosition().toPoint()
        else:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def handle_mouse_move(self, event):
        global_pos = event.globalPosition().toPoint()

        if self._resizing and self._resize_start_geo is not None:
            delta = global_pos - self._resize_start_mouse
            new_w = max(MIN_WIDTH, self._resize_start_geo.width() + delta.x())
            if self._video_aspect:
                # Khoá tỉ lệ theo đúng camera — chỉ chiều rộng quyết định,
                # chiều cao tự tính theo, không bao giờ bị lệch tỉ lệ nữa.
                new_h = max(MIN_HEIGHT, int(round(new_w / self._video_aspect)))
            else:
                new_h = max(MIN_HEIGHT, self._resize_start_geo.height() + delta.y())
            self.resize(new_w, new_h)
            return

        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(global_pos - self._drag_pos)
            return

        pos = event.position().toPoint()
        if self._grip_rect().contains(pos):
            self.overlay.setCursor(QCursor(Qt.SizeFDiagCursor))
        else:
            self.overlay.setCursor(QCursor(Qt.ArrowCursor))

    def handle_mouse_release(self, event):
        was_active = self._drag_pos is not None or self._resizing
        self._drag_pos = None
        self._resizing = False
        self._resize_start_geo = None
        self._resize_start_mouse = None
        if was_active:
            self._had_saved_size = True
            self._save_geometry_to_config()

    def _save_geometry_to_config(self):
        geo = self.geometry()
        win_cfg = self.config.setdefault("window", {})
        win_cfg["pos_x"] = geo.x()
        win_cfg["pos_y"] = geo.y()
        win_cfg["width"] = geo.width()
        win_cfg["height"] = geo.height()
        save_config(self.config)

    def apply_new_rtsp(self, new_url: str):
        """Gọi từ tray sau khi người dùng lưu cài đặt kết nối mới
        (SettingsDialog, Sprint 4) — dừng stream cũ, đổi URL, phát lại."""
        self.stream_widget.stop()
        self.stream_widget.set_rtsp_url(new_url)
        QTimer.singleShot(300, self.stream_widget.start)

    def request_quit(self):
        """Gọi từ tray khi người dùng thật sự muốn thoát app (khác với đóng
        cửa sổ vô tình, ví dụ Alt+F4 — xem closeEvent())."""
        self._quitting = True
        self.close()

    def closeEvent(self, event):
        if not self._quitting:
            # Cửa sổ nổi không có nút đóng thật (frameless, không titlebar).
            # Nếu sự kiện đóng tới từ nơi khác ngoài tray (vd Alt+F4), chỉ ẩn
            # cửa sổ đi thay vì huỷ hẳn — tránh rơi vào trạng thái "mồ côi"
            # (tray vẫn sống nhưng cửa sổ đã bị huỷ, bấm "Hiện cửa sổ" sẽ lỗi).
            # Muốn thoát hẳn app, dùng menu khay hệ thống > Thoát.
            event.ignore()
            self.hide()
            return
        self.stream_widget.stop()
        self.status_timer.stop()
        self._save_geometry_to_config()
        event.accept()
