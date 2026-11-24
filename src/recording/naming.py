"""
recording/naming.py — quy ước đặt tên thư mục/file ghi hình (dễ đọc).

Stdlib-only, không I/O (trừ `unique_session_name` chỉ kiểm tra thư mục đã
tồn tại chưa). Tên thư mục phiên cũng chính là `session_id` trong
session.json, nên mở file nào cũng thấy cùng một cái tên dễ hiểu:

    2026-11-22_14-30-05_TuDong     ghi TỰ ĐỘNG khi có chuyển động
    2026-11-22_14-30-05_ThuCong    ghi THỦ CÔNG (nút REC)

Dùng chữ không dấu (ASCII) cho tên thư mục: libVLC ghi file qua chuỗi
`sout` nên đường dẫn có dấu/khoảng trắng dễ gây lỗi trên Windows.

Tương thích ngược: thư mục kiểu cũ `emergency_<uuid>/` (ghi tay) và
`emergency_motion_<uuid>/` (ghi tự động, bản thử trước) vẫn được nhận ra.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

__all__ = [
    "KIND_MANUAL",
    "KIND_AUTO",
    "LEGACY_PREFIX",
    "LEGACY_MOTION_PREFIX",
    "make_session_name",
    "unique_session_name",
    "make_segment_name",
    "is_session_dir_name",
    "is_legacy_motion_dir_name",
    "PRE_ROLL_FILENAME",
]

# Đoạn ghi TRƯỚC khi phát hiện chuyển động (nếu bật "pre-roll"): một file
# MPEG-TS nằm đầu thư mục phiên (tên bắt đầu bằng "00-" nên xếp trước các đoạn
# .mkv đặt theo giờ).
PRE_ROLL_FILENAME = "00-truoc-chuyen-dong.ts"

KIND_MANUAL = "manual"
KIND_AUTO = "auto"

_KIND_LABELS = {KIND_MANUAL: "ThuCong", KIND_AUTO: "TuDong"}

LEGACY_PREFIX = "emergency_"
LEGACY_MOTION_PREFIX = "emergency_motion_"

_NEW_NAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(TuDong|ThuCong)(_\d+)?$"
)


def make_session_name(kind: str, when: datetime) -> str:
    """Tên thư mục phiên, vd '2026-11-22_14-30-05_TuDong' (giờ địa phương)."""
    label = _KIND_LABELS.get(kind)
    if label is None:
        raise ValueError(f"kind không hợp lệ: {kind!r}")
    return f"{when.strftime('%Y-%m-%d_%H-%M-%S')}_{label}"


def unique_session_name(base_dir: Union[str, Path], kind: str, when: datetime) -> str:
    """Như make_session_name() nhưng thêm hậu tố _2, _3... nếu thư mục đã có
    (hiếm: hai phiên cùng loại bắt đầu trong cùng một giây)."""
    base = Path(base_dir)
    name = make_session_name(kind, when)
    candidate, n = name, 2
    while (base / candidate).exists():
        candidate = f"{name}_{n}"
        n += 1
    return candidate


def make_segment_name(when: datetime) -> str:
    """Tên file đoạn ghi, vd '14-30-05.mkv' (nằm trong thư mục phiên đã có
    ngày, nên không cần lặp lại ngày)."""
    return f"{when.strftime('%H-%M-%S')}.mkv"


def is_legacy_motion_dir_name(name: str) -> bool:
    return name.startswith(LEGACY_MOTION_PREFIX)


def is_session_dir_name(name: str) -> bool:
    """True nếu `name` là tên thư mục phiên ghi hình (kiểu mới hoặc cũ)."""
    return name.startswith(LEGACY_PREFIX) or bool(_NEW_NAME_RE.match(name))
