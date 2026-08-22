"""
recording/storage.py — Recording storage policy (Task 4 của migration
Player/Recorder).

Mục tiêu: bảo vệ đĩa khi ghi hình khẩn cấp chạy lâu (có thể kéo dài hàng
giờ, sinh nhiều RecordingSegment nối tiếp — xem SEGMENT_DURATION_S trong
src/recorder.py), bằng cách kiểm tra dung lượng trống TRƯỚC khi cho phép
tạo một đoạn ghi hình mới.

Cũng như recording/session.py, module này CHỦ Ý là một domain model
thuần túy:

- standard-library only (shutil, pathlib, dataclasses, enum)
- không PySide6, không vlc
- không tự xóa file/segment/session nào — StoragePolicy KHÔNG có bất kỳ
  method nào xóa dữ liệu. "Không bao giờ xóa segment của session đang
  active" được đảm bảo bằng cách không tồn tại khả năng xóa trong class
  này, chứ không phải bằng một điều kiện if-check có thể bị bỏ sót.
- không thêm auto-delete recording cũ (ngoài scope Task 4)
- không database, không JSON persistence, không background thread,
  không async

Việc gọi StoragePolicy trước mỗi lần recorder.py tạo segment mới (Task 3:
_start_segment/_rotate_segment) là việc của MỘT TASK SAU — ở đây chỉ cung
cấp chính sách (policy) và cách áp dụng nó lên một RecordingSession có
sẵn (apply_to_session), không đụng vào src/recorder.py.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from .session import RecordingSession, RecordingStatus

__all__ = [
    "StorageDecision",
    "StorageCheckResult",
    "DiskStatError",
    "StoragePolicy",
    "DEFAULT_MIN_FREE_BYTES",
    "DEFAULT_LOW_FREE_BYTES",
]


# ---------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------
#
# Cả hai threshold đều là SỐ BYTE TUYỆT ĐỐI (không phải phần trăm đĩa) —
# vì cái ta thực sự cần bảo vệ là "còn đủ chỗ cho (ít nhất) một đoạn ghi
# hình MKV nữa", và kích thước một đoạn không phụ thuộc dung lượng đĩa
# tổng (đĩa 256GB hay 4TB thì một đoạn 5 phút vẫn nặng như nhau).
#
# Cơ sở tính: SEGMENT_DURATION_S trong src/recorder.py = 300s (5 phút).
# remux MKV không transcode nên kích thước đoạn ~ bitrate luồng "main"
# camera Ezviz. Với luồng main chất lượng cao nhất thực tế gặp (~8 Mbps,
# 1080p H.264), một đoạn 5 phút nặng tối đa khoảng:
#     8_000_000 bit/s * 300s / 8 = 300_000_000 byte ≈ 286 MiB
#
# DEFAULT_MIN_FREE_BYTES = 1 GiB: ngưỡng "an toàn cứng" — dưới mức này
# thì KHÔNG được phép tạo đoạn mới (DISK_FULL), vì 1 GiB vẫn còn hơn 3
# lần kích thước một đoạn worst-case (~286 MiB), đủ dư để: (a) đoạn đang
# ghi dở kịp hoàn tất/flush trước khi bị dừng, và (b) chừa khoảng trống
# cho hệ điều hành/ứng dụng khác cùng ghi vào ổ đĩa đó trong lúc ta kiểm
# tra và lúc thật sự ghi (free space có thể giảm giữa hai thời điểm này).
#
# DEFAULT_LOW_FREE_BYTES = 2 GiB: ngưỡng "cảnh báo sớm" — dưới mức này
# (nhưng vẫn >= ngưỡng an toàn cứng) thì VẪN cho phép tạo đoạn mới
# (ALLOW_LOW_SPACE), nhưng caller (task sau, khi tích hợp vào recorder)
# có cơ sở để log cảnh báo/hiện thông báo cho người dùng — còn đủ chỗ
# cho khoảng 2-3 đoạn nữa trước khi chạm ngưỡng cứng.
#
# Hai hằng số này là NƠI DUY NHẤT định nghĩa threshold — StoragePolicy
# nhận chúng qua constructor (có thể override theo instance), không có
# số "1 GiB"/"2 GiB" nào bị hard-code rải rác ở nơi khác.

DEFAULT_MIN_FREE_BYTES: int = 1 * 1024 ** 3  # 1 GiB — ngưỡng an toàn cứng
DEFAULT_LOW_FREE_BYTES: int = 2 * 1024 ** 3  # 2 GiB — ngưỡng cảnh báo sớm


class StorageDecision(Enum):
    """Quyết định của StoragePolicy cho câu hỏi "có nên tạo đoạn ghi hình
    mới bây giờ không?"."""

    # Dung lượng trống dồi dào (>= ngưỡng cảnh báo sớm) — cứ tạo đoạn mới.
    ALLOW = "ALLOW"

    # Dung lượng trống ít (< ngưỡng cảnh báo sớm) nhưng vẫn >= ngưỡng an
    # toàn cứng — vẫn CHO PHÉP tạo đoạn mới, nhưng caller nên cảnh báo.
    ALLOW_LOW_SPACE = "ALLOW_LOW_SPACE"

    # Dung lượng trống dưới ngưỡng an toàn cứng — KHÔNG được tạo đoạn
    # mới. Tương ứng RecordingStatus.DISK_FULL.
    DISK_FULL = "DISK_FULL"

    # Không xác định được dung lượng trống (lỗi khi stat filesystem) —
    # đây LÀ MỘT TRẠNG THÁI RIÊNG, không bị gộp/ngầm hiểu là ALLOW hay
    # DISK_FULL. Caller quyết định cách xử lý (vd. coi như không an toàn
    # và không tạo đoạn mới), nhưng policy không tự ý quyết thay.
    CHECK_FAILED = "CHECK_FAILED"


