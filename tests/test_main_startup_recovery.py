"""
tests/test_main_startup_recovery.py

Task 11 — focused tests proving `run_startup_recovery()` (Task 9,
`recording.startup`) is correctly wired into the real application startup
in src/main.py.

Everything here runs in a fresh subprocess rather than importing `main`
(and therefore `glass_window` -> `recorder` -> `vlc`) into this test
process. Two reasons:

- `main.py` is not otherwise imported anywhere else in this suite, and
  test_recorder.py::test_recorder_functions_fully_without_any_window_or_widget_created
  asserts `"glass_window" not in sys.modules` as an architectural
  invariant. Importing `main` at module scope here (even once, even in a
  fixture) would permanently pollute sys.modules for the rest of the
  pytest session regardless of test execution order, since pytest
  collects/imports all test modules before running any test — so it would
  make that unrelated test order-dependent and, in practice, break it.
- It mirrors the pattern this codebase already uses in
  test_recording_startup.py for the same class of "what does importing/
  running this actually pull into sys.modules" question.

No real VLC binary and no real display/QApplication are used anywhere in
this module.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
_MAIN_PY = _SRC_DIR / "main.py"


# ---------------------------------------------------------------------
# Subprocess harness: drives main.main() against fully faked
# collaborators (QApplication, GlassWindow, TrayIcon, load_config,
# build_rtsp_url, QTimer.singleShot) and reports back what happened.
# ---------------------------------------------------------------------

_DRIVER_TEMPLATE = r"""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, {src_dir!r})

# Minimal fake `vlc` so `import main` (-> glass_window -> recorder ->
# `import vlc`) succeeds without a real libVLC installation, same
# approach as tests/conftest.py._install_fake_vlc_module.
fake_vlc = types.ModuleType("vlc")
fake_vlc._is_fake_vlc = True
class _State:
    NothingSpecial = "NothingSpecial"
    Playing = "Playing"
    Error = "Error"
fake_vlc.State = _State
fake_vlc.Instance = lambda *a, **kw: types.SimpleNamespace()
sys.modules["vlc"] = fake_vlc

import main

call_order = []
recovery_calls = []

def fake_run_startup_recovery(save_dir=None):
    call_order.append("run_startup_recovery")
    recovery_calls.append(save_dir)
    {recovery_side_effect}

class _FakeAppInstance:
    def __init__(self):
        self.exec_called = False
    def setQuitOnLastWindowClosed(self, *a, **kw):
        pass
    def setWindowIcon(self, *a, **kw):
        pass
    def exec(self):
        self.exec_called = True
        return 0

fake_app_instance = _FakeAppInstance()

class _FakeGlassWindow:
    def __init__(self, *a, **kw):
        call_order.append("GlassWindow")
    def show(self):
        pass
    def start_stream(self):
        pass

class _FakeTrayIcon:
    def __init__(self, *a, **kw):
        call_order.append("TrayIcon")

main.QApplication = lambda argv: fake_app_instance
main.QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
main.QIcon = lambda *a, **kw: None
main.get_app_icon_path = lambda: Path("/nonexistent/icon.png")
main.load_config = lambda: {{
    "rtsp": {{"ip": "1.2.3.4", "port": 554, "username": "a", "password": "b"}},
    "recording": {{"save_dir": "C:/recordings"}},
}}
main.build_rtsp_url = lambda rtsp_cfg: "rtsp://x"
main.run_startup_recovery = fake_run_startup_recovery
main.GlassWindow = _FakeGlassWindow
main.TrayIcon = _FakeTrayIcon
main.QTimer.singleShot = staticmethod(lambda *a, **kw: None)
main.sys.exit = lambda *a, **kw: None

warnings = []
_orig_print = print
def _capturing_print(*a, **kw):
    warnings.append(" ".join(str(x) for x in a))
    _orig_print(*a, **kw)
import builtins
builtins.print = _capturing_print

error = None
try:
    main.main()
except Exception as exc:  # the test itself asserts main() must not raise
    error = f"{{type(exc).__name__}}: {{exc}}"

result = {{
    "call_order": call_order,
    "recovery_call_count": len(recovery_calls),
    "recovery_calls": recovery_calls,
    "glasswindow_constructed": "GlassWindow" in call_order,
    "trayicon_constructed": "TrayIcon" in call_order,
    "app_exec_called": fake_app_instance.exec_called,
    "warnings": warnings,
    "raised": error,
}}
print("RESULT_JSON:" + json.dumps(result))
"""


def _run_main_driver(recovery_side_effect: str = "pass") -> dict:
    script = _DRIVER_TEMPLATE.format(
        src_dir=str(_SRC_DIR), recovery_side_effect=recovery_side_effect
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"driver subprocess failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line[len("RESULT_JSON:") :])
    raise AssertionError(f"no RESULT_JSON line in stdout:\n{proc.stdout}")


# ---------------------------------------------------------------------
# 1. run_startup_recovery is invoked exactly once
# ---------------------------------------------------------------------


def test_main_calls_run_startup_recovery_exactly_once():
    result = _run_main_driver()

    assert result["raised"] is None
    assert result["recovery_call_count"] == 1


# ---------------------------------------------------------------------
# 2. It happens before the main application runtime (GlassWindow/
#    TrayIcon) is constructed
# ---------------------------------------------------------------------


def test_run_startup_recovery_happens_before_glasswindow_and_tray():
    result = _run_main_driver()

    call_order = result["call_order"]
    assert call_order.index("run_startup_recovery") < call_order.index("GlassWindow")
    assert call_order.index("run_startup_recovery") < call_order.index("TrayIcon")


# ---------------------------------------------------------------------
# 3. A recovery exception does not prevent the application startup path
#    from continuing
# ---------------------------------------------------------------------


def test_recovery_exception_does_not_prevent_app_startup():
    result = _run_main_driver(
        recovery_side_effect='raise RuntimeError("disk exploded")'
    )

    assert result["raised"] is None  # main() itself must not raise
    assert result["recovery_call_count"] == 1
    assert result["glasswindow_constructed"] is True
    assert result["trayicon_constructed"] is True
    assert result["app_exec_called"] is True
    assert any(
        "WARN" in w and "disk exploded" in w for w in result["warnings"]
    ), result["warnings"]


# ---------------------------------------------------------------------
# 4. run_startup_recovery receives the configured save_dir
# ---------------------------------------------------------------------


def test_run_startup_recovery_called_with_configured_save_dir():
    result = _run_main_driver()

    assert result["recovery_calls"] == ["C:/recordings"]


# ---------------------------------------------------------------------
# 5. Preserve existing behavior: the app still runs normally end-to-end
#    after a successful recovery
# ---------------------------------------------------------------------


def test_app_still_starts_normally_after_successful_recovery():
    result = _run_main_driver()

    assert result["glasswindow_constructed"] is True
    assert result["trayicon_constructed"] is True
    assert result["app_exec_called"] is True


# ---------------------------------------------------------------------
# 6. Wiring goes through recording.startup, not recorder.py / vlc
#    (static source check — does not import main.py at all)
# ---------------------------------------------------------------------


def test_main_source_imports_run_startup_recovery_from_recording_startup():
    """main.py's import of run_startup_recovery must come from
    `recording.startup` (Task 9's stdlib-only entry point). main.py must
    not import `recorder` or `vlc` itself merely to perform recovery —
    recorder/vlc only ever enter main.py's import graph transitively
    through GlassWindow, which this task does not touch.
    """
    source = _MAIN_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)

    recovery_import_modules = []
    top_level_module_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            top_level_module_names.add(node.module)
            if any(alias.name == "run_startup_recovery" for alias in node.names):
                recovery_import_modules.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top_level_module_names.add(alias.name)

    assert recovery_import_modules == ["recording.startup"]
    assert "recorder" not in top_level_module_names
    assert "vlc" not in top_level_module_names


def test_main_module_does_not_import_vlc_directly():
    """The recovery wiring itself must not need `vlc` in sys.modules to
    resolve main.py's own import graph. Checked via a fresh subprocess
    (mirroring test_recording_startup.py's approach) so this doesn't
    depend on the fake `vlc` conftest.py installs for the rest of the
    suite, and doesn't require a real `vlc` package either.
    """
    script = textwrap.dedent(
        f"""
        import ast
        from pathlib import Path

        source = Path({str(_MAIN_PY)!r}).read_text(encoding="utf-8")
        tree = ast.parse(source)

        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name)

        assert "vlc" not in names, names
        assert "recording.startup" in names, names
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"
