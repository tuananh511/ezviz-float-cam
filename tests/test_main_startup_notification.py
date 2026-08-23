"""
tests/test_main_startup_notification.py

Task 12 — focused tests proving that the `RecoveryReport` returned by
`run_startup_recovery()` (Task 9/11) is surfaced to the user through the
existing `TrayIcon` / `QSystemTrayIcon.showMessage()` notification API in
src/main.py, without touching recovery.py/startup.py/the recovery state
machine, and without introducing any new notification mechanism.

Same subprocess-harness approach as test_main_startup_recovery.py, for
the same reasons (avoids permanently importing `main` -> `glass_window`
-> `recorder` -> `vlc` into this test process, which would break
test_recorder.py's `"glass_window" not in sys.modules` invariant).

No real VLC binary and no real display/QApplication are used anywhere in
this module.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
_MAIN_PY = _SRC_DIR / "main.py"


# ---------------------------------------------------------------------
# Subprocess harness: drives main.main() against fully faked
# collaborators, with a fake TrayIcon that records every showMessage()
# call so tests can assert on notification content/severity/ordering
# without a real system tray.
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
notify_calls = []

class _FakeRecoveryResult:
    pass

def _fake_report(recovered=0, invalid=0, failed=0):
    return types.SimpleNamespace(
        recovered=[object()] * recovered,
        already_terminal=[],
        invalid=[object()] * invalid,
        failed=[object()] * failed,
    )

_REPORT = {report_expr}

def fake_run_startup_recovery(save_dir=None):
    call_order.append("run_startup_recovery")
    recovery_calls.append(save_dir)
    {recovery_side_effect}
    return _REPORT

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
    def showMessage(self, title, message, icon=None, msecs=0):
        call_order.append("showMessage")
        notify_calls.append({{
            "title": title,
            "message": message,
            "icon": str(icon),
        }})
        {notify_side_effect}

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
    "notify_calls": notify_calls,
    "glasswindow_constructed": "GlassWindow" in call_order,
    "trayicon_constructed": "TrayIcon" in call_order,
    "app_exec_called": fake_app_instance.exec_called,
    "warnings": warnings,
    "raised": error,
}}
print("RESULT_JSON:" + json.dumps(result))
"""


def _run_main_driver(
    report_expr: str = "_fake_report()",
    recovery_side_effect: str = "pass",
    notify_side_effect: str = "pass",
) -> dict:
    script = _DRIVER_TEMPLATE.format(
        src_dir=str(_SRC_DIR),
        report_expr=report_expr,
        recovery_side_effect=recovery_side_effect,
        notify_side_effect=notify_side_effect,
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
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
# 1. recovered > 0 -> exactly one notification, Information severity,
#    with a concise count (no raw paths/session ids/exceptions).
# ---------------------------------------------------------------------


def test_recovered_sessions_produce_exactly_one_notification():
    result = _run_main_driver(report_expr="_fake_report(recovered=3)")

    assert result["raised"] is None
    assert len(result["notify_calls"]) == 1
    call = result["notify_calls"][0]
    assert "3" in call["message"]
    assert "Information" in call["icon"]
    # No path-like or exception-like content leaks into the notification.
    assert "Traceback" not in call["message"]
    assert "/" not in call["message"] and "\\" not in call["message"]


# ---------------------------------------------------------------------
# 2. No recovered/invalid/failed sessions -> no notification at all.
# ---------------------------------------------------------------------


def test_empty_report_produces_no_notification():
    result = _run_main_driver(report_expr="_fake_report()")

    assert result["raised"] is None
    assert result["notify_calls"] == []


# ---------------------------------------------------------------------
# 3. invalid/failed sessions -> a separate Warning-severity notification.
# ---------------------------------------------------------------------


def test_invalid_and_failed_sessions_produce_warning_notification():
    result = _run_main_driver(report_expr="_fake_report(invalid=1, failed=2)")

    assert result["raised"] is None
    assert len(result["notify_calls"]) == 1
    call = result["notify_calls"][0]
    assert "3" in call["message"]  # invalid(1) + failed(2)
    assert "Warning" in call["icon"]


def test_recovered_and_problem_sessions_produce_two_distinct_notifications():
    result = _run_main_driver(report_expr="_fake_report(recovered=2, failed=1)")

    assert result["raised"] is None
    assert len(result["notify_calls"]) == 2
    severities = {c["icon"] for c in result["notify_calls"]}
    assert any("Information" in s for s in severities)
    assert any("Warning" in s for s in severities)


# ---------------------------------------------------------------------
# 4. Notification happens only after TrayIcon is constructed, but still
#    before app.exec().
# ---------------------------------------------------------------------


def test_notification_happens_after_trayicon_construction():
    result = _run_main_driver(report_expr="_fake_report(recovered=1)")

    call_order = result["call_order"]
    assert call_order.index("TrayIcon") < call_order.index("showMessage")


def test_notification_happens_before_app_exec():
    result = _run_main_driver(report_expr="_fake_report(recovered=1)")

    assert result["app_exec_called"] is True
    # showMessage must have been called (see call_order test above); this
    # test only pins down that reaching app.exec() is unaffected either
    # way, i.e. notification never blocks/skips startup continuing on to
    # app.exec().
    assert "showMessage" in result["call_order"]
    assert result["call_order"].index("showMessage") < len(result["call_order"])


# ---------------------------------------------------------------------
# 5. A notification failure (showMessage itself raising) must not abort
#    application startup.
# ---------------------------------------------------------------------


def test_notification_failure_does_not_abort_startup():
    result = _run_main_driver(
        report_expr="_fake_report(recovered=1)",
        notify_side_effect='raise RuntimeError("tray exploded")',
    )

    assert result["raised"] is None
    assert result["glasswindow_constructed"] is True
    assert result["trayicon_constructed"] is True
    assert result["app_exec_called"] is True
    assert any(
        "WARN" in w and "tray exploded" in w for w in result["warnings"]
    ), result["warnings"]


# ---------------------------------------------------------------------
# 6. Existing Task 11 behavior is untouched: a recovery exception (report
#    never produced) still allows startup to continue, and produces no
#    notification (there is nothing to report).
# ---------------------------------------------------------------------


def test_recovery_exception_still_continues_startup_and_skips_notification():
    result = _run_main_driver(
        recovery_side_effect='raise RuntimeError("disk exploded")'
    )

    assert result["raised"] is None
    assert result["recovery_call_count"] == 1
    assert result["glasswindow_constructed"] is True
    assert result["trayicon_constructed"] is True
    assert result["app_exec_called"] is True
    assert any(
        "WARN" in w and "disk exploded" in w for w in result["warnings"]
    ), result["warnings"]
    assert result["notify_calls"] == []


# ---------------------------------------------------------------------
# 7. run_startup_recovery() is still called exactly once, with the
#    configured save_dir (Task 11 wiring untouched).
# ---------------------------------------------------------------------


def test_run_startup_recovery_still_called_once_with_configured_save_dir():
    result = _run_main_driver(report_expr="_fake_report(recovered=1)")

    assert result["recovery_call_count"] == 1
    assert result["recovery_calls"] == ["C:/recordings"]