class DiskStatError(Exception):
    """Bọc lại OSError gốc khi shutil.disk_usage() thất bại (đường dẫn
    không tồn tại ở bất kỳ ancestor nào, không có quyền, lỗi I/O, v.v.),
    để caller chỉ cần bắt MỘT loại exception bất kể nguyên nhân/platform.
    Exception gốc luôn được giữ lại qua `__cause__` (raise ... from exc)
    — không bao giờ bị nuốt."""


@dataclass(frozen=True)
class StorageCheckResult:
    """Kết quả của một lần StoragePolicy.check() — bất biến (frozen),
    dùng làm bằng chứng có thể log/test lại được."""

    decision: StorageDecision
    reason: str
    checked_path: Path
    free_bytes: Optional[int] = None
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    error: Optional[BaseException] = None

    def allows_new_segment(self) -> bool:
        """True nếu decision này cho phép tạo đoạn ghi hình mới.
        CHECK_FAILED KHÔNG cho phép — nếu không biết chắc còn đủ chỗ
        hay không, an toàn hơn là coi như KHÔNG được tạo đoạn mới."""
        return self.decision in (
            StorageDecision.ALLOW,
            StorageDecision.ALLOW_LOW_SPACE,
        )


class StoragePolicy:
    """Chính sách kiểm tra dung lượng đĩa trước khi cho phép tạo một
    RecordingSegment mới.

    KHÔNG giữ tham chiếu tới bất kỳ RecordingSession/RecordingSegment cụ
    thể nào — mỗi lần check() là một phép đo tức thời, độc lập, dựa trên
    filesystem chứa `recording_dir` tại thời điểm gọi.
    """

    def __init__(
        self,
        recording_dir: Union[str, Path],
        *,
        min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
        low_free_bytes: int = DEFAULT_LOW_FREE_BYTES,
    ) -> None:
        if min_free_bytes < 0:
            raise ValueError("min_free_bytes must be non-negative")
        if low_free_bytes < min_free_bytes:
            raise ValueError(
                "low_free_bytes must be >= min_free_bytes "
                f"(got low_free_bytes={low_free_bytes}, "
                f"min_free_bytes={min_free_bytes})"
            )
        self.recording_dir = Path(recording_dir)
        self.min_free_bytes = min_free_bytes
        self.low_free_bytes = low_free_bytes

    # ------------------------------------------------------------------
    # Kiểm tra dung lượng
    # ------------------------------------------------------------------

    def _existing_ancestor(self) -> Path:
        """recording_dir có thể CHƯA được tạo (vd. trước lần ghi hình
        đầu tiên, xem base_dir.mkdir() trong recorder.start()) — shutil
        .disk_usage() yêu cầu một đường dẫn tồn tại. Đi ngược lên các
        thư mục cha tới khi gặp một đường dẫn tồn tại, giống cách lệnh
        `df` xử lý một đường dẫn chưa được tạo."""
        candidate = self.recording_dir
        # Path.parents không lặp vô hạn: dừng ở root ('/' hoặc 'C:\\').
        for path in (candidate, *candidate.parents):
            if path.exists():
                return path
        # Trường hợp cực hiếm (vd. root cũng không "exists()" được, môi
        # trường filesystem lạ) — trả nguyên recording_dir và để
        # disk_usage() tự raise, không tự bịa một quyết định ở đây.
        return candidate

    def check(self) -> StorageCheckResult:
        """Đo dung lượng trống của filesystem chứa recording_dir và trả
        về quyết định tương ứng. Không bao giờ raise ra ngoài vì lỗi
        stat filesystem — lỗi đó là MỘT KẾT QUẢ hợp lệ (CHECK_FAILED),
        không phải một exception nuốt âm thầm: `error` trong kết quả
        luôn chứa exception gốc để caller/log xem lại được."""
        stat_path = self._existing_ancestor()
        try:
            usage = shutil.disk_usage(stat_path)
        except OSError as exc:
            wrapped = DiskStatError(
                f"Không kiểm tra được dung lượng đĩa cho "
                f"'{self.recording_dir}' (stat tại '{stat_path}'): {exc}"
            )
            wrapped.__cause__ = exc
            return StorageCheckResult(
                decision=StorageDecision.CHECK_FAILED,
                reason=str(wrapped),
                checked_path=stat_path,
                error=wrapped,
            )

        free = usage.free
        if free < self.min_free_bytes:
            decision = StorageDecision.DISK_FULL
            reason = (
                f"Dung lượng trống {free} byte < ngưỡng an toàn "
                f"{self.min_free_bytes} byte tại '{stat_path}'"
            )
        elif free < self.low_free_bytes:
            decision = StorageDecision.ALLOW_LOW_SPACE
            reason = (
                f"Dung lượng trống {free} byte < ngưỡng cảnh báo sớm "
                f"{self.low_free_bytes} byte (nhưng vẫn >= ngưỡng an "
                f"toàn {self.min_free_bytes} byte) tại '{stat_path}'"
            )
        else:
            decision = StorageDecision.ALLOW
            reason = (
                f"Dung lượng trống {free} byte >= ngưỡng cảnh báo sớm "
                f"{self.low_free_bytes} byte tại '{stat_path}'"
            )

        return StorageCheckResult(
            decision=decision,
            reason=reason,
            checked_path=stat_path,
            free_bytes=free,
            total_bytes=usage.total,
            used_bytes=usage.used,
        )

    def may_start_new_segment(self) -> bool:
        """Tiện ích: True nếu check() hiện tại cho phép tạo đoạn mới."""
        return self.check().allows_new_segment()

    # ------------------------------------------------------------------
    # Áp dụng lên một RecordingSession
    # ------------------------------------------------------------------

    def apply_to_session(self, session: RecordingSession) -> StorageCheckResult:
        """Chạy check() và, nếu kết quả là DISK_FULL, chuyển `session`
        sang RecordingStatus.DISK_FULL (dùng `reason` của check() làm
        `error`). Đây là TOÀN BỘ mức độ tích hợp của Task 4 — không gọi
        hàm này từ recorder.py ở đây; việc gọi nó đúng thời điểm (trước
        _start_segment()/_rotate_segment()) là việc của task tích hợp
        sau, để không làm phình scope Task 4.

        Khi decision là ALLOW/ALLOW_LOW_SPACE/CHECK_FAILED, session
        KHÔNG bị đụng vào — caller tự quyết định phải làm gì tiếp (vd.
        coi CHECK_FAILED là không an toàn và không tạo đoạn mới, nhưng
        không nhất thiết phải coi đó là lỗi ghi hình).

        Nếu `session` không ở trạng thái có thể chuyển sang DISK_FULL
        (vd. đã STOPPED), InvalidTransitionError được để propagate
        nguyên vẹn — không bị nuốt ở đây. Việc gọi hàm này chỉ hợp lý
        khi session đang RECORDING; caller chịu trách nhiệm đó.
        """
        result = self.check()
        if result.decision is StorageDecision.DISK_FULL:
            session.transition_to(RecordingStatus.DISK_FULL, error=result.reason)
        return result
