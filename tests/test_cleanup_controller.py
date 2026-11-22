"""tests/test_cleanup_controller.py — RecordingCleanupController (Qt, thư mục thật trong tmp)."""

from datetime import datetime, timedelta, timezone

from cleanup_controller import RecordingCleanupController
from recording import RecordingMetadataStore, RecordingSession, RecordingStatus

MB = 1024 * 1024


def make_auto(base, n, size_mb):
    name = f"2026-11-0{n}_10-00-00_TuDong"
    d = base / name
    d.mkdir(parents=True)
    (d / "00-00-01.mkv").write_bytes(b"\0" * (size_mb * MB))
    s = RecordingSession(session_id=name, protected=False,
                         started_at=datetime(2026, 11, n, 10, tzinfo=timezone.utc))
    s.transition_to(RecordingStatus.STARTING)
    s.transition_to(RecordingStatus.RECORDING)
    s.transition_to(RecordingStatus.STOPPING)
    s.transition_to(RecordingStatus.STOPPED)
    RecordingMetadataStore(d).save(s)
    return d


def cfg(tmp_path, **retention):
    return {"recording": {"save_dir": str(tmp_path)},
            "retention": {"enabled": True, "max_gb": 1, **retention}}


def test_disabled_does_nothing(tmp_path):
    make_auto(tmp_path, 1, 3)
    c = RecordingCleanupController(lambda: cfg(tmp_path, enabled=False), lambda: [])
    assert c.run_now() is None
    assert len(list(tmp_path.iterdir())) == 1


def test_under_threshold_keeps_everything(tmp_path):
    make_auto(tmp_path, 1, 3)
    c = RecordingCleanupController(lambda: cfg(tmp_path), lambda: [])
    report = c.run_now()
    assert report.deleted == []


def test_over_threshold_deletes_oldest_and_emits_signal(tmp_path, monkeypatch):
    import cleanup_controller as mod
    monkeypatch.setattr(mod, "_GB", 10 * MB)       # "1 GB" = 10 MB trong test
    for n in (1, 2, 3):
        make_auto(tmp_path, n, 6)                  # 18 MB > 10 MB
    emitted = []
    c = RecordingCleanupController(lambda: cfg(tmp_path), lambda: [])
    c.cleaned.connect(emitted.append)
    report = c.run_now()
    left = sorted(p.name[:10] for p in tmp_path.iterdir())
    assert left == ["2026-11-03"]                  # còn 6MB <= 90% của 10MB
    assert report.deleted[0].startswith("2026-11-01")
    assert len(emitted) == 1


def test_active_dirs_are_never_deleted(tmp_path, monkeypatch):
    import cleanup_controller as mod
    monkeypatch.setattr(mod, "_GB", 10 * MB)
    oldest = make_auto(tmp_path, 1, 6)
    make_auto(tmp_path, 2, 6)
    c = RecordingCleanupController(lambda: cfg(tmp_path), lambda: [oldest])
    c.run_now()
    assert oldest.exists()


def test_errors_never_propagate(tmp_path, monkeypatch):
    import cleanup_controller as mod

    def boom(*a, **k):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(mod, "run_cleanup", boom)
    c = RecordingCleanupController(lambda: cfg(tmp_path), lambda: [])
    assert c.run_now() is None
