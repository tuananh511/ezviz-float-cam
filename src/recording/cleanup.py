"""
recording/cleanup.py — tự xoá bản ghi cũ khi thư mục ghi hình vượt ngưỡng.

Stdlib-only (không PySide6/vlc). Nối `retention.is_eligible_for_cleanup`
(policy "phiên nào được phép xoá") với việc quét thư mục + xoá thật.

Quy tắc an toàn (đây là code XOÁ FILE, nên chặt tay):
- Chỉ đụng tới các thư mục phiên ghi hình nhận ra được theo tên
  (`naming.is_session_dir_name`) nằm TRỰC TIẾP dưới thư mục lưu; thư mục/file
  lạ người dùng để chung được bỏ qua hoàn toàn (không tính dung lượng, không xoá).
- Chỉ xoá phiên có session.json ĐỌC ĐƯỢC, trạng thái kết thúc (STOPPED/FAILED/
  DISK_FULL), `protected=False`. Ghi THỦ CÔNG luôn `protected=True` nên
  không bao giờ bị xoá. Thư mục không có/hỏng session.json -> bỏ qua.
- Phiên đang ghi (do app truyền vào `exclude_dirs`) không bao giờ bị xoá.
- Chỉ xoá đúng các file do app tạo (*.mkv, session.json, thong-tin.txt, file
  tạm của session.json) rồi `rmdir` nếu thư mục rỗng; nếu còn file lạ thì
  để lại thư mục, không xoá đệ quy.
- Xoá từ phiên CŨ NHẤT trước, và dừng ngay khi đã xuống dưới mục tiêu.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Union

from .metadata import MetadataError, RecordingMetadataStore, SESSION_METADATA_FILENAME
from .naming import is_legacy_motion_dir_name, is_session_dir_name
from .retention import RetentionCriteria, is_eligible_for_cleanup
from .session import RecordingSession
from .summary import SUMMARY_FILENAME

__all__ = [
    "DEFAULT_MAX_GB",
    "MIN_MAX_GB",
    "MAX_MAX_GB",
    "TARGET_RATIO",
    "get_retention_config",
    "SessionEntry",
    "CleanupPlan",
    "CleanupReport",
    "scan_sessions",
    "plan_cleanup",
    "delete_session_dir",
    "run_cleanup",
    "summarize_usage",
]

DEFAULT_MAX_GB = 20
MIN_MAX_GB = 1
MAX_MAX_GB = 5000

# Khi vượt ngưỡng, xoá xuống còn ~90% ngưỡng (không phải sát 100%) để không
# phải xoá lắt nhắt một bản mỗi phút khi đang ghi.
TARGET_RATIO = 0.9

_GB = 1024 ** 3


# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------


def get_retention_config(config: Optional[dict]) -> dict:
    """Cấu hình tự xoá đã hợp lệ hoá từ `config["retention"]` (có thể thiếu)."""
    raw = (config or {}).get("retention")
    if not isinstance(raw, dict):
        raw = {}
    enabled = bool(raw.get("enabled", True))
    try:
        max_gb = int(raw.get("max_gb", DEFAULT_MAX_GB))
    except (TypeError, ValueError):
        max_gb = DEFAULT_MAX_GB
    max_gb = max(MIN_MAX_GB, min(MAX_MAX_GB, max_gb))
    return {"enabled": enabled, "max_gb": max_gb}


# ---------------------------------------------------------------------------
# Quét
# ---------------------------------------------------------------------------


@dataclass
class SessionEntry:
    path: Path
    size_bytes: int                      # dung lượng THẬT trên đĩa (các file app tạo)
    sort_time: datetime                  # để xếp cũ -> mới
    session: Optional[RecordingSession]  # None nếu không đọc được session.json
    deletable: bool = False              # đủ điều kiện bị xoá theo quy tắc ở đầu file


_OWN_SUFFIXES = (".mkv",)
_OWN_NAMES = (SESSION_METADATA_FILENAME, SUMMARY_FILENAME)


def _is_own_file(p: Path) -> bool:
    if not p.is_file() or p.is_symlink():
        return False
    return (
        p.suffix.lower() in _OWN_SUFFIXES
        or p.name in _OWN_NAMES
        or (p.name.startswith(".session.json.") and p.name.endswith(".tmp"))
    )


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for p in path.iterdir():
            if _is_own_file(p):
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _sort_time(path: Path, session: Optional[RecordingSession]) -> datetime:
    if session is not None:
        return session.started_at
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.max.replace(tzinfo=timezone.utc)


def scan_sessions(base_dir: Union[str, os.PathLike], *, now: Optional[datetime] = None) -> List[SessionEntry]:
    """Liệt kê các thư mục phiên ghi hình trực tiếp dưới base_dir, cũ nhất
    trước. Không xoá/sửa gì."""
    base = Path(base_dir)
    if not base.is_dir():
        return []
    now = now or datetime.now(timezone.utc)
    criteria = RetentionCriteria(older_than=now)

    entries: List[SessionEntry] = []
    for d in base.iterdir():
        if not d.is_dir() or d.is_symlink() or not is_session_dir_name(d.name):
            continue
        session: Optional[RecordingSession]
        try:
            session = RecordingMetadataStore(d).load()
        except (MetadataError, OSError):
            session = None

        deletable = False
        if session is not None:
            effective = session
            if is_legacy_motion_dir_name(d.name) and session.protected:
                # Bản thử trước của tính năng này tạo thư mục emergency_motion_*
                # với protected=True do mặc định; chúng là ghi TỰ ĐỘNG nên coi
                # là xoá được.
                effective = replace(session, protected=False)
            deletable = is_eligible_for_cleanup(effective, criteria)

        entries.append(SessionEntry(
            path=d, size_bytes=_dir_size(d), sort_time=_sort_time(d, session),
            session=session, deletable=deletable,
        ))
    entries.sort(key=lambda e: (e.sort_time, e.path.name))
    return entries


# ---------------------------------------------------------------------------
# Kế hoạch (thuần, dễ test)
# ---------------------------------------------------------------------------


@dataclass
class CleanupPlan:
    total_bytes: int
    max_bytes: int
    to_delete: List[SessionEntry] = field(default_factory=list)
    expected_total_bytes: int = 0
    unresolved: bool = False   # đã xoá hết cái được phép mà vẫn vượt ngưỡng


def plan_cleanup(
    entries: Iterable[SessionEntry],
    max_bytes: int,
    *,
    exclude_dirs: Iterable[Union[str, os.PathLike]] = (),
    target_ratio: float = TARGET_RATIO,
) -> CleanupPlan:
    """Chọn các phiên cần xoá (cũ nhất trước). Không I/O."""
    entries = list(entries)
    excluded = {Path(p) for p in exclude_dirs}
    total = sum(e.size_bytes for e in entries)
    plan = CleanupPlan(total_bytes=total, max_bytes=max_bytes, expected_total_bytes=total)
    if total <= max_bytes:
        return plan

    target = int(max_bytes * target_ratio)
    remaining = total
    for e in sorted(entries, key=lambda x: (x.sort_time, x.path.name)):
        if remaining <= target:
            break
        if not e.deletable or e.path in excluded:
            continue
        plan.to_delete.append(e)
        remaining -= e.size_bytes
    plan.expected_total_bytes = remaining
    plan.unresolved = remaining > max_bytes
    return plan


# ---------------------------------------------------------------------------
# Xoá
# ---------------------------------------------------------------------------


def delete_session_dir(path: Union[str, os.PathLike]) -> int:
    """Xoá các file do app tạo trong thư mục phiên rồi rmdir nếu rỗng. Trả về
    số byte đã giải phóng. Không đệ quy, không xoá file lạ."""
    p = Path(path)
    freed = 0
    for f in list(p.iterdir()):
        if _is_own_file(f):
            try:
                size = f.stat().st_size
                f.unlink()
                freed += size
            except OSError:
                pass
    try:
        p.rmdir()
    except OSError:
        pass  # còn file lạ hoặc file đang bị khoá — để lại, không ép xoá
    return freed


@dataclass
class CleanupReport:
    total_before: int = 0
    total_after: int = 0
    deleted: List[str] = field(default_factory=list)
    freed_bytes: int = 0
    unresolved: bool = False
    errors: List[str] = field(default_factory=list)


def run_cleanup(
    base_dir: Union[str, os.PathLike],
    max_bytes: int,
    *,
    exclude_dirs: Iterable[Union[str, os.PathLike]] = (),
    now: Optional[datetime] = None,
) -> CleanupReport:
    """Quét base_dir, nếu tổng dung lượng các phiên vượt max_bytes thì xoá
    dần phiên cũ nhất được phép xoá. Không bao giờ raise vì một phiên lỗi."""
    entries = scan_sessions(base_dir, now=now)
    plan = plan_cleanup(entries, max_bytes, exclude_dirs=exclude_dirs)
    report = CleanupReport(total_before=plan.total_bytes, total_after=plan.total_bytes)

    for entry in plan.to_delete:
        try:
            freed = delete_session_dir(entry.path)
        except OSError as exc:
            report.errors.append(f"{entry.path.name}: {exc}")
            continue
        report.deleted.append(entry.path.name)
        report.freed_bytes += freed
    report.total_after = max(0, plan.total_bytes - report.freed_bytes)
    report.unresolved = report.total_after > max_bytes
    return report


# ---------------------------------------------------------------------------
# Thống kê cho giao diện Cài đặt
# ---------------------------------------------------------------------------


def summarize_usage(base_dir: Union[str, os.PathLike]) -> dict:
    """{'total', 'auto', 'protected', 'sessions'} (byte) — để hiển thị mức dùng
    hiện tại trong Cài đặt. 'auto' = phần có thể bị tự xoá."""
    entries = scan_sessions(base_dir)
    auto = sum(e.size_bytes for e in entries if e.deletable)
    total = sum(e.size_bytes for e in entries)
    return {"total": total, "auto": auto, "protected": total - auto, "sessions": len(entries)}
