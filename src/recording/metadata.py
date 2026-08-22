"""
recording/metadata.py — session.json persistence for RecordingSession
(Task 6 of the Player/Recorder migration).

Like session.py and storage.py, this module is a deliberately plain
persistence layer:

- standard library only (json, os, dataclasses, datetime, enum, pathlib)
- no PySide6, no vlc
- no filesystem dependency outside this module's own save()/load() —
  callers decide where the session directory lives
- does NOT wire into EmergencyRecorder — that is a later task

save() writes `session.json` inside a given session directory. To avoid
ever leaving a half-written session.json behind (crash mid-write, power
loss, etc.), save() writes to a temporary file in the SAME directory
first, flushes and closes it, then atomically replaces session.json
with os.replace() — on POSIX and Windows alike, os.replace() is atomic
when source and destination are on the same filesystem, which is
guaranteed here because the temp file is created next to the target.

load() is intentionally strict: malformed JSON, a missing file, or a
metadata document missing/mistyping a required field all raise a clear,
specific exception. This module does not attempt to silently repair or
default-fill a broken session.json — a corrupt metadata file is a signal
that something went wrong and should be surfaced, not papered over.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union

from .session import RecordingSegment, RecordingSession, RecordingStatus

__all__ = [
    "RecordingMetadataStore",
    "MetadataError",
    "SESSION_METADATA_FILENAME",
]

SESSION_METADATA_FILENAME = "session.json"

# session.json format version. Bumped only if the on-disk shape changes
# in a way that would require load() to branch on it; today there is
# exactly one shape.
_FORMAT_VERSION = 1


class MetadataError(ValueError):
    """Raised when session.json is missing, malformed, or fails to
    describe a valid RecordingSession/RecordingSegment. Never raised to
    mean "recovered anyway" — this module does not silently repair
    broken metadata."""


# ---------------------------------------------------------------------
# datetime <-> str
# ---------------------------------------------------------------------
#
# RecordingSession/RecordingSegment always use timezone-aware UTC
# datetimes (see session.py's _utcnow()). To keep that guarantee across
# a JSON round-trip — where JSON has no native datetime type — every
# datetime is serialized as an ISO 8601 string with an explicit "Z" UTC
# suffix (e.g. "2026-08-22T07:25:32.460729Z"), never a naive/offset-less
# string and never a "+00:00" spelling, so the representation is
# unambiguous both to read and to grep for in a raw session.json.


def _dt_to_str(value: datetime) -> str:
    if value.tzinfo is None:
        raise MetadataError(
            "cannot serialize a naive datetime — RecordingSession/"
            "RecordingSegment datetimes must be timezone-aware UTC"
        )
    as_utc = value.astimezone(timezone.utc)
    return as_utc.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _str_to_dt(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise MetadataError(
            f"field {field_name!r} must be a UTC ISO 8601 string ending in "
            f"'Z', got {value!r}"
        )
    body = value[:-1]
    try:
        naive = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S.%f")
    except ValueError:
        try:
            naive = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S")
        except ValueError as exc:
            raise MetadataError(
                f"field {field_name!r} is not a valid UTC ISO 8601 "
                f"timestamp: {value!r}"
            ) from exc
    return naive.replace(tzinfo=timezone.utc)


def _optional_str_to_dt(value: Any, *, field_name: str) -> Union[datetime, None]:
    if value is None:
        return None
    return _str_to_dt(value, field_name=field_name)


# ---------------------------------------------------------------------
# RecordingSegment <-> dict
# ---------------------------------------------------------------------

_SEGMENT_REQUIRED_FIELDS = ("path", "started_at", "ended_at", "size_bytes", "completed")


def _segment_to_dict(segment: RecordingSegment) -> dict:
    return {
        "path": segment.path,
        "started_at": _dt_to_str(segment.started_at),
        "ended_at": _dt_to_str(segment.ended_at) if segment.ended_at is not None else None,
        "size_bytes": segment.size_bytes,
        "completed": segment.completed,
    }


def _segment_from_dict(data: Any, *, index: int) -> RecordingSegment:
    if not isinstance(data, dict):
        raise MetadataError(f"segments[{index}] must be an object, got {type(data).__name__}")

    for field_name in _SEGMENT_REQUIRED_FIELDS:
        if field_name not in data:
            raise MetadataError(f"segments[{index}] is missing required field {field_name!r}")

    path = data["path"]
    if not isinstance(path, str):
        raise MetadataError(f"segments[{index}].path must be a string, got {type(path).__name__}")

    size_bytes = data["size_bytes"]
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
        raise MetadataError(
            f"segments[{index}].size_bytes must be an int, got {type(size_bytes).__name__}"
        )
    if size_bytes < 0:
        raise MetadataError(f"segments[{index}].size_bytes must be non-negative, got {size_bytes}")

    completed = data["completed"]
    if not isinstance(completed, bool):
        raise MetadataError(
            f"segments[{index}].completed must be a bool, got {type(completed).__name__}"
        )

    started_at = _str_to_dt(data["started_at"], field_name=f"segments[{index}].started_at")
    ended_at = _optional_str_to_dt(data["ended_at"], field_name=f"segments[{index}].ended_at")

    return RecordingSegment(
        path=path,
        started_at=started_at,
        ended_at=ended_at,
        size_bytes=size_bytes,
        completed=completed,
    )


# ---------------------------------------------------------------------
# RecordingSession <-> dict
# ---------------------------------------------------------------------

_SESSION_REQUIRED_FIELDS = (
    "format_version",
    "session_id",
    "started_at",
    "ended_at",
    "status",
    "protected",
    "segments",
    "total_bytes",
    "error",
)


def _session_to_dict(session: RecordingSession) -> dict:
    return {
        "format_version": _FORMAT_VERSION,
        "session_id": session.session_id,
        "started_at": _dt_to_str(session.started_at),
        "ended_at": _dt_to_str(session.ended_at) if session.ended_at is not None else None,
        "status": session.status.value,
        "protected": session.protected,
        "segments": [_segment_to_dict(s) for s in session.segments],
        "total_bytes": session.total_bytes,
        "error": session.error,
    }


def _session_from_dict(data: Any) -> RecordingSession:
    if not isinstance(data, dict):
        raise MetadataError(f"session metadata must be a JSON object, got {type(data).__name__}")

    for field_name in _SESSION_REQUIRED_FIELDS:
        if field_name not in data:
            raise MetadataError(f"session metadata is missing required field {field_name!r}")

    format_version = data["format_version"]
    if format_version != _FORMAT_VERSION:
        raise MetadataError(
            f"unsupported session metadata format_version {format_version!r} "
            f"(expected {_FORMAT_VERSION})"
        )

    session_id = data["session_id"]
    if not isinstance(session_id, str) or not session_id:
        raise MetadataError(
            f"session_id must be a non-empty string, got {session_id!r}"
        )

    status_value = data["status"]
    try:
        status = RecordingStatus(status_value)
    except ValueError as exc:
        raise MetadataError(f"unknown status {status_value!r}") from exc

    protected = data["protected"]
    if not isinstance(protected, bool):
        raise MetadataError(f"protected must be a bool, got {type(protected).__name__}")

    total_bytes = data["total_bytes"]
    if not isinstance(total_bytes, int) or isinstance(total_bytes, bool):
        raise MetadataError(f"total_bytes must be an int, got {type(total_bytes).__name__}")
    if total_bytes < 0:
        raise MetadataError(f"total_bytes must be non-negative, got {total_bytes}")

    error = data["error"]
    if error is not None and not isinstance(error, str):
        raise MetadataError(f"error must be a string or null, got {type(error).__name__}")

    segments_data = data["segments"]
    if not isinstance(segments_data, list):
        raise MetadataError(f"segments must be a list, got {type(segments_data).__name__}")
    segments = [_segment_from_dict(s, index=i) for i, s in enumerate(segments_data)]

    started_at = _str_to_dt(data["started_at"], field_name="started_at")
    ended_at = _optional_str_to_dt(data["ended_at"], field_name="ended_at")

    return RecordingSession(
        session_id=session_id,
        started_at=started_at,
        ended_at=ended_at,
        status=status,
        protected=protected,
        segments=segments,
        total_bytes=total_bytes,
        error=error,
    )


# ---------------------------------------------------------------------
# RecordingMetadataStore
# ---------------------------------------------------------------------


class RecordingMetadataStore:
    """Minimal save/load persistence for one RecordingSession's
    session.json, inside a given session directory.

    This class holds no state of its own beyond the directory it is
    pointed at — it does not cache a session, watch the filesystem, or
    know anything about EmergencyRecorder. Each save()/load() call is a
    single, self-contained operation.
    """

    def __init__(self, session_dir: Union[str, os.PathLike]) -> None:
        self.session_dir = Path(session_dir)

    @property
    def metadata_path(self) -> Path:
        return self.session_dir / SESSION_METADATA_FILENAME

    def save(self, session: RecordingSession) -> Path:
        """Serialize `session` to session.json inside self.session_dir,
        using atomic replacement: write a temp file in the same
        directory, flush + close it, then os.replace() it over
        session.json. This guarantees session.json is either the
        previous complete content or the new complete content — never a
        partially-written file, even if the process is interrupted
        mid-write.

        Returns the path written to.
        """
        self.session_dir.mkdir(parents=True, exist_ok=True)
        payload = _session_to_dict(session)
        text = json.dumps(payload, indent=2, ensure_ascii=False)

        fd, tmp_name = tempfile.mkstemp(
            prefix=".session.json.",
            suffix=".tmp",
            dir=str(self.session_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self.metadata_path)
        except BaseException:
            # Best-effort cleanup of the temp file if the replace never
            # happened (e.g. an error before/at os.replace()).
            try:
                os.remove(tmp_name)
            except OSError:
                pass
            raise

        return self.metadata_path

    def load(self) -> RecordingSession:
        """Read and validate session.json from self.session_dir,
        returning a reconstructed RecordingSession.

        Raises MetadataError (a ValueError subclass) if the file is
        missing, is not valid JSON, or does not describe a valid
        RecordingSession/RecordingSegment. Never returns a partially
        or speculatively repaired session.
        """
        path = self.metadata_path
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise MetadataError(f"no session metadata found at {path}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MetadataError(f"session metadata at {path} is not valid JSON: {exc}") from exc

        return _session_from_dict(data)

    def exists(self) -> bool:
        return self.metadata_path.is_file()
