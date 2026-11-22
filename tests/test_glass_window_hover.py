"""tests/test_glass_window_hover.py — điều khiển trên cửa sổ camera chỉ hiện khi
rê chuột (GlassWindow). StreamWidget được thay bằng bản giả để không cần libVLC."""

import sys

import pytest
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

# glass_window được import TRỄ (trong fixture) và gỡ khỏi sys.modules sau khi
# xong module này: tests/test_recorder.py có một test khẳng định recorder chạy
# được trong tiến trình CHƯA từng import glass_window, nên ở đây không được để
# module đó "rò" sang các file test khác (kể cả khi chỉ collect, không chạy).
gw = None


@pytest.fixture(scope="module", autouse=True)
def _glass_window_module():
    global gw
    import glass_window

    gw = glass_window
    yield
    sys.modules.pop("glass_window", None)
    gw = None


class FakeStream(QWidget):
    native_size_ready = Signal(int, int)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self._muted = False

    def get_connection_state(self):
        return "connected"

    def is_muted(self):
        return self._muted

    def set_muted(self, muted):
        self._muted = muted

    def latest_frame(self):
        return None

    def __getattr__(self, name):
        # mọi phương thức khác (start/stop/...) là no-op
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


class Ev:
    """Sự kiện chuột tối giản cho handle_mouse_press()."""

    def __init__(self, x, y):
        self._p = QPointF(x, y)

    def button(self):
        return Qt.LeftButton

    def position(self):
        return self._p

    def globalPosition(self):
        return self._p


@pytest.fixture
def win(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "StreamWidget", FakeStream)
    monkeypatch.setattr(gw, "save_config", lambda cfg: None)
    cfg = {
        "rtsp": {"ip": "1.2.3.4", "port": 554, "username": "a", "password": "b",
                 "stream_type": "sub", "channel": "ch1"},
        "window": {"width": 400, "height": 225, "pos_x": 0, "pos_y": 0},
        "recording": {"save_dir": str(tmp_path)},
        "retention": {"enabled": False},
    }
    w = gw.GlassWindow(cfg, "rtsp://x")
    w._hover_timer.stop()          # test tự điều khiển, không để timer can thiệp
    w.motion.shutdown()
    yield w
    w.cleanup.shutdown()
    w.status_timer.stop()


def test_controls_start_hidden(win):
    assert win._controls_opacity == 0.0
    assert win._controls_clickable() is False


def test_hover_fades_controls_in_and_out(win):
    win.show()
    win._set_controls_target(1.0)
    QTest.qWait(300)
    assert win._controls_opacity == pytest.approx(1.0, abs=0.02)
    assert win._controls_clickable() is True
    win._set_controls_target(0.0)
    QTest.qWait(500)
    assert win._controls_opacity == pytest.approx(0.0, abs=0.02)


def test_poll_hover_uses_cursor_position(win, monkeypatch):
    win.show()
    from PySide6.QtCore import QPoint
    monkeypatch.setattr(gw.QCursor, "pos", staticmethod(lambda: win.mapToGlobal(QPoint(50, 50))))
    win._poll_hover()
    assert win._controls_target == 1.0
    monkeypatch.setattr(gw.QCursor, "pos", staticmethod(lambda: win.mapToGlobal(QPoint(-500, -500))))
    win._poll_hover()
    assert win._controls_target == 0.0


def test_poll_hover_stays_visible_while_dragging(win, monkeypatch):
    win.show()
    from PySide6.QtCore import QPoint
    win._drag_pos = QPoint(1, 1)
    monkeypatch.setattr(gw.QCursor, "pos", staticmethod(lambda: win.mapToGlobal(QPoint(-500, -500))))
    win._poll_hover()
    assert win._controls_target == 1.0


def test_hidden_buttons_do_not_react_to_clicks(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win, "toggle_recording", lambda: calls.append("rec"))
    monkeypatch.setattr(win, "toggle_mute", lambda: calls.append("mute"))
    monkeypatch.setattr(win, "show_about_dialog", lambda: calls.append("about"))
    for rect in (win._record_rect(), win._mute_rect(), win._about_rect()):
        win.handle_mouse_press(Ev(rect.center().x(), rect.center().y()))
        win.handle_mouse_release(Ev(0, 0))
    assert calls == []


def test_visible_buttons_react_to_clicks(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win, "toggle_recording", lambda: calls.append("rec"))
    monkeypatch.setattr(win, "toggle_mute", lambda: calls.append("mute"))
    monkeypatch.setattr(win, "show_about_dialog", lambda: calls.append("about"))
    win._controls_opacity = 1.0
    for rect in (win._record_rect(), win._mute_rect(), win._about_rect()):
        win.handle_mouse_press(Ev(rect.center().x(), rect.center().y()))
    assert calls == ["rec", "mute", "about"]


def test_record_button_stays_clickable_while_recording_even_if_faded(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win, "toggle_recording", lambda: calls.append("rec"))
    monkeypatch.setattr(win.recorder, "is_recording", lambda: True)
    r = win._record_rect()
    win.handle_mouse_press(Ev(r.center().x(), r.center().y()))
    assert calls == ["rec"]


def test_mute_button_stays_clickable_while_muted_even_if_faded(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win, "toggle_mute", lambda: calls.append("mute"))
    win.stream_widget.set_muted(True)
    r = win._mute_rect()
    win.handle_mouse_press(Ev(r.center().x(), r.center().y()))
    assert calls == ["mute"]


def test_resize_grip_still_works_when_hidden(win):
    g = win._grip_rect()
    win.handle_mouse_press(Ev(g.center().x(), g.center().y()))
    assert win._resizing is True
    win.handle_mouse_release(Ev(0, 0))


@pytest.mark.parametrize("opacity", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("recording", [False, True])
@pytest.mark.parametrize("muted", [False, True])
def test_overlay_paints_in_every_state(win, monkeypatch, opacity, recording, muted):
    win.show()
    win._controls_opacity = opacity
    monkeypatch.setattr(win.recorder, "is_recording", lambda: recording)
    monkeypatch.setattr(win.recorder, "elapsed_seconds", lambda: 75)
    win.stream_widget.set_muted(muted)
    assert not win.grab().toImage().isNull()


def test_auto_badge_paints_and_shifts_with_controls(win, monkeypatch):
    win.show()
    monkeypatch.setattr(win.motion, "is_recording", lambda: True)
    monkeypatch.setattr(win.motion, "elapsed_seconds", lambda: 7)
    for op in (0.0, 1.0):
        win._controls_opacity = op
        assert not win.grab().toImage().isNull()
