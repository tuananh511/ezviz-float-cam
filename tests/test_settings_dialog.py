"""tests/test_settings_dialog.py — SettingsDialog (giao diện 3 tab, giữ nguyên API cũ)."""

import json
from pathlib import Path

import pytest

from settings_dialog import SettingsDialog

DEFAULT = json.loads(
    (Path(__file__).resolve().parent.parent / "config" / "default_config.json")
    .read_text(encoding="utf-8")
)


def cfg(**overrides):
    c = json.loads(json.dumps(DEFAULT))
    for k, v in overrides.items():
        c[k].update(v) if isinstance(v, dict) else c.__setitem__(k, v)
    c["rtsp"]["ip"] = c["rtsp"]["ip"] or "192.168.1.5"
    return c


def make(tmp_path, **overrides):
    c = cfg(**overrides)
    c.setdefault("recording", {})["save_dir"] = overrides.get("recording", {}).get("save_dir", str(tmp_path))
    return SettingsDialog(c)


def test_roundtrip_of_default_values(tmp_path):
    d = make(tmp_path)
    rtsp = d.get_rtsp_config()
    assert rtsp == {"ip": "192.168.1.100", "port": 554, "username": "admin",
                    "password": "", "stream_type": "sub", "channel": "ch1"}
    assert d.get_motion_config() == {"enabled": True, "sensitivity": "medium", "post_roll_s": 15}
    assert d.get_retention_settings() == {"enabled": True, "max_gb": 20}


def test_values_from_config_are_reflected(tmp_path):
    d = make(tmp_path,
             rtsp={"stream_type": "main", "port": 8554},
             motion={"enabled": False, "sensitivity": "high", "post_roll_s": 40},
             retention={"enabled": False, "max_gb": 75})
    assert d.get_rtsp_config()["stream_type"] == "main"
    assert d.get_rtsp_config()["port"] == 8554
    assert d.get_motion_config() == {"enabled": False, "sensitivity": "high", "post_roll_s": 40}
    assert d.get_retention_settings() == {"enabled": False, "max_gb": 75}


def test_user_changes_flow_into_getters(tmp_path):
    d = make(tmp_path)
    d.ip_edit.setText("10.0.0.7")
    d.stream_combo.setCurrentData("main")
    d.motion_check.setChecked(False)
    d.motion_sens_combo.setCurrentData("low")
    d.motion_post_roll_spin.setValue(60)
    d.retention_spin.setValue(50)
    assert d.get_rtsp_config()["ip"] == "10.0.0.7"
    assert d.get_rtsp_config()["stream_type"] == "main"
    assert d.get_motion_config() == {"enabled": False, "sensitivity": "low", "post_roll_s": 60}
    assert d.get_retention_settings()["max_gb"] == 50


def test_show_password_button_toggles_echo_mode_and_label(tmp_path):
    from PySide6.QtWidgets import QLineEdit
    d = make(tmp_path)
    assert d.pass_edit.echoMode() == QLineEdit.Password
    d.show_pass_check.setChecked(True)
    assert d.pass_edit.echoMode() == QLineEdit.Normal
    assert d.show_pass_check.text() == "Ẩn"
    d.show_pass_check.setChecked(False)
    assert d.pass_edit.echoMode() == QLineEdit.Password
    assert d.show_pass_check.text() == "Hiện"


def test_tabs_switch_pages(tmp_path):
    d = make(tmp_path)
    assert d._stack.currentIndex() == 0
    d._tabs.setCurrentIndex(2)
    assert d._stack.currentIndex() == 2


def test_save_without_ip_returns_to_connection_tab_and_stays_open(tmp_path):
    d = make(tmp_path)
    d.ip_edit.setText("   ")
    d._tabs.setCurrentIndex(2)
    d._on_save()
    assert d._tabs.currentIndex() == 0
    assert d.result() == 0                      # chưa Accepted
    assert "IP" in d.status_label.text()


def test_save_with_ip_accepts(tmp_path):
    d = make(tmp_path)
    d._on_save()
    assert d.result() == 1


def test_record_dir_is_shown_from_the_start_and_returned_unchanged(tmp_path):
    d = make(tmp_path)
    assert d.get_recording_config()["save_dir"] == str(tmp_path)
    assert d.record_dir_edit.cursorPosition() == 0   # luôn cuộn về đầu chuỗi


def test_use_default_record_dir_button(tmp_path):
    from recorder import default_recording_dir
    d = make(tmp_path)
    d._use_default_record_dir()
    assert Path(d.get_recording_config()["save_dir"]) == default_recording_dir()


def test_usage_bar_levels_follow_cap(tmp_path):
    d = make(tmp_path)
    gb = 1024 ** 3
    d._usage = {"total": 5 * gb, "auto": 4 * gb, "protected": 1 * gb, "sessions": 3}
    d.retention_spin.setValue(20)
    assert d.usage_bar.property("level") == "ok"
    d.retention_spin.setValue(5)            # 5/5 = 100%
    assert d.usage_bar.property("level") == "full"
    d.retention_spin.setValue(6)            # 83%... -> ok
    assert d.usage_bar.property("level") == "ok"
    d._usage = {"total": int(5.6 * gb), "auto": 0, "protected": int(5.6 * gb), "sessions": 1}
    d._refresh_usage()                      # 93% -> warn
    assert d.usage_bar.property("level") == "warn"
    assert "5.6 GB" in d.retention_usage_label.text()
    assert "6 GB" in d.retention_usage_label.text()


def test_usage_unavailable_is_handled(tmp_path):
    d = make(tmp_path)
    d._usage = None
    d._refresh_usage()
    assert d.retention_usage_label.text() == ""


def test_dialog_renders_every_tab(tmp_path):
    d = make(tmp_path)
    d.show()
    for i in range(3):
        d._tabs.setCurrentIndex(i)
        assert not d.grab().toImage().isNull()
