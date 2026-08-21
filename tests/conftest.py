"""
tests/conftest.py

Shared test infrastructure for characterization tests of src/recorder.py
(EmergencyRecorder).

Responsibilities:
- Add src/ to sys.path so `import recorder` (and recorder's own
  `import vlc`, `from config_loader import build_rtsp_url`) resolve the
  same way they do when the real app runs.
- Install a FAKE `vlc` module into sys.modules before anything imports
  recorder.py. The real `python-vlc` package requires a native libVLC
  installation that is not available (and, per the audit task, must not
  be required) in the test environment. Tests configure the fake module's
  behavior per-test via the `fake_vlc` / `wired_vlc` fixtures below.
- Provide a QCoreApplication so PySide6 QObject/QTimer/Signal machinery
  used by EmergencyRecorder behaves normally outside the full app.

No real VLC binary and no real RTSP camera are used anywhere in this
test suite.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---- make src/ importable, same as the real app (main.py runs with src/
# as the working directory / on sys.path) ----
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


def _install_fake_vlc_module():
    """Install a minimal fake `vlc` module so `import vlc` in recorder.py
    succeeds without a real libVLC installation. Only the surface actually
    used by recorder.py is modeled: vlc.State (with the members recorder.py
    references) and vlc.Instance (a MagicMock factory tests configure)."""
    existing = sys.modules.get("vlc")
    if existing is not None and getattr(existing, "_is_fake_vlc", False):
        return existing

    fake = types.ModuleType("vlc")
    fake._is_fake_vlc = True

    class State:
        NothingSpecial = "NothingSpecial"
        Opening = "Opening"
        Buffering = "Buffering"
        Playing = "Playing"
        Paused = "Paused"
        Stopped = "Stopped"
        Ended = "Ended"
        Error = "Error"

    fake.State = State
    fake.Instance = MagicMock(name="vlc.Instance")

    sys.modules["vlc"] = fake
    return fake


_install_fake_vlc_module()


@pytest.fixture(scope="session")
def qapp():
    """A single QCoreApplication for the whole test session. EmergencyRecorder
    only uses QtCore (QObject/QTimer/Signal) — QCoreApplication is enough,
    no QPA platform plugin (e.g. 'offscreen') is required."""
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(["pytest"])
    return app


@pytest.fixture(autouse=True)
def _qapp_available(qapp):
    """Every test automatically gets a live QCoreApplication instance."""
    yield


@pytest.fixture
def fake_vlc():
    """The fake `vlc` module, reset to a clean MagicMock `Instance` factory
    for every test so call-history/return-values never leak between tests."""
    mod = sys.modules["vlc"]
    mod.Instance = MagicMock(name="vlc.Instance")
    return mod


@pytest.fixture
def wired_vlc(fake_vlc):
    """Wires fake_vlc.Instance(...) to return a MagicMock VLC instance whose
    media_player_new()/media_new() calls return distinct, inspectable mocks
    — mirroring the real python-vlc object graph recorder.py drives
    (instance -> media_player, instance -> media).

    Default media_player.get_state() reports 'Playing' (i.e. no error) so
    tests that don't care about the watchdog error path aren't affected by
    it.
    """
    instance_mock = MagicMock(name="vlc_instance")
    media_player_mock = MagicMock(name="media_player")
    media_mock = MagicMock(name="media")

    instance_mock.media_player_new.return_value = media_player_mock
    instance_mock.media_new.return_value = media_mock
    fake_vlc.Instance.return_value = instance_mock

    media_player_mock.get_state.return_value = fake_vlc.State.Playing

    class Wired:
        instance = instance_mock
        media_player = media_player_mock
        media = media_mock

    return Wired
