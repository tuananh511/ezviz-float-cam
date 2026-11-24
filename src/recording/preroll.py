"""
recording/preroll.py — logic THUẦN (stdlib) cho "ghi đoạn TRƯỚC chuyển động".

Cách làm: một phiên libVLC riêng chạy LIÊN TỤC ghi luồng nhẹ (sub) vào một
thư mục đệm tạm bằng bộ cắt đoạn kiểu HLS của VLC (`access=livehttp`): cứ
`SEG_LEN_S` giây ra một file `seg-########.ts`, VLC tự xoá đoạn cũ để chỉ giữ
vài đoạn mới nhất. Khi phát hiện chuyển động, các đoạn gần nhất được ghép lại
(file MPEG-TS ghép nối vẫn hợp lệ) thành một file "trước chuyển động" đặt
trong thư mục phiên ghi.

Module này không đụng tới VLC/Qt: chỉ dựng chuỗi sout, chọn đoạn, ghép file
và dọn thư mục đệm — để test được không cần camera.
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Iterable, List, Union

__all__ = [
    "SEG_LEN_S",
    "TS_PACKET",
    "SEGMENT_GLOB",
    "num_segments_for",
    "build_buffer_sout",
    "list_segments",
    "select_recent_segments",
    "read_clip",
    "clear_buffer_dir",
]

SEG_LEN_S = 2          # độ dài mỗi đoạn đệm (VLC cắt theo khung hình chính nên có thể dài hơn chút)
TS_PACKET = 188        # kích thước 1 gói MPEG-TS; chỉ ghép tới biên gói để file luôn hợp lệ
SEGMENT_GLOB = "seg-*.ts"
_SEG_RE = re.compile(r"^seg-\d+\.ts$")


def num_segments_for(pre_roll_s: float, seg_len_s: int = SEG_LEN_S) -> int:
    """Số đoạn VLC cần giữ lại để chắc chắn phủ được `pre_roll_s` giây
    (dư vài đoạn cho đoạn đang ghi dở và đoạn bị cắt dài hơn dự kiến)."""
    return max(3, math.ceil(pre_roll_s / seg_len_s) + 3)


def build_buffer_sout(buffer_dir: Union[str, os.PathLike], pre_roll_s: float) -> str:
    """Chuỗi `:sout=...` cho VLC. Đường dẫn LUÔN được đặt trong dấu nháy kép
    (thư mục tạm của Windows có thể chứa dấu cách) và dùng "/" thay cho dấu gạch ngược."""
    d = str(buffer_dir).replace("\\", "/").rstrip("/")
    n = num_segments_for(pre_roll_s)
    return (
        "#std{access=livehttp{"
        f"seglen={SEG_LEN_S},numsegs={n},delsegs=true,"
        f'index="{d}/index.m3u8",index-url=seg-########.ts'
        "},mux=ts{use-key-frames},"
        f'dst="{d}/seg-########.ts"'
        "}"
    )


def list_segments(buffer_dir: Union[str, os.PathLike]) -> List[Path]:
    """Các file đoạn đệm, cũ -> mới (tên tăng dần theo số thứ tự)."""
    d = Path(buffer_dir)
    if not d.is_dir():
        return []
    return sorted(
        (p for p in d.iterdir() if _SEG_RE.match(p.name) and p.is_file()),
        key=lambda p: p.name,
    )


def select_recent_segments(
    segments: Iterable[Path], pre_roll_s: float, seg_len_s: int = SEG_LEN_S,
) -> List[Path]:
    """Chọn các đoạn mới nhất đủ phủ `pre_roll_s` giây. Bỏ qua đoạn rỗng
    (đoạn VLC đang mở nhưng chưa ghi gì)."""
    non_empty = []
    for p in segments:
        try:
            if p.stat().st_size > 0:
                non_empty.append(p)
        except OSError:
            continue
    need = max(1, math.ceil(pre_roll_s / seg_len_s))
    return non_empty[-need:]


def read_clip(paths: Iterable[Union[str, os.PathLike]]) -> bytes:
    """Đọc và ghép các đoạn thành MỘT khối bytes MPEG-TS hợp lệ.

    Mỗi đoạn được cắt về bội số 188 byte (đoạn đang ghi dở có thể dừng giữa
    chừng một gói). Đoạn bị VLC xoá giữa chừng thì bỏ qua. Đọc hết vào RAM
    ngay để không bị VLC xoá file khi đang chép (clip vài giây luồng nhẹ chỉ
    cỡ vài trăm KB — vài MB).
    """
    chunks = []
    for p in paths:
        try:
            data = Path(p).read_bytes()
        except OSError:
            continue
        data = data[: len(data) // TS_PACKET * TS_PACKET]
        if data:
            chunks.append(data)
    return b"".join(chunks)


def clear_buffer_dir(buffer_dir: Union[str, os.PathLike]) -> int:
    """Xoá file đệm (seg-*.ts, index.m3u8) còn sót (vd lần chạy trước bị tắt
    đột ngột). Chỉ xoá đúng các file do bộ đệm tạo. Trả về số file đã xoá."""
    d = Path(buffer_dir)
    if not d.is_dir():
        return 0
    removed = 0
    for p in d.iterdir():
        if p.is_file() and (_SEG_RE.match(p.name) or p.name == "index.m3u8"):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed
