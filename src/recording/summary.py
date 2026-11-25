"""
recording/summary.py — file ghi chú dễ đọc `thong-tin.txt` trong mỗi thư mục
phiên ghi hình (tiếng Việt, giờ địa phương).

session.json là file máy đọc (dùng cho khôi phục sau crash) — vẫn giữ
nguyên. File này chỉ để NGƯỜI mở ra xem nhanh: ghi lúc nào, bao lâu, dung
lượng bao nhiêu, gồm những đoạn nào, có bị tự xoá khi đầy dung lượng không.

Stdlib-only. `write_summary()` không bao giờ raise: lỗi ghi file ghi chú
không được phép ảnh hưởng tới việc ghi hình.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Union

from .session import RecordingSession, RecordingStatus

__all__ = ["SUMMARY_FILENAME", "format_size", "format_duration", "build_summary", "write_summary"]

SUMMARY_FILENAME = "thong-tin.txt"

_STATUS_TEXT = {
    RecordingStatus.IDLE: "Chưa bắt đầu",
    RecordingStatus.STARTING: "Đang khởi động",
    RecordingStatus.RECORDING: "Đang ghi...",
    RecordingStatus.STOPPING: "Đang dừng",
    RecordingStatus.STOPPED: "Hoàn tất",
    RecordingStatus.FAILED: "Bị gián đoạn (file vẫn xem được, có thể thiếu vài giây cuối)",
    RecordingStatus.DISK_FULL: "Dừng vì ổ đĩa đầy",
    RecordingStatus.RECOVERABLE: "Đã khôi phục",
}


def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024.0
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} giờ {m} phút {s} giây"
    if m:
        return f"{m} phút {s} giây"
    return f"{s} giây"


def _local(dt: datetime) -> str:
    return dt.astimezone().strftime("%d/%m/%Y %H:%M:%S")


def build_summary(session: RecordingSession, kind_title: str) -> str:
    lines = [kind_title, "=" * len(kind_title), ""]
    lines.append(f"Bắt đầu   : {_local(session.started_at)}")
    if session.ended_at is not None:
        lines.append(f"Kết thúc  : {_local(session.ended_at)}")
        lines.append(
            "Thời lượng: "
            + format_duration((session.ended_at - session.started_at).total_seconds())
        )
    else:
        lines.append("Kết thúc  : (đang ghi hoặc chưa kết thúc)")

    done_bytes = sum(s.size_bytes for s in session.segments if s.completed)
    lines.append(f"Dung lượng: {format_size(done_bytes)}")
    lines.append(f"Trạng thái: {_STATUS_TEXT.get(session.status, session.status.value)}")
    if session.error:
        lines.append(f"Ghi chú lỗi: {session.error}")
    if session.protected:
        lines.append("Bảo vệ    : CÓ — không bao giờ bị tự xoá")
    else:
        lines.append("Bảo vệ    : không — sẽ bị tự xoá (bản cũ nhất trước) khi thư mục ghi hình đầy")

    lines += ["", "Các đoạn video:"]
    if not session.segments:
        lines.append("  (chưa có)")
    for i, seg in enumerate(session.segments, 1):
        name = Path(seg.path).name
        if seg.completed and seg.ended_at is not None:
            dur = format_duration((seg.ended_at - seg.started_at).total_seconds())
            lines.append(f"  {i}. {name}  ({dur}, {format_size(seg.size_bytes)})")
        else:
            lines.append(f"  {i}. {name}  (đang ghi hoặc chưa hoàn tất)")
    lines.append("")
    return "\n".join(lines)


def write_summary(session_dir: Union[str, os.PathLike], session: RecordingSession, kind_title: str) -> bool:
    """Ghi thong-tin.txt (UTF-8 có BOM để Notepad hiển thị đúng tiếng Việt).
    Trả về True nếu ghi được; không bao giờ raise."""
    try:
        path = Path(session_dir) / SUMMARY_FILENAME
        path.write_text(build_summary(session, kind_title), encoding="utf-8-sig")
        return True
    except Exception:  # noqa: BLE001 — ghi chú phụ, không được chặn ghi hình
        return False
