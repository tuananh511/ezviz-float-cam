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
    try:
        run_startup_recovery(save_dir)
    except Exception as exc:  # noqa: BLE001 — ranh giới ứng dụng, xem chú thích trên
        print(f"[WARN] Startup recording recovery thất bại, bỏ qua: {exc}")

    window = GlassWindow(config, rtsp_url)
    window.show()

    tray = TrayIcon(window, app)  # noqa: F841 — giữ tham chiếu sống suốt vòng đời app

    # bắt đầu phát sau khi cửa sổ đã hiện ra (tránh lỗi bind window handle quá
    # sớm); start_stream() cũng áp dụng lại trạng thái mute đã lưu từ lần
    # trước (Sprint 5.5).
    QTimer.singleShot(300, window.start_stream)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
