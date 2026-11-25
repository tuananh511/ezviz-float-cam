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
import time

from PySide6.QtWidgets import (
    QWidget, QMessageBox, QDialog, QVBoxLayout, QLabel, QPushButton,
)
from PySide6.QtCore import Qt, QPoint, QRect, QTimer, QVariantAnimation, QEasingCurve
from PySide6.QtGui import (
    QPainter, QColor, QPen, QCursor, QPainterPath, QRegion, QPolygon, QFont,
    QFontMetrics, QLinearGradient,
)

from stream_widget import StreamWidget
from recorder import EmergencyRecorder
from recording import KIND_AUTO
from motion import get_motion_config
from motion_controller import MotionRecordingController
from cleanup_controller import RecordingCleanupController
from config_loader import save_config
from windows_blur import enable_acrylic_blur
from version import APP_NAME, APP_VERSION, GITHUB_URL, LICENSE_NAME

MIN_WIDTH = 200
MIN_HEIGHT = 120
GRIP_SIZE = 18  # vùng tay cầm resize ở góc dưới-phải, tính bằng pixel
DOT_INSET = 14  # khoảng cách chấm trạng thái tới góc, tránh bị vùng bo góc cắt

# Sprint 5.5: 2 icon hành động (ghi hình khẩn cấp + mute) đặt góc trên-phải,
# vẽ động bằng QPainter (không cần file ảnh rời), giống tinh thần icon tray.
ICON_SIZE = 20
ICON_MARGIN = 10
ICON_GAP = 6

# Sprint 5.6: icon "Giới thiệu" (About) — đặt góc dưới-trái để không chồng
# lấn với chấm trạng thái (trên-trái), 2 icon mute/ghi hình (trên-phải) hay
# tay cầm resize (dưới-phải).
ABOUT_ICON_SIZE = 18
ABOUT_ICON_MARGIN = 10

