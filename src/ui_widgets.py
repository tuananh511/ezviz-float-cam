"""
ui_widgets.py — vài widget Qt tự vẽ cho giao diện Cài đặt kiểu hiện đại
(công tắc gạt + thanh chọn dạng "segmented"), không cần thư viện hay file ảnh
ngoài — chỉ QPainter, nên nhẹ như các widget mặc định.

API cố ý giống widget chuẩn để thay thế trực tiếp:
  - ToggleSwitch      ~ QCheckBox      (isChecked/setChecked/toggled)
  - SegmentedControl  ~ QComboBox      (currentData/setCurrentData/currentIndex,
                                        tín hiệu currentChanged(int))
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

__all__ = ["ToggleSwitch", "SegmentedControl", "ACCENT", "GREEN"]

ACCENT = QColor("#0a84ff")   # xanh Apple (nút chính, viền focus)
GREEN = QColor("#30d158")    # xanh lá Apple (công tắc bật)
_OFF = QColor("#4a4a4d")


def _is_keyboard_focus(reason) -> bool:
    return reason in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class ToggleSwitch(QAbstractButton):
    """Công tắc gạt kiểu iOS. Dùng như QCheckBox: setChecked/isChecked/toggled."""

    _W, _H = 44, 26

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)  # chỉ hiện viền focus khi dùng phím Tab
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._t = 1.0 if self.isChecked() else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate_to)
        self._focus_ring = False

    def sizeHint(self) -> QSize:
        return QSize(self._W, self._H)

    def focusInEvent(self, event):
        # Chỉ hiện viền focus khi người dùng tới bằng phím Tab — không hiện khi
        # focus tự nhảy sang (vd lúc đổi tab trong hộp Cài đặt) hay khi bấm chuột.
        self._focus_ring = _is_keyboard_focus(event.reason())
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        self._focus_ring = False
        super().focusOutEvent(event)
        self.update()

    def _on_anim(self, value):
        self._t = float(value)
        self.update()

    def _animate_to(self, checked: bool):
        target = 1.0 if checked else 0.0
        self._anim.stop()
        if not self.isVisible():
            self._t = target
            self.update()
            return
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        track = _mix(_OFF, GREEN, self._t)
        if not self.isEnabled():
            track.setAlphaF(0.4)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)

        d = h - 4
        x = 2 + self._t * (w - d - 4)
        p.setBrush(QColor(0, 0, 0, 55))                       # bóng nhẹ dưới núm
        p.drawEllipse(QRectF(x, 2 + 1, d, d))
        p.setBrush(QColor(255, 255, 255, 255 if self.isEnabled() else 160))
        p.drawEllipse(QRectF(x, 2, d, d))

        if self._focus_ring:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(ACCENT, 2))
            p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), (h - 2) / 2, (h - 2) / 2)


class SegmentedControl(QWidget):
    """Thanh chọn một trong vài mục, kiểu "segmented control" của Apple.

    items: danh sách (nhãn, dữ liệu). stretch=True thì các mục chia đều cả
    chiều rộng widget (dùng cho thanh tab); False thì vừa khít chữ (dùng
    trong một hàng cài đặt).
    """

    currentChanged = Signal(int)

    _HEIGHT = 30
    _PAD = 16

    def __init__(self, items, parent: QWidget | None = None, *, stretch: bool = False,
                 track: str = "#1c1c1e", pill: str = "#636366"):
        super().__init__(parent)
        self._items = [(str(label), data) for label, data in items]
        if not self._items:
            raise ValueError("SegmentedControl cần ít nhất 1 mục")
        self._stretch = stretch
        self._track = QColor(track)
        self._pill = QColor(pill)
        self._index = 0
        self._pill_x = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setFixedHeight(self._HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Expanding if stretch else QSizePolicy.Fixed, QSizePolicy.Fixed,
        )
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._focus_ring = False

    def focusInEvent(self, event):
        self._focus_ring = _is_keyboard_focus(event.reason())
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        self._focus_ring = False
        super().focusOutEvent(event)
        self.update()

    # ---------- API giống QComboBox ----------

    def count(self) -> int:
        return len(self._items)

    def currentIndex(self) -> int:
        return self._index

    def currentData(self):
        return self._items[self._index][1]

    def itemText(self, index: int) -> str:
        return self._items[index][0]

    def findData(self, data) -> int:
        for i, (_label, d) in enumerate(self._items):
            if d == data:
                return i
        return -1

    def setCurrentData(self, data):
        i = self.findData(data)
        if i >= 0:
            self.setCurrentIndex(i)

    def setCurrentIndex(self, index: int):
        if not (0 <= index < len(self._items)) or index == self._index:
            return
        self._index = index
        self._move_pill()
        self.currentChanged.emit(index)
        self.update()

    # ---------- hình học ----------

    def _seg_width(self) -> float:
        if self._stretch:
            return self.width() / len(self._items)
        fm = self.fontMetrics()
        return max(fm.horizontalAdvance(label) for label, _ in self._items) + 2 * self._PAD

    def sizeHint(self) -> QSize:
        return QSize(int(self._seg_width() * len(self._items)) + 4, self._HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint() if not self._stretch else QSize(60 * len(self._items), self._HEIGHT)

    def _target_pill_x(self) -> float:
        return 2 + self._index * self._inner_seg_width()

    def _inner_seg_width(self) -> float:
        return (self.width() - 4) / len(self._items)

    def _move_pill(self):
        target = self._target_pill_x()
        self._anim.stop()
        if not self.isVisible():
            self._pill_x = target
            return
        self._anim.setStartValue(self._pill_x)
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_anim(self, value):
        self._pill_x = float(value)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._anim.stop()
        self._pill_x = self._target_pill_x()

    def showEvent(self, event):
        super().showEvent(event)
        self._pill_x = self._target_pill_x()

    # ---------- vẽ / chuột / phím ----------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        track = QColor(self._track)
        if not self.isEnabled():
            track.setAlphaF(0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        seg_w = self._inner_seg_width()
        pill_rect = QRectF(self._pill_x, 2, seg_w, h - 4)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawRoundedRect(pill_rect.translated(0, 1), 6.5, 6.5)
        p.setBrush(self._pill)
        p.drawRoundedRect(pill_rect, 6.5, 6.5)

        font = QFont(self.font())
        for i, (label, _data) in enumerate(self._items):
            selected = i == self._index
            font.setBold(selected)
            p.setFont(font)
            p.setPen(QColor(255, 255, 255, 255) if selected else QColor(209, 209, 214))
            p.drawText(QRectF(2 + i * seg_w, 0, seg_w, h), Qt.AlignCenter, label)

        if self._focus_ring:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(ACCENT, 2))
            p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 7, 7)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self.isEnabled():
            return
        i = int((event.position().x() - 2) // self._inner_seg_width())
        self.setCurrentIndex(max(0, min(len(self._items) - 1, i)))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Up):
            self.setCurrentIndex(self._index - 1)
        elif event.key() in (Qt.Key_Right, Qt.Key_Down):
            self.setCurrentIndex(self._index + 1)
        else:
            super().keyPressEvent(event)
