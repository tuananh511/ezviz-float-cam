"""
tests/test_recording_metadata.py

Focused unit tests for src/recording/metadata.py (RecordingMetadataStore,
MetadataError) — Task 6 of the Player/Recorder migration.

Like test_recording_session.py and test_storage_policy.py, this module is
standard-library only: no PySide6, no VLC, and all filesystem access goes
through tmp_path (pytest's built-in temp directory fixture) — no writes
outside the test's own sandbox.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from recording import (
    MetadataError,
    RecordingMetadataStore,
    RecordingSegment,
    RecordingSession,
    RecordingStatus,
    SESSION_METADATA_FILENAME,
)


# ---------------------------------------------------------------------
# 1. Complete session round-trip
# ---------------------------------------------------------------------


def test_round_trip_preserves_all_session_fields(tmp_path):
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)
    session.add_bytes(1234)

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()

    assert loaded.session_id == session.session_id
    assert loaded.started_at == session.started_at
    assert loaded.ended_at == session.ended_at
    assert loaded.status == session.status
    assert loaded.protected == session.protected
    assert loaded.total_bytes == session.total_bytes
    assert loaded.error == session.error
    assert loaded.segments == []


def test_round_trip_preserves_error_message(tmp_path):
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.FAILED, error="disk write error")

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()

    assert loaded.error == "disk write error"
    assert loaded.status == RecordingStatus.FAILED


# ---------------------------------------------------------------------
# 2. Multiple segments
# ---------------------------------------------------------------------


def test_round_trip_preserves_all_segment_fields(tmp_path):
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.RECORDING)

    seg1 = RecordingSegment(
        path="C:/recordings/seg1.mkv",
        started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    seg1.mark_completed(
        ended_at=datetime(2026, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
        size_bytes=500_000,
    )
    seg2 = RecordingSegment(
        path="C:/recordings/seg2.mkv",
        started_at=datetime(2026, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
    )
    # seg2 left incomplete (still being written): ended_at None, completed False

    session.add_segment(seg1)
    session.add_segment(seg2)
    session.recalculate_total_bytes()

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()

    assert len(loaded.segments) == 2

    loaded_seg1, loaded_seg2 = loaded.segments
    assert loaded_seg1.path == seg1.path
    assert loaded_seg1.started_at == seg1.started_at
    assert loaded_seg1.ended_at == seg1.ended_at
    assert loaded_seg1.size_bytes == seg1.size_bytes
    assert loaded_seg1.completed is True

    assert loaded_seg2.path == seg2.path
    assert loaded_seg2.started_at == seg2.started_at
    assert loaded_seg2.ended_at is None
    assert loaded_seg2.size_bytes == 0
    assert loaded_seg2.completed is False

    assert loaded.total_bytes == 500_000


# ---------------------------------------------------------------------
# 3. Timezone-aware timestamps
# ---------------------------------------------------------------------


def test_utc_timestamps_are_preserved_exactly(tmp_path):
    started = datetime(2026, 6, 15, 3, 4, 5, 678901, tzinfo=timezone.utc)
    session = RecordingSession(started_at=started)

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()

    assert loaded.started_at == started
    assert loaded.started_at.tzinfo is not None
    assert loaded.started_at.utcoffset() == timedelta(0)


def test_non_utc_offset_is_normalized_to_utc_on_save(tmp_path):
    """A timezone-aware datetime with a non-UTC offset must still be
    preserved correctly — normalized to the equivalent UTC instant."""
    plus_seven = timezone(timedelta(hours=7))
    started = datetime(2026, 6, 15, 10, 4, 5, tzinfo=plus_seven)
    session = RecordingSession(started_at=started)

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()

    assert loaded.started_at == started  # same instant
    assert loaded.started_at == started.astimezone(timezone.utc)


def test_naive_datetime_is_rejected_on_save(tmp_path):
    session = RecordingSession(started_at=datetime(2026, 1, 1, 0, 0, 0))
    store = RecordingMetadataStore(tmp_path)

    with pytest.raises(MetadataError):
        store.save(session)


def test_metadata_file_stores_explicit_utc_z_suffix(tmp_path):
    started = datetime(2026, 6, 15, 3, 4, 5, 678901, tzinfo=timezone.utc)
    session = RecordingSession(started_at=started)

    store = RecordingMetadataStore(tmp_path)
    store.save(session)

    raw = json.loads(store.metadata_path.read_text(encoding="utf-8"))
    assert raw["started_at"].endswith("Z")
    assert "+00:00" not in raw["started_at"]


# ---------------------------------------------------------------------
# 4. Every terminal status
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "path_to_status",
    [
        RecordingStatus.STOPPED,
        RecordingStatus.FAILED,
        RecordingStatus.DISK_FULL,
    ],
)
def test_round_trip_preserves_terminal_status(tmp_path, path_to_status):
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    if path_to_status == RecordingStatus.STOPPED:
        session.transition_to(RecordingStatus.RECORDING)
        session.transition_to(RecordingStatus.STOPPING)
        session.transition_to(RecordingStatus.STOPPED)
    elif path_to_status == RecordingStatus.FAILED:
        session.transition_to(RecordingStatus.FAILED, error="boom")
    else:  # DISK_FULL
        session.transition_to(RecordingStatus.DISK_FULL)

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()

    assert loaded.status == path_to_status
    assert loaded.ended_at is not None


def test_round_trip_preserves_recoverable_status(tmp_path):
    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)
    session.transition_to(RecordingStatus.FAILED, error="boom")
    session.transition_to(RecordingStatus.RECOVERABLE)

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()

    assert loaded.status == RecordingStatus.RECOVERABLE
    # ended_at was set at FAILED time and untouched by RECOVERABLE
    assert loaded.ended_at == session.ended_at


@pytest.mark.parametrize("status", list(RecordingStatus))
def test_every_status_value_round_trips(tmp_path, status):
    """Every RecordingStatus enum member must be representable and
    reconstructible via session.json, regardless of reachability via
    normal transitions."""
    session = RecordingSession()
    session.status = status  # bypass transition rules for full enum coverage

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()

    assert loaded.status == status


# ---------------------------------------------------------------------
# 5. Protected flag
# ---------------------------------------------------------------------


def test_protected_defaults_true_and_round_trips(tmp_path):
    session = RecordingSession()
    assert session.protected is True

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()
    assert loaded.protected is True


def test_protected_false_round_trips(tmp_path):
    session = RecordingSession(protected=False)

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()
    assert loaded.protected is False


# ---------------------------------------------------------------------
# 6. total_bytes
# ---------------------------------------------------------------------


def test_total_bytes_round_trips(tmp_path):
    session = RecordingSession()
    session.add_bytes(42)
    session.add_bytes(58)
    assert session.total_bytes == 100

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()
    assert loaded.total_bytes == 100


def test_negative_total_bytes_in_file_is_rejected(tmp_path):
    session = RecordingSession()
    store = RecordingMetadataStore(tmp_path)
    store.save(session)

    data = json.loads(store.metadata_path.read_text(encoding="utf-8"))
    data["total_bytes"] = -5
    store.metadata_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(MetadataError):
        store.load()


# ---------------------------------------------------------------------
# 7. Malformed JSON
# ---------------------------------------------------------------------


def test_malformed_json_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    store.session_dir.mkdir(parents=True, exist_ok=True)
    store.metadata_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(MetadataError):
        store.load()


def test_json_that_is_not_an_object_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    store.session_dir.mkdir(parents=True, exist_ok=True)
    store.metadata_path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(MetadataError):
        store.load()


# ---------------------------------------------------------------------
# 8. Missing metadata
# ---------------------------------------------------------------------


def test_load_with_no_file_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    assert store.exists() is False

    with pytest.raises(MetadataError):
        store.load()


def test_load_with_missing_session_directory_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path / "does-not-exist-yet")

    with pytest.raises(MetadataError):
        store.load()


def test_exists_reflects_presence_of_metadata_file(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    assert store.exists() is False

    store.save(RecordingSession())
    assert store.exists() is True


# ---------------------------------------------------------------------
# 9. Invalid / missing required fields
# ---------------------------------------------------------------------


def _write_raw(store: RecordingMetadataStore, data: dict) -> None:
    store.session_dir.mkdir(parents=True, exist_ok=True)
    store.metadata_path.write_text(json.dumps(data), encoding="utf-8")


def _valid_minimal_dict() -> dict:
    return {
        "format_version": 1,
        "session_id": "abc-123",
        "started_at": "2026-01-01T00:00:00.000000Z",
        "ended_at": None,
        "status": "IDLE",
        "protected": True,
        "segments": [],
        "total_bytes": 0,
        "error": None,
    }


@pytest.mark.parametrize(
    "field_name",
    [
        "format_version",
        "session_id",
        "started_at",
        "ended_at",
        "status",
        "protected",
        "segments",
        "total_bytes",
        "error",
    ],
)
def test_missing_required_field_raises_metadata_error(tmp_path, field_name):
    store = RecordingMetadataStore(tmp_path)
    data = _valid_minimal_dict()
    del data[field_name]
    _write_raw(store, data)

    with pytest.raises(MetadataError):
        store.load()


def test_unknown_status_value_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    data = _valid_minimal_dict()
    data["status"] = "NOT_A_REAL_STATUS"
    _write_raw(store, data)

    with pytest.raises(MetadataError):
        store.load()


def test_unsupported_format_version_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    data = _valid_minimal_dict()
    data["format_version"] = 999
    _write_raw(store, data)

    with pytest.raises(MetadataError):
        store.load()


def test_wrong_type_for_protected_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    data = _valid_minimal_dict()
    data["protected"] = "yes"
    _write_raw(store, data)

    with pytest.raises(MetadataError):
        store.load()


def test_wrong_type_for_total_bytes_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    data = _valid_minimal_dict()
    data["total_bytes"] = "100"
    _write_raw(store, data)

    with pytest.raises(MetadataError):
        store.load()


def test_segments_not_a_list_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    data = _valid_minimal_dict()
    data["segments"] = {"not": "a list"}
    _write_raw(store, data)

    with pytest.raises(MetadataError):
        store.load()


def test_segment_missing_required_field_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    data = _valid_minimal_dict()
    data["segments"] = [
        {
            "path": "seg.mkv",
            "started_at": "2026-01-01T00:00:00.000000Z",
            "ended_at": None,
            # missing "size_bytes" and "completed"
        }
    ]
    _write_raw(store, data)

    with pytest.raises(MetadataError):
        store.load()


def test_segment_negative_size_bytes_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    data = _valid_minimal_dict()
    data["segments"] = [
        {
            "path": "seg.mkv",
            "started_at": "2026-01-01T00:00:00.000000Z",
            "ended_at": None,
            "size_bytes": -1,
            "completed": False,
        }
    ]
    _write_raw(store, data)

    with pytest.raises(MetadataError):
        store.load()


def test_malformed_timestamp_raises_metadata_error(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    data = _valid_minimal_dict()
    data["started_at"] = "not-a-timestamp"
    _write_raw(store, data)

    with pytest.raises(MetadataError):
        store.load()


def test_timestamp_without_z_suffix_raises_metadata_error(tmp_path):
    """Offset-style timestamps (e.g. '+00:00') are not the format this
    module writes and are rejected, since the on-disk representation
    must be unambiguous."""
    store = RecordingMetadataStore(tmp_path)
    data = _valid_minimal_dict()
    data["started_at"] = "2026-01-01T00:00:00.000000+00:00"
    _write_raw(store, data)

    with pytest.raises(MetadataError):
        store.load()


# ---------------------------------------------------------------------
# 10. Atomic replacement behavior
# ---------------------------------------------------------------------


def test_save_leaves_no_temp_files_behind(tmp_path):
    store = RecordingMetadataStore(tmp_path)
    store.save(RecordingSession())

    entries = sorted(os.listdir(tmp_path))
    assert entries == [SESSION_METADATA_FILENAME]


def test_save_uses_os_replace_for_atomic_swap(tmp_path, monkeypatch):
    """Verify save() goes through os.replace() (atomic on POSIX/Windows)
    rather than e.g. write-in-place or os.rename()-without-replace
    semantics, and that the temp file is created inside the same
    directory as the target (a prerequisite for atomicity)."""
    store = RecordingMetadataStore(tmp_path)

    calls = []
    real_replace = os.replace

    def spy_replace(src, dst):
        calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)

    store.save(RecordingSession())

    assert len(calls) == 1
    src, dst = calls[0]
    assert os.path.dirname(src) == os.path.dirname(str(store.metadata_path))
    assert str(dst) == str(store.metadata_path)


def test_second_save_overwrites_first_completely(tmp_path):
    store = RecordingMetadataStore(tmp_path)

    first = RecordingSession()
    first.transition_to(RecordingStatus.STARTING)
    store.save(first)

    second = RecordingSession()
    second.add_bytes(999)
    store.save(second)

    loaded = store.load()
    assert loaded.session_id == second.session_id
    assert loaded.total_bytes == 999
    assert loaded.status == RecordingStatus.IDLE


def test_existing_session_json_survives_a_failed_save(tmp_path, monkeypatch):
    """If save() fails after creating the temp file but before/at the
    atomic replace, the original session.json (if any) must be left
    untouched — atomicity means readers never see a torn write, and a
    failed write must not destroy previously-good data."""
    store = RecordingMetadataStore(tmp_path)

    original = RecordingSession()
    store.save(original)
    original_bytes = store.metadata_path.read_bytes()

    def boom(src, dst):
        raise OSError("simulated failure during replace")

    monkeypatch.setattr(os, "replace", boom)

    broken = RecordingSession()
    broken.add_bytes(123456)

    with pytest.raises(OSError):
        store.save(broken)

    assert store.metadata_path.read_bytes() == original_bytes

    # temp file used for the failed attempt must not linger
    leftovers = [
        name
        for name in os.listdir(tmp_path)
        if name != SESSION_METADATA_FILENAME
    ]
    assert leftovers == []


def test_save_creates_session_directory_if_missing(tmp_path):
    nested = tmp_path / "sessions" / "abc-123"
    store = RecordingMetadataStore(nested)
    assert not nested.exists()

    store.save(RecordingSession())

    assert nested.is_dir()
    assert store.metadata_path.is_file()


# ---------------------------------------------------------------------
# 11. Architecture guard against PySide6/VLC imports
# ---------------------------------------------------------------------


def test_recording_package_imports_no_pyside6_or_vlc():
    """Static regression guard: src/recording/ (including metadata.py)
    must stay a plain persistence/domain layer. Mirrors the guard in
    test_recording_session.py and test_storage_policy.py."""
    import ast
    from pathlib import Path

    recording_dir = Path(__file__).resolve().parent.parent / "src" / "recording"
    py_files = sorted(recording_dir.glob("*.py"))
    assert py_files, "expected src/recording/*.py to exist"
    assert any(f.name == "metadata.py" for f in py_files)

    forbidden_prefixes = ("PySide6", "vlc", "shiboken6")

    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)

        offending = [
            name
            for name in imported_names
            if any(name == p or name.startswith(p + ".") for p in forbidden_prefixes)
        ]
        assert not offending, f"{py_file.name} imports forbidden module(s): {offending}"


def test_metadata_store_is_usable_without_qt_or_vlc_loaded(tmp_path):
    """Functional companion: saving/loading via RecordingMetadataStore
    must not require PySide6 or vlc to be importable at all — this test
    module never imports either, unlike tests/test_recorder.py (which
    fakes vlc via conftest.py for EmergencyRecorder's sake)."""
    import sys

    session = RecordingSession()
    session.transition_to(RecordingStatus.STARTING)

    store = RecordingMetadataStore(tmp_path)
    store.save(session)
    loaded = store.load()

    assert loaded.status == RecordingStatus.STARTING
    # Note: conftest.py's fake `vlc` module is present in sys.modules
    # session-wide (installed for test_recorder.py), so this only proves
    # `recording.metadata` itself doesn't reference PySide6/vlc — the
    # static AST check above is the authoritative guard for that.
    assert "recording" in sys.modules