# Điều khiển (icon REC / mute / "i", tay cầm resize) chỉ hiện khi rê chuột vào
# cửa sổ, mờ dần khi chuột rời đi — kiểu thanh điều khiển của QuickTime/Apple TV.
# Chấm trạng thái, "REC mm:ss" khi đang ghi, huy hiệu AUTO REC và viền cam LUÔN
# hiện vì là thông tin trạng thái, không phải nút bấm.
HOVER_POLL_MS = 80       # tần suất kiểm tra chuột có nằm trong cửa sổ không
FADE_IN_MS = 140
FADE_OUT_MS = 320
SCRIM_HEIGHT = 46        # dải tối mờ phía trên/dưới giúp icon dễ đọc trên nền sáng

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
        self.glass_window.paint_scrim(painter)
        self.glass_window.paint_status_dot(painter)
        self.glass_window.paint_resize_grip(painter)
        self.glass_window.paint_action_icons(painter)
        self.glass_window.paint_about_icon(painter)
        self.glass_window.paint_auto_record(painter)

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

        # Sprint 5.5: ghi hình khẩn cấp — phiên libVLC RIÊNG, luôn dùng luồng
        # main chất lượng cao, độc lập hoàn toàn với stream_widget đang xem.
        self.recorder = EmergencyRecorder(self)
        self.recorder.recording_started.connect(self._on_recording_started)
        self.recorder.recording_stopped.connect(self._on_recording_stopped)
        self.recorder.recording_error.connect(self._on_recording_error)

        # Ghi hình TỰ ĐỘNG khi có chuyển động — recorder RIÊNG, độc lập hoàn
        # toàn với self.recorder (nút REC thủ công): hai bên có phiên libVLC
        # và thư mục phiên riêng (..._TuDong vs ..._ThuCong)
        # nên bật/tắt cái này không ảnh hưởng cái kia.
        motion_cfg = get_motion_config(config)
        self.auto_recorder = EmergencyRecorder(
            self,
            kind=KIND_AUTO,
            stream_type=motion_cfg["stream_type"],
        )
        self.auto_recorder.recording_started.connect(lambda _p: self.overlay.update())
        self.auto_recorder.recording_stopped.connect(lambda _p: self.overlay.update())
        self.auto_recorder.recording_error.connect(self._on_auto_recording_error)
        self.motion = MotionRecordingController(
            self.stream_widget, self.auto_recorder, lambda: self.config, self,
        )
        self.motion.state_changed.connect(self.overlay.update)
        self.motion.start()

        # Tự xoá bản ghi TỰ ĐỘNG cũ khi thư mục ghi hình vượt ngưỡng (Cài đặt).
        # Phiên đang ghi (cả tay lẫn tự động) luôn được loại khỏi việc xoá.
        self.cleanup = RecordingCleanupController(
            lambda: self.config,
            lambda: [
                d for d in (
                    self.recorder.active_session_dir(),
                    self.auto_recorder.active_session_dir(),
                ) if d is not None
            ],
            self,
        )
        self.auto_recorder.recording_stopped.connect(lambda _p: self.cleanup.run_now())
        self.cleanup.start()

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
        self.status_timer.start(500)  # 500ms để huy hiệu AUTO REC nhấp nháy mượt

        # Điều khiển chỉ hiện khi chuột ở trong cửa sổ. Dùng kiểm tra vị trí
        # chuột theo chu kỳ thay vì enter/leaveEvent vì cửa sổ có nhiều widget
        # con chồng nhau (video + lớp phủ) — cách này không bị lệch sự kiện.
        self._controls_opacity = 0.0
        self._controls_target = 0.0
        self._controls_anim = QVariantAnimation(self)
        self._controls_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._controls_anim.valueChanged.connect(self._on_controls_anim)
        self._hover_timer = QTimer(self)
        self._hover_timer.timeout.connect(self._poll_hover)
        self._hover_timer.start(HOVER_POLL_MS)

    # ---------- điều khiển hiện khi rê chuột ----------

    def _poll_hover(self):
        if not self.isVisible():
            return
        inside = (
            self._resizing
            or self._drag_pos is not None
            or self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        )
        self._set_controls_target(1.0 if inside else 0.0)

    def _set_controls_target(self, target: float):
        if target == self._controls_target:
            return
        self._controls_target = target
        self._controls_anim.stop()
        self._controls_anim.setDuration(FADE_IN_MS if target > self._controls_opacity else FADE_OUT_MS)
        self._controls_anim.setStartValue(self._controls_opacity)
        self._controls_anim.setEndValue(target)
        self._controls_anim.start()

    def _on_controls_anim(self, value):
        self._controls_opacity = float(value)
        self.overlay.update()

    def _controls_clickable(self) -> bool:
        """Nút chỉ nhận click khi đã hiện rõ — tránh bấm nhầm vào nút còn vô
        hình ngay khoảnh khắc chuột vừa vào cửa sổ."""
        return self._controls_opacity >= 0.5

    def paint_scrim(self, painter: QPainter):
        """Dải tối mờ ở mép trên/dưới (đậm dần khi điều khiển hiện) để icon
        trắng không bị chìm trên nền video sáng."""
        op = self._controls_opacity
        if op < 0.01:
            return
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(),
                            self.corner_radius, self.corner_radius)
        painter.save()
        painter.setClipPath(path)
        painter.setPen(Qt.NoPen)
        for top in (True, False):
            y0 = 0 if top else self.height() - SCRIM_HEIGHT
            grad = QLinearGradient(0, y0, 0, y0 + SCRIM_HEIGHT)
            near, far = (QColor(0, 0, 0, int(120 * op)), QColor(0, 0, 0, 0))
            grad.setColorAt(0.0, near if top else far)
            grad.setColorAt(1.0, far if top else near)
            painter.setBrush(grad)
            painter.drawRect(0, y0, self.width(), SCRIM_HEIGHT)
        painter.restore()

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
        # Sprint 5.6: 3 màu thay vì chỉ xanh/đỏ — vàng cam khi đang kết nối
        # lần đầu hoặc đang tự thử kết nối lại, để phân biệt với "mất hẳn tín
        # hiệu" (đỏ) và "đang xem bình thường" (xanh).
        state = self.stream_widget.get_connection_state()
        if state == "connected":
            color = QColor(64, 200, 110)
        elif state in ("connecting", "reconnecting"):
            color = QColor(230, 170, 40)
        else:  # "no_signal" hoặc "stopped"
            color = QColor(220, 70, 70)
        radius = 5
        cx = DOT_INSET
        cy = DOT_INSET
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPoint(cx, cy), radius, radius)

    def paint_resize_grip(self, painter: QPainter):
        if self._controls_opacity < 0.01:
            return
        grip_color = QColor(255, 255, 255, int(90 * self._controls_opacity))
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

    # ---------- huy hiệu ghi hình TỰ ĐỘNG theo chuyển động ----------

    def paint_auto_record(self, painter: QPainter):
        """Hiển thị trên hình khi đang ghi tự động: viền cam quanh khung +
        huy hiệu "AUTO REC mm:ss" (chấm nhấp nháy) góc dưới-trái, cạnh icon
        "i". Màu cam để phân biệt với REC thủ công (đỏ, góc trên-phải). Nếu
        ghi tự động vừa gặp lỗi (đầy đĩa...), hiện "AUTO REC LỖI" ~15 giây."""
        recording = self.motion.is_recording()
        error_active = (
            not recording
            and self.motion.last_error is not None
            and time.monotonic() - self.motion.last_error_at < 15.0
        )
        if not recording and not error_active:
            return

        orange = QColor(255, 140, 0)
        if recording:
            path = QPainterPath()
            path.addRoundedRect(
                1, 1, self.width() - 2, self.height() - 2,
                self.corner_radius, self.corner_radius,
            )
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 140, 0, 200), 2))
            painter.drawPath(path)

        blink_on = int(time.time() * 2) % 2 == 0
        if recording:
            mm, ss = divmod(self.motion.elapsed_seconds(), 60)
            text = f"AUTO REC {mm:02d}:{ss:02d}"
            dot_color = orange if blink_on else QColor(255, 140, 0, 80)
        else:
            text = "AUTO REC LỖI"
            dot_color = QColor(220, 70, 70)

        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(8)
        painter.setFont(font)
        text_w = QFontMetrics(font).horizontalAdvance(text)

        height = 18
        # Dịch sang trái khi icon "i" đang ẩn, để không chừa khoảng trống.
        x = ABOUT_ICON_MARGIN + round((ABOUT_ICON_SIZE + 6) * self._controls_opacity)
        y = self.height() - ABOUT_ICON_MARGIN - height
        pill = QRect(x, y, 14 + text_w + 10, height)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 140))
        painter.drawRoundedRect(pill, height / 2, height / 2)

        painter.setBrush(dot_color)
        painter.drawEllipse(QPoint(pill.left() + 9, pill.center().y()), 4, 4)

        painter.setPen(QColor(255, 255, 255, 235))
        painter.drawText(
            QRect(pill.left() + 17, pill.top(), pill.width() - 17, pill.height()),
            Qt.AlignLeft | Qt.AlignVCenter, text,
        )

    def _on_auto_recording_error(self, message: str):
        # KHÔNG hiện hộp thoại modal như ghi tay: ghi tự động chạy ngầm, một
        # hộp thoại bật lên giữa chừng sẽ rất phiền. Lỗi đã được in ra console
        # và huy hiệu "AUTO REC LỖI" báo trên hình.
        print(f"[WARN] Ghi tự động: {message}")
        self.motion.last_error = message.splitlines()[0] if message else "lỗi"
        self.motion.last_error_at = time.monotonic()
        self.overlay.update()

    def set_motion_enabled(self, enabled: bool):
        """Bật/tắt ghi tự động (từ menu khay), lưu vào config."""
        motion_cfg = self.config.setdefault("motion", {})
        motion_cfg["enabled"] = bool(enabled)
        save_config(self.config)
        self.apply_motion_config()

    def apply_retention_config(self):
        """Áp dụng ngưỡng dung lượng mới (sau khi lưu Cài đặt) — dọn ngay."""
        self.cleanup.run_now()

    def apply_motion_config(self):
        """Áp dụng lại cấu hình chuyển động hiện có trong self.config."""
        self.motion.apply_config()
        self.overlay.update()

    # ---------- icon hành động: ghi hình khẩn cấp + mute (Sprint 5.5) ----------

    def _record_rect(self) -> QRect:
        # icon bên trái trong cặp 2 icon, góc trên-phải
        x = self.width() - ICON_MARGIN - ICON_SIZE * 2 - ICON_GAP
        return QRect(x, ICON_MARGIN, ICON_SIZE, ICON_SIZE)

    def _mute_rect(self) -> QRect:
        # icon bên phải trong cặp 2 icon, góc trên-phải
        x = self.width() - ICON_MARGIN - ICON_SIZE
        return QRect(x, ICON_MARGIN, ICON_SIZE, ICON_SIZE)

    def paint_action_icons(self, painter: QPainter):
        op = self._controls_opacity
        recording = self.recorder.is_recording()
        muted = self.stream_widget.is_muted()
        # Đang ghi / đang tắt tiếng là THÔNG TIN trạng thái nên nút giữ nguyên
        # hiện; ở trạng thái bình thường thì chỉ hiện khi rê chuột.
        self._draw_record_icon(painter, self._record_rect(), 1.0 if recording else op)
        self._draw_mute_icon(painter, self._mute_rect(), max(op, 0.9) if muted else op)

    def _draw_record_icon(self, painter: QPainter, rect: QRect, opacity: float = 1.0):
        recording = self.recorder.is_recording()

        if opacity > 0.01:
            painter.save()
            painter.setOpacity(opacity)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 110))
            painter.drawEllipse(rect)

            dot_color = QColor(220, 40, 40) if recording else QColor(255, 255, 255, 210)
            painter.setBrush(dot_color)
            inset = 5
            painter.drawEllipse(rect.adjusted(inset, inset, -inset, -inset))
            painter.restore()

        if recording:
            elapsed = self.recorder.elapsed_seconds()
            mm, ss = divmod(elapsed, 60)
            text = f"REC {mm:02d}:{ss:02d}"
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255, 235))
            text_rect = QRect(rect.left() - 92, rect.top(), 86, rect.height())
            painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, text)

    def _draw_mute_icon(self, painter: QPainter, rect: QRect, opacity: float = 1.0):
        if opacity <= 0.01:
            return
        painter.save()
        try:
            self._draw_mute_icon_body(painter, rect, opacity)
        finally:
            painter.restore()

    def _draw_mute_icon_body(self, painter: QPainter, rect: QRect, opacity: float):
        muted = self.stream_widget.is_muted()
        painter.setOpacity(opacity)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 110))
        painter.drawEllipse(rect)

        color = QColor(220, 70, 70) if muted else QColor(255, 255, 255, 220)
        cx, cy = rect.center().x(), rect.center().y()

        # hình loa đơn giản: 1 hình vuông nhỏ nối 1 tam giác (không cần ảnh)
        painter.setBrush(color)
        painter.drawRect(cx - 6, cy - 3, 4, 6)
        triangle = QPolygon([
            QPoint(cx - 2, cy - 3), QPoint(cx - 2, cy + 3),
            QPoint(cx + 4, cy + 7), QPoint(cx + 4, cy - 7),
        ])
        painter.drawPolygon(triangle)

        if muted:
            pen = QPen(QColor(220, 70, 70), 2)
            painter.setPen(pen)
            painter.drawLine(rect.left() + 3, rect.top() + 3, rect.right() - 3, rect.bottom() - 3)

    # ---------- icon "Giới thiệu" / About (Sprint 5.6) ----------

    def _about_rect(self) -> QRect:
        return QRect(
            ABOUT_ICON_MARGIN, self.height() - ABOUT_ICON_MARGIN - ABOUT_ICON_SIZE,
            ABOUT_ICON_SIZE, ABOUT_ICON_SIZE,
        )

    def paint_about_icon(self, painter: QPainter):
        if self._controls_opacity < 0.01:
            return
        painter.save()
        painter.setOpacity(self._controls_opacity)
        self._paint_about_icon_body(painter)
        painter.restore()

    def _paint_about_icon_body(self, painter: QPainter):
        rect = self._about_rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 110))
        painter.drawEllipse(rect)

        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 220))
        painter.drawText(rect, Qt.AlignCenter, "i")

    def show_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Giới thiệu")
        dialog.setModal(True)
        dialog.setFixedWidth(320)

        layout = QVBoxLayout(dialog)

        title = QLabel(f"{APP_NAME}")
        title_font = QFont(title.font())
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        version_label = QLabel(f"Phiên bản {APP_VERSION}")
        layout.addWidget(version_label)

        desc_label = QLabel(
            "Cửa sổ nổi hiển thị camera Ezviz qua RTSP — nhẹ, luôn nổi trên "
            "cùng, giao diện kính mờ."
        )
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        github_label = QLabel(f'<a href="{GITHUB_URL}">{GITHUB_URL}</a>')
        github_label.setOpenExternalLinks(True)
        github_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(github_label)

        license_label = QLabel(f"Giấy phép: {LICENSE_NAME} — mã nguồn mở")
        layout.addWidget(license_label)

        close_button = QPushButton("Đóng")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        dialog.exec()

    def toggle_mute(self):
        muted = not self.stream_widget.is_muted()
        self.stream_widget.set_muted(muted)
        audio_cfg = self.config.setdefault("audio", {})
        audio_cfg["muted"] = muted
        save_config(self.config)
        self.overlay.update()

    def toggle_recording(self):
        if self.recorder.is_recording():
            self.recorder.stop()
        else:
            rtsp_cfg = self.config.get("rtsp", {})
            save_dir = self.config.get("recording", {}).get("save_dir", "")
            self.recorder.start(rtsp_cfg, save_dir)

    def _on_recording_started(self, path: str):
        self.overlay.update()

    def _on_recording_stopped(self, path: str):
        self.overlay.update()

    def _on_recording_error(self, message: str):
        self.overlay.update()
        QMessageBox.warning(self, "Ghi hình khẩn cấp", message)

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
        # icon hành động có ưu tiên cao nhất — bấm trúng icon thì KHÔNG bắt
        # đầu kéo-thả cửa sổ (2 icon nằm ở vùng góc trên-phải, không chồng
        # lấn với tay cầm resize ở góc dưới-phải nên không xung đột logic).
        clickable = self._controls_clickable()
        if self._record_rect().contains(pos) and (clickable or self.recorder.is_recording()):
            self.toggle_recording()
            return
        if self._mute_rect().contains(pos) and (clickable or self.stream_widget.is_muted()):
            self.toggle_mute()
            return
        if self._about_rect().contains(pos) and clickable:
            self.show_about_dialog()
            return
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
        QTimer.singleShot(300, self._start_stream_and_restore_audio)

    def start_stream(self):
        """Gọi từ main.py lúc khởi động app lần đầu — phát stream và áp
        dụng lại trạng thái mute đã lưu từ lần trước (Sprint 5.5)."""
        self._start_stream_and_restore_audio()

    def _start_stream_and_restore_audio(self):
        self.stream_widget.start()
        audio_cfg = self.config.get("audio", {})
        self.stream_widget.set_muted(bool(audio_cfg.get("muted", False)))

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
        # Dừng ghi tự động (nếu đang chạy) trước, rồi mới tới ghi tay.
        self.motion.shutdown()
        self.cleanup.shutdown()
        self._hover_timer.stop()
        if self.recorder.is_recording():
            # Dừng ghi hình đúng cách trước khi thoát hẳn. File .mkv chống
            # chịu tốt hơn .mp4 khi bị ngắt đột ngột (xem giải thích trong
            # recorder.py), nhưng dừng đúng quy trình ở đây vẫn đảm bảo file
            # được đóng gói (finalize) hoàn chỉnh nhất, không mất giây cuối.
            self.recorder.stop()
        self.stream_widget.stop()
        self.status_timer.stop()
        self._save_geometry_to_config()
        event.accept()
