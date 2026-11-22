"""tests/test_ui_widgets.py — ToggleSwitch / SegmentedControl (ui_widgets.py)."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from ui_widgets import SegmentedControl, ToggleSwitch


def test_toggle_switch_behaves_like_checkbox(qapp):
    t = ToggleSwitch()
    seen = []
    t.toggled.connect(seen.append)
    assert t.isChecked() is False
    t.setChecked(True)
    assert t.isChecked() is True and seen == [True]
    t.setChecked(False)
    assert seen == [True, False]


def test_toggle_switch_click_toggles(qapp):
    t = ToggleSwitch()
    t.show()
    QTest.mouseClick(t, Qt.LeftButton)
    assert t.isChecked() is True
    QTest.mouseClick(t, Qt.LeftButton)
    assert t.isChecked() is False


def test_toggle_switch_initial_state_is_painted_without_animation(qapp):
    t = ToggleSwitch()
    t.setChecked(True)           # chưa hiện -> nhảy thẳng tới vị trí "bật"
    assert t._t == 1.0
    img = t.grab().toImage()
    assert not img.isNull()


def test_toggle_switch_animates_when_visible(qapp):
    t = ToggleSwitch()
    t.show()
    t.setChecked(True)
    QTest.qWait(260)
    assert t._t == pytest.approx(1.0, abs=0.01)


ITEMS = [("Thấp", "low"), ("Vừa", "medium"), ("Cao", "high")]


def test_segmented_current_data_and_set(qapp):
    s = SegmentedControl(ITEMS)
    assert s.currentIndex() == 0 and s.currentData() == "low"
    s.setCurrentData("high")
    assert s.currentIndex() == 2 and s.currentData() == "high"
    assert s.count() == 3 and s.itemText(1) == "Vừa"


def test_segmented_unknown_data_is_ignored(qapp):
    s = SegmentedControl(ITEMS)
    s.setCurrentData("medium")
    s.setCurrentData("???")
    assert s.currentData() == "medium"


def test_segmented_emits_only_on_real_change(qapp):
    s = SegmentedControl(ITEMS)
    seen = []
    s.currentChanged.connect(seen.append)
    s.setCurrentIndex(1)
    s.setCurrentIndex(1)
    s.setCurrentIndex(99)
    assert seen == [1]


def test_segmented_click_selects_segment(qapp):
    s = SegmentedControl(ITEMS)
    s.resize(s.sizeHint())
    s.show()
    third_x = int(s.width() * 5 / 6)
    QTest.mouseClick(s, Qt.LeftButton, Qt.NoModifier, QPoint(third_x, 15))
    assert s.currentData() == "high"
    QTest.mouseClick(s, Qt.LeftButton, Qt.NoModifier, QPoint(4, 15))
    assert s.currentData() == "low"


def test_segmented_keyboard_navigation(qapp):
    s = SegmentedControl(ITEMS)
    s.show()
    QTest.keyClick(s, Qt.Key_Right)
    assert s.currentData() == "medium"
    QTest.keyClick(s, Qt.Key_Left)
    assert s.currentData() == "low"
    QTest.keyClick(s, Qt.Key_Left)         # không vượt quá mép
    assert s.currentData() == "low"


def test_segmented_stretch_mode_fills_width(qapp):
    s = SegmentedControl(ITEMS, stretch=True)
    s.resize(300, 30)
    s.show()
    assert s._inner_seg_width() == pytest.approx((300 - 4) / 3)


def test_segmented_requires_items(qapp):
    with pytest.raises(ValueError):
        SegmentedControl([])


def test_segmented_paints(qapp):
    s = SegmentedControl(ITEMS)
    s.resize(s.sizeHint())
    assert not s.grab().toImage().isNull()
