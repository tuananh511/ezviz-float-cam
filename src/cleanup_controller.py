"""
cleanup_controller.py — chạy dọn dẹp dung lượng ghi hình định kỳ (nền Qt).

Mỗi 60 giây (và ngay sau khi một phiên ghi tự động kết thúc, và ~5 giây sau
khi app khởi động — SAU bước khôi phục phiên dở dang ở main.py) kiểm tra tổng
dung lượng các phiên ghi hình trong thư mục lưu; vượt ngưỡng ở Cài đặt thì xoá
dần bản ghi TỰ ĐỘNG cũ nhất. Ghi thủ công không bao giờ bị xoá; phiên đang ghi
được loại ra. Chi tiết quy tắc an toàn: recording/cleanup.py.

Chạy trên thread chính: mỗi lần chỉ quét vài chục thư mục nhỏ (stat file),
và xoá file lớn gần như tức thì, nên không cần thread riêng.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from recording import resolve_recording_base_dir
from recording.cleanup import CleanupReport, get_retention_config, run_cleanup
from recording.summary import format_size

CHECK_INTERVAL_MS = 60_000
STARTUP_DELAY_MS = 5_000
_GB = 1024 ** 3


class RecordingCleanupController(QObject):
    cleaned = Signal(object)   # CleanupReport — chỉ phát khi thật sự đã xoá gì đó

    def __init__(self, get_config, get_active_dirs, parent=None):
        super().__init__(parent)
        self._get_config = get_config          # -> dict config đầy đủ
        self._get_active_dirs = get_active_dirs  # -> iterable các thư mục phiên đang ghi
        self._warned_unresolved = False

        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self.run_now)

    def start(self):
        if not self._timer.isActive():
            self._timer.start()
        QTimer.singleShot(STARTUP_DELAY_MS, self.run_now)

    def shutdown(self):
        self._timer.stop()

    def run_now(self) -> CleanupReport | None:
        config = self._get_config()
        cfg = get_retention_config(config)
        if not cfg["enabled"]:
            return None
        base_dir = resolve_recording_base_dir(config.get("recording", {}).get("save_dir", ""))
        try:
            report = run_cleanup(
                base_dir,
                cfg["max_gb"] * _GB,
                exclude_dirs=list(self._get_active_dirs()),
            )
        except Exception as exc:  # noqa: BLE001 — dọn dẹp phụ, không được làm sập app
            print(f"[WARN] Dọn dẹp dung lượng ghi hình thất bại: {exc}")
            return None

        if report.deleted:
            print(
                f"[INFO] Đã tự xoá {len(report.deleted)} bản ghi tự động cũ "
                f"(giải phóng {format_size(report.freed_bytes)}), thư mục ghi hình "
                f"còn {format_size(report.total_after)}/{cfg['max_gb']} GB."
            )
            self.cleaned.emit(report)
        if report.unresolved and not self._warned_unresolved:
            self._warned_unresolved = True
            print(
                "[WARN] Thư mục ghi hình vẫn vượt ngưỡng sau khi đã xoá hết bản ghi "
                "tự động được phép xoá — phần còn lại là ghi thủ công/đang ghi "
                "(không bao giờ tự xoá). Hãy tăng ngưỡng ở Cài đặt hoặc tự xoá bớt."
            )
        elif not report.unresolved:
            self._warned_unresolved = False
        for err in report.errors:
            print(f"[WARN] Không xoá được: {err}")
        return report
