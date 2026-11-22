"""tests/test_recorder_independence.py — ghi tay và ghi tự động chạy ĐỘC LẬP:
hai EmergencyRecorder, thư mục phiên khác nhau, dừng cái này không đụng cái kia."""

import json
import re

import pytest

from recorder import EmergencyRecorder
from recording import KIND_AUTO, KIND_MANUAL, RecordingMetadataStore, SUMMARY_FILENAME

RTSP_CFG = {"ip": "192.168.1.50", "port": 554, "username": "admin",
            "password": "pw", "stream_type": "sub", "channel": "ch1"}

NAME_RE = r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(ThuCong|TuDong)(_\d+)?"


def test_default_recorder_is_manual_protected_and_forces_main(tmp_path, wired_vlc):
    rec = EmergencyRecorder()
    rec.start(RTSP_CFG, str(tmp_path))
    assert rec.kind == KIND_MANUAL
    assert re.fullmatch(NAME_RE.replace("(ThuCong|TuDong)", "ThuCong"), rec._session_dir.name)
    assert rec._session.protected is True
    assert "/main/av_stream" in wired_vlc.instance.media_new.call_args[0][0]
    rec.stop()


def test_auto_recorder_is_unprotected_and_named_tudong(tmp_path, wired_vlc):
    rec = EmergencyRecorder(kind=KIND_AUTO, stream_type="sub")
    rec.start(RTSP_CFG, str(tmp_path))
    assert rec._session_dir.name.endswith("_TuDong")
    assert rec._session.protected is False
    assert "/sub/av_stream" in wired_vlc.instance.media_new.call_args[0][0]
    rec.stop()


def test_invalid_kind_rejected():
    with pytest.raises(ValueError):
        EmergencyRecorder(kind="whatever")


def test_session_id_equals_folder_name_in_session_json(tmp_path, wired_vlc):
    rec = EmergencyRecorder(kind=KIND_AUTO)
    rec.start(RTSP_CFG, str(tmp_path))
    rec.stop()
    data = json.loads((rec._session_dir / "session.json").read_text(encoding="utf-8"))
    assert data["session_id"] == rec._session_dir.name
    assert data["protected"] is False


def test_readable_summary_file_is_written(tmp_path, wired_vlc):
    rec = EmergencyRecorder(kind=KIND_AUTO)
    rec.start(RTSP_CFG, str(tmp_path))
    rec.stop()
    text = (rec._session_dir / SUMMARY_FILENAME).read_text(encoding="utf-8-sig")
    assert "GHI HÌNH TỰ ĐỘNG" in text
    assert "Hoàn tất" in text
    assert "tự xoá" in text


def test_same_second_same_kind_gets_unique_folder(tmp_path, segment_vlc, monkeypatch):
    import datetime as real_dt
    import recorder as rec_mod

    fixed = real_dt.datetime(2026, 11, 22, 14, 30, 5)

    class FixedDateTime(real_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.replace(tzinfo=tz)

    monkeypatch.setattr(rec_mod.datetime, "datetime", FixedDateTime)
    a = EmergencyRecorder(kind=KIND_AUTO)
    b = EmergencyRecorder(kind=KIND_AUTO)
    a.start(RTSP_CFG, str(tmp_path))
    b.start(RTSP_CFG, str(tmp_path))
    assert a._session_dir != b._session_dir
    assert b._session_dir.name.endswith("_TuDong_2")
    a.stop()
    b.stop()


def test_manual_and_auto_record_side_by_side_without_clashing(tmp_path, segment_vlc):
    manual = EmergencyRecorder()
    auto = EmergencyRecorder(kind=KIND_AUTO)

    manual.start(RTSP_CFG, str(tmp_path))
    auto.start(RTSP_CFG, str(tmp_path))
    assert manual.is_recording() and auto.is_recording()
    assert manual._session_dir != auto._session_dir
    assert manual._session_dir.parent == auto._session_dir.parent == tmp_path

    auto.stop()
    assert manual.is_recording() and not auto.is_recording()
    auto.start(RTSP_CFG, str(tmp_path))
    manual.stop()
    assert auto.is_recording() and not manual.is_recording()
    auto.stop()


def test_active_session_dir_only_while_recording(tmp_path, wired_vlc):
    rec = EmergencyRecorder(kind=KIND_AUTO)
    assert rec.active_session_dir() is None
    rec.start(RTSP_CFG, str(tmp_path))
    assert rec.active_session_dir() == rec._session_dir
    rec.stop()
    assert rec.active_session_dir() is None


def test_new_style_session_dirs_are_found_by_startup_recovery(tmp_path, wired_vlc):
    from recording.recovery import discover_session_dirs

    rec = EmergencyRecorder(kind=KIND_AUTO)
    rec.start(RTSP_CFG, str(tmp_path))
    rec.stop()
    assert rec._session_dir.name in [p.name for p in discover_session_dirs(tmp_path)]
