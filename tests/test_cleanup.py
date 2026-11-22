"""tests/test_cleanup.py — recording/cleanup.py (tự xoá bản ghi cũ khi vượt ngưỡng)."""

from datetime import datetime, timedelta, timezone

import pytest

from recording import RecordingMetadataStore, RecordingSession, RecordingStatus
from recording.cleanup import (
    TARGET_RATIO,
    delete_session_dir,
    get_retention_config,
    plan_cleanup,
    run_cleanup,
    scan_sessions,
    summarize_usage,
)

MB = 1024 * 1024
BASE_T = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


def make_session_dir(base, name, *, size_mb, minutes_ago, protected=False,
                     status=RecordingStatus.STOPPED, with_json=True, extra_files=()):
    d = base / name
    d.mkdir(parents=True)
    (d / "00-00-01.mkv").write_bytes(b"\0" * (size_mb * MB))
    (d / "thong-tin.txt").write_text("x", encoding="utf-8")
    if with_json:
        s = RecordingSession(session_id=name, protected=protected,
                             started_at=BASE_T - timedelta(minutes=minutes_ago))
        s.transition_to(RecordingStatus.STARTING)
        if status is RecordingStatus.STARTING:
            pass
        else:
            s.transition_to(RecordingStatus.RECORDING)
            if status is RecordingStatus.STOPPED:
                s.transition_to(RecordingStatus.STOPPING)
                s.transition_to(RecordingStatus.STOPPED)
            elif status is RecordingStatus.FAILED:
                s.transition_to(RecordingStatus.FAILED)
        RecordingMetadataStore(d).save(s)
    for fname in extra_files:
        (d / fname).write_text("mine", encoding="utf-8")
    return d


def auto(base, n, size_mb, minutes_ago, **kw):
    return make_session_dir(base, f"2026-11-0{n}_10-00-00_TuDong", size_mb=size_mb,
                            minutes_ago=minutes_ago, protected=False, **kw)


def manual(base, n, size_mb, minutes_ago, **kw):
    return make_session_dir(base, f"2026-11-0{n}_10-00-00_ThuCong", size_mb=size_mb,
                            minutes_ago=minutes_ago, protected=True, **kw)


def names(base):
    return sorted(p.name for p in base.iterdir())


# ---------------- config ----------------


def test_retention_config_defaults_and_clamp():
    assert get_retention_config({}) == {"enabled": True, "max_gb": 20}
    assert get_retention_config(None) == {"enabled": True, "max_gb": 20}
    assert get_retention_config({"retention": {"max_gb": 0}})["max_gb"] == 1
    assert get_retention_config({"retention": {"max_gb": 10**9}})["max_gb"] == 5000
    assert get_retention_config({"retention": {"max_gb": "abc"}})["max_gb"] == 20
    assert get_retention_config({"retention": {"enabled": False}})["enabled"] is False


# ---------------- quét ----------------


def test_scan_orders_oldest_first_and_counts_real_size(tmp_path):
    auto(tmp_path, 3, 5, minutes_ago=10)
    auto(tmp_path, 1, 7, minutes_ago=300)
    auto(tmp_path, 2, 6, minutes_ago=100)
    entries = scan_sessions(tmp_path)
    assert [e.path.name[:12] for e in entries] == [
        "2026-11-01_1", "2026-11-02_1", "2026-11-03_1"]
    assert entries[0].size_bytes >= 7 * MB


def test_scan_ignores_unrelated_dirs_and_files(tmp_path):
    auto(tmp_path, 1, 1, 10)
    (tmp_path / "Phim gia dinh").mkdir()
    (tmp_path / "Phim gia dinh" / "a.mkv").write_bytes(b"\0" * MB)
    (tmp_path / "ghichu.txt").write_text("hi")
    entries = scan_sessions(tmp_path)
    assert len(entries) == 1


def test_scan_missing_dir_is_empty(tmp_path):
    assert scan_sessions(tmp_path / "nope") == []


# ---------------- kế hoạch ----------------


def test_under_cap_plans_nothing(tmp_path):
    auto(tmp_path, 1, 5, 100)
    plan = plan_cleanup(scan_sessions(tmp_path), max_bytes=50 * MB)
    assert plan.to_delete == [] and plan.unresolved is False


def test_over_cap_deletes_oldest_first_down_to_target(tmp_path):
    for n, age in ((1, 400), (2, 300), (3, 200), (4, 100)):
        auto(tmp_path, n, 10, age)               # 4 x 10MB = ~40MB
    plan = plan_cleanup(scan_sessions(tmp_path), max_bytes=30 * MB)
    deleted = [e.path.name[:10] for e in plan.to_delete]
    assert deleted[0] == "2026-11-01"             # cũ nhất trước
    assert plan.expected_total_bytes <= int(30 * MB * TARGET_RATIO)
    assert plan.unresolved is False
    assert "2026-11-04" not in deleted            # bản mới nhất được giữ


