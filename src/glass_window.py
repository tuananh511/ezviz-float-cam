"""
glass_window.py — Sprint 2: Glass UI

Cửa sổ nổi kiểu "kính mờ":
- Frameless, always-on-top, bo góc, nền translucent.
- Trên Windows: bật acrylic blur thật (blur nội dung phía sau cửa sổ) qua
  windows_blur.py. Trên OS khác (dev/test): fallback vẽ nền màu bán trong
  suốt (không có blur thật, nhưng vẫn xem được layout/hành vi).
- Video (StreamWidget) được đặt lùi vào trong một khoảng margin nhỏ so với
  viền cửa sổ, để lộ ra viền "kính" xung quanh và đảm bảo 4 góc vuông của
  video native window luôn nằm trong vùng mask bo góc (không bị lòi góc).
- Kéo-thả: giữ chuột trái bất kỳ đâu trên cửa sổ (kể cả trên video, nhờ lớp
  overlay trong suốt phủ toàn bộ cửa sổ) để di chuyển.
- Resize: kéo tại tay cầm nhỏ ở góc dưới-phải.
- Vị trí & kích thước cửa sổ được lưu lại vào config khi người dùng thả
  chuột, để lần mở sau giữ nguyên chỗ cũ.
"""

import sys

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPoint, QRect, QSize, QTimer
from PySide6.QtGui import QPainter, QColor, QPainterPath, QRegion, QCursor

from stream_widget import StreamWidget
from config_loader import save_config
from windows_blur import enable_acrylic_blur

MIN_WIDTH = 200
MIN_HEIGHT = 130
GRIP_SIZE = 18  # vùng tay cầm resize ở góc dưới-phải, tính bằng pixel

# Xem giải thích chi tiết trong showEvent(): acrylic blur thật phá vỡ bo góc
# vì DWM vẽ blur trên toàn bộ hình chữ nhật cửa sổ, bỏ qua window region.
# Mặc định TẮT để ưu tiên bo góc hoạt động đúng.
ENABLE_ACRYLIC_BLUR = False


class _Overlay(QWidget):
    """
    Lớp phủ trong suốt nằm TRÊN CÙNG toàn bộ cửa sổ, dùng để bắt sự kiện
    chuột cho việc kéo-thả / resize ở bất kỳ đâu (kể cả trên vùng video),
    đồng thời vẽ chấm trạng thái kết nối + gợi ý tay cầm resize.

    (Ghi chú: từ bản fix video callback của StreamWidget, video không còn là
    native child window nữa nên về mặt kỹ thuật overlay không còn bắt buộc
    để tránh việc native window "nuốt" sự kiện chuột như trước — nhưng vẫn
    giữ lại vì đơn giản hoá logic vẽ status dot/resize-grip ở một chỗ duy
    nhất, tách biệt khỏi StreamWidget.)
    """

    def __init__(self, glass_window: "GlassWindow"):
        super().__init__(glass_window)
        self.glass_window = glass_window
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        # Overlay trong suốt hoàn toàn, không vẽ gì — chỉ để nhận sự kiện chuột.
        # Có thể vẽ chấm trạng thái kết nối ở góc trên-trái tại đây.
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
        # margin phải >= corner_radius để góc vuông của video không lòi ra
        # ngoài vùng mask bo tròn của cửa sổ.
        self.video_margin = max(8, self.corner_radius)

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
        self.overlay = _Overlay(self)

        self._drag_pos: QPoint | None = None
        self._resizing = False
        self._resize_start_geo: QRect | None = None
        self._resize_start_mouse: QPoint | None = None

        self._blur_enabled = False

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
        # Mặc định: góc trên-phải màn hình, cách mép 24px.
        screen = self.screen() if hasattr(self, "screen") else None
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.right() - self.width() - 24, geo.top() + 24)

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
        # Đã THỬ và XÁC NHẬN: acrylic blur thật (SetWindowCompositionAttribute)
        # được DWM vẽ trên toàn bộ hình chữ nhật của cửa sổ, KHÔNG tôn trọng
        # vùng bo góc (setMask/window region) ở tầng Qt/USER32 — nên khi bật
        # blur, 4 góc luôn hiện ra vuông dù mask đã đúng. Đây là giới hạn đã
        # biết của API không chính thức này (không có cách chính thức nào để
        # "blur đúng theo custom region" trên Windows 10 hiện tại). Vì bo góc
        # là yêu cầu quan trọng hơn, mình ưu tiên TẮT blur thật, chỉ dùng nền
        # bán trong suốt do chính Qt vẽ trong paintEvent() — cách này tôn
        # trọng bo góc hoàn hảo vì không có tầng DWM nào can thiệp.
        #
        # Nếu sau này muốn thử lại blur thật (chấp nhận đánh đổi góc vuông),
        # đổi ENABLE_ACRYLIC_BLUR ở đầu file thành True.
        if ENABLE_ACRYLIC_BLUR and not self._blur_enabled and sys.platform.startswith("win"):
            self._blur_enabled = enable_acrylic_blur(int(self.winId()))

    def paintEvent(self, event):
        # Vẽ nền "kính": nếu acrylic blur (Windows) đã bật, chỉ cần phủ 1 lớp
        # màu rất mỏng để giữ viền rõ; nếu không (fallback OS khác / blur lỗi),
        # vẽ nền bán trong suốt đậm hơn để vẫn nhìn được layout.
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
        cx = self.video_margin + radius + 4
        cy = self.video_margin + radius + 4
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPoint(cx, cy), radius, radius)

    def paint_resize_grip(self, painter: QPainter):
        grip_color = QColor(255, 255, 255, 90)
        painter.setPen(Qt.NoPen)
        painter.setBrush(grip_color)
        x0 = self.width() - GRIP_SIZE
        y0 = self.height() - GRIP_SIZE
        # 3 chấm nhỏ chéo góc để gợi ý có thể kéo resize ở đây
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
            new_h = max(MIN_HEIGHT, self._resize_start_geo.height() + delta.y())
            self.resize(new_w, new_h)
            return

        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(global_pos - self._drag_pos)
            return

        # cập nhật con trỏ chuột khi rê qua tay cầm resize
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
            self._save_geometry_to_config()

    def _save_geometry_to_config(self):
        geo = self.geometry()
        win_cfg = self.config.setdefault("window", {})
        win_cfg["pos_x"] = geo.x()
        win_cfg["pos_y"] = geo.y()
        win_cfg["width"] = geo.width()
        win_cfg["height"] = geo.height()
        save_config(self.config)

    def closeEvent(self, event):
        self.stream_widget.stop()
        self.status_timer.stop()
        self._save_geometry_to_config()
        event.accept()
