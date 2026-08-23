"""
main.py — Sprint 3: System tray
Entry point: nạp config, dựng RTSP URL, mở cửa sổ kính mờ nổi (GlassWindow)
always-on-top, tự phát stream sau khi cửa sổ đã hiện ra, kèm icon khay hệ
thống (TrayIcon) để hiện/ẩn, bật/tắt stream, thoát app.
"""

import sys
import re
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer

from config_loader import load_config, build_rtsp_url, get_app_icon_path
from glass_window import GlassWindow
from tray import TrayIcon
from recording.startup import run_startup_recovery


def _mask_credentials(url: str) -> str:
    """Che user:pass trong RTSP URL khi in ra console/log, tránh lộ mật khẩu
    lúc người dùng copy log để báo lỗi."""
    return re.sub(r"://[^@/]+@", "://***:***@", url)


def _notify_startup_recovery_result(tray: QSystemTrayIcon, report) -> None:
    """Task 12: surface the RecoveryReport (Task 8/`recording.recovery`)
    returned by `run_startup_recovery()` (Task 11) to the user, through
    the tray icon's existing (Qt-native, inherited from QSystemTrayIcon)
    `showMessage()` balloon-notification API — no new notification
    mechanism, no new TrayIcon method.

    This function only *reads* the report and decides what (if anything)
    to display; it never re-runs, extends, or second-guesses recovery
    itself, and never touches the filesystem, VLC, or RTSP.

    - report is None (recovery raised, see the try/except around
      run_startup_recovery() in main()) or entirely empty (nothing to
      recover) -> no notification at all.
    - report.recovered non-empty -> one Information-level notification
      with a concise count only (no paths, no session IDs).
    - report.invalid or report.failed non-empty -> one separate
      Warning-level notification with a concise count only (no raw
      exception text/tracebacks — SessionRecoveryResult.error is never
      surfaced to the user here).

    Never raises: a notification failure (e.g. no system tray available,
    or showMessage() itself erroring) must not prevent application
    startup, so any exception here is caught and logged, matching the
    same app-boundary try/except pattern Task 11 already uses around
    run_startup_recovery() itself.
    """
    if report is None:
        return

    try:
        recovered_count = len(report.recovered)
        problem_count = len(report.invalid) + len(report.failed)

        if recovered_count > 0:
            tray.showMessage(
                "EzvizFloatCam",
                f"Đã khôi phục {recovered_count} phiên ghi hình khẩn cấp bị "
                "gián đoạn từ lần chạy trước.",
                QSystemTrayIcon.Information,
                5000,
            )

        if problem_count > 0:
            tray.showMessage(
                "EzvizFloatCam",
                f"{problem_count} phiên ghi hình trước đó không thể khôi "
                "phục hoàn toàn.",
                QSystemTrayIcon.Warning,
                5000,
            )
    except Exception as exc:  # noqa: BLE001 — xem docstring: không được
        # chặn khởi động app chỉ vì hiện thông báo thất bại.
        print(f"[WARN] Hiện thông báo khôi phục ghi hình thất bại, bỏ qua: {exc}")


def main():
    app = QApplication(sys.argv)
    # App chỉ thoát khi người dùng chọn "Thoát" ở tray, KHÔNG thoát khi cửa
    # sổ chính bị ẩn/đóng (vd Alt+F4) — nếu không, tray sẽ chết theo, mất hết
    # tác dụng của việc có system tray.
    app.setQuitOnLastWindowClosed(False)

    # Icon riêng cho app (Sprint 8 - vụ icon): set ở cấp QApplication để cả
    # taskbar/Alt-Tab lẫn icon mặc định của tray đều dùng đúng icon này, thay
    # vì icon Python/Qt mặc định — độc lập với icon đã nhúng vào .exe lúc
    # build (PyInstaller --icon), nên vẫn đúng khi chạy trực tiếp từ source.
    icon_path = get_app_icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    else:
        print(f"[WARN] Không tìm thấy app icon tại {icon_path} — dùng icon mặc định.")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("[WARN] Hệ thống không có khay hệ thống (system tray) — icon khay sẽ không hiện.")

    config = load_config()
    rtsp_url = build_rtsp_url(config["rtsp"])
    print(f"[INFO] Đang kết nối tới: {_mask_credentials(rtsp_url)}")

    # Startup crash recovery (Task 11): phải chạy trước khi bất kỳ
    # EmergencyRecorder/GlassWindow nào được dựng lên, để các phiên ghi hình
    # bị bỏ dở do crash/mất điện lần trước được đưa về trạng thái kết thúc
    # (FAILED) trước khi có cơ hội ghi đè hoặc bị VLC động vào. Chỉ chạy
    # đúng một lần mỗi tiến trình. run_startup_recovery() tự nó không bao
    # giờ raise theo tài liệu (recover_all trả về RecoveryReport, không
    # raise cho từng phiên lỗi), nhưng vẫn bọc try/except ở ranh giới ứng
    # dụng này để một lỗi tích hợp không lường trước không chặn app khởi
    # động.
    save_dir = config.get("recording", {}).get("save_dir", "")
    recovery_report = None
    try:
        recovery_report = run_startup_recovery(save_dir)
    except Exception as exc:  # noqa: BLE001 — ranh giới ứng dụng, xem chú thích trên
        print(f"[WARN] Startup recording recovery thất bại, bỏ qua: {exc}")

    window = GlassWindow(config, rtsp_url)
    window.show()

    tray = TrayIcon(window, app)  # noqa: F841 — giữ tham chiếu sống suốt vòng đời app

    # Task 12: báo cho người dùng biết kết quả khôi phục ở trên (nếu có gì
    # đáng nói) — phải chạy SAU khi tray đã dựng xong (cần tray làm nơi
    # hiện balloon notification), nhưng vẫn trước app.exec().
    _notify_startup_recovery_result(tray, recovery_report)

    # bắt đầu phát sau khi cửa sổ đã hiện ra (tránh lỗi bind window handle quá
    # sớm); start_stream() cũng áp dụng lại trạng thái mute đã lưu từ lần
    # trước (Sprint 5.5).
    QTimer.singleShot(300, window.start_stream)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