def test_manual_sessions_are_never_planned_for_deletion(tmp_path):
    manual(tmp_path, 1, 10, 500)
    auto(tmp_path, 2, 10, 100)
    plan = plan_cleanup(scan_sessions(tmp_path), max_bytes=5 * MB)
    assert [e.path.name for e in plan.to_delete] == ["2026-11-02_10-00-00_TuDong"]
    assert plan.unresolved is True                # thủ công một mình đã vượt ngưỡng


def test_active_sessions_are_excluded(tmp_path):
    a = auto(tmp_path, 1, 10, 500)
    auto(tmp_path, 2, 10, 100)
    plan = plan_cleanup(scan_sessions(tmp_path), max_bytes=12 * MB,
                        exclude_dirs=[a])
    assert [e.path.name[:10] for e in plan.to_delete] == ["2026-11-02"]


def test_non_terminal_sessions_are_not_deletable(tmp_path):
    auto(tmp_path, 1, 10, 500, status=RecordingStatus.STARTING)
    entries = scan_sessions(tmp_path)
    assert entries[0].deletable is False


def test_failed_auto_session_is_deletable(tmp_path):
    auto(tmp_path, 1, 10, 500, status=RecordingStatus.FAILED)
    assert scan_sessions(tmp_path)[0].deletable is True


def test_dir_without_valid_session_json_is_never_deletable(tmp_path):
    auto(tmp_path, 1, 10, 500, with_json=False)
    d = auto(tmp_path, 2, 10, 400)
    (d / "session.json").write_text("{ not json", encoding="utf-8")
    entries = scan_sessions(tmp_path)
    assert all(e.deletable is False for e in entries)


def test_legacy_emergency_uuid_dirs_are_protected_manual(tmp_path):
    make_session_dir(tmp_path, "emergency_1234", size_mb=10, minutes_ago=500, protected=True)
    assert scan_sessions(tmp_path)[0].deletable is False


def test_legacy_motion_dirs_are_treated_as_auto(tmp_path):
    make_session_dir(tmp_path, "emergency_motion_1234", size_mb=10, minutes_ago=500, protected=True)
    assert scan_sessions(tmp_path)[0].deletable is True


# ---------------- xoá thật ----------------


def test_run_cleanup_deletes_oldest_and_keeps_manual_and_newest(tmp_path):
    manual(tmp_path, 1, 10, 900)
    auto(tmp_path, 2, 10, 800)
    auto(tmp_path, 3, 10, 700)
    auto(tmp_path, 4, 10, 100)
    report = run_cleanup(tmp_path, max_bytes=25 * MB)
    left = names(tmp_path)
    assert "2026-11-01_10-00-00_ThuCong" in left
    assert "2026-11-04_10-00-00_TuDong" in left
    assert "2026-11-02_10-00-00_TuDong" not in left
    assert report.deleted[0] == "2026-11-02_10-00-00_TuDong"
    assert report.freed_bytes >= 10 * MB
    assert report.total_after <= 25 * MB
    assert report.unresolved is False


def test_run_cleanup_under_cap_touches_nothing(tmp_path):
    auto(tmp_path, 1, 5, 100)
    report = run_cleanup(tmp_path, max_bytes=100 * MB)
    assert report.deleted == [] and len(names(tmp_path)) == 1


def test_run_cleanup_unresolved_when_only_manual_left(tmp_path):
    manual(tmp_path, 1, 10, 500)
    report = run_cleanup(tmp_path, max_bytes=5 * MB)
    assert report.deleted == [] and report.unresolved is True
    assert len(names(tmp_path)) == 1


def test_delete_session_dir_keeps_foreign_files_and_dir(tmp_path):
    d = auto(tmp_path, 1, 3, 100, extra_files=("anh-cua-toi.jpg",))
    freed = delete_session_dir(d)
    assert freed >= 3 * MB
    assert d.exists()                              # còn file lạ nên giữ thư mục
    assert [p.name for p in d.iterdir()] == ["anh-cua-toi.jpg"]


def test_delete_session_dir_removes_empty_dir(tmp_path):
    d = auto(tmp_path, 1, 3, 100)
    delete_session_dir(d)
    assert not d.exists()


def test_cleanup_never_touches_unrelated_content(tmp_path):
    other = tmp_path / "Phim gia dinh"
    other.mkdir()
    (other / "a.mkv").write_bytes(b"\0" * (20 * MB))
    auto(tmp_path, 1, 10, 100)
    run_cleanup(tmp_path, max_bytes=1 * MB)
    assert (other / "a.mkv").exists()


# ---------------- thống kê ----------------


def test_summarize_usage(tmp_path):
    manual(tmp_path, 1, 10, 500)
    auto(tmp_path, 2, 6, 400)
    u = summarize_usage(tmp_path)
    assert u["sessions"] == 2
    assert u["auto"] >= 6 * MB and u["protected"] >= 10 * MB
    assert u["total"] == u["auto"] + u["protected"]
