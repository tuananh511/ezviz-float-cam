"""
main.py — Sprint 3: System tray
Entry point: nạp config, dựng RTSP URL, mở cửa sổ kính mờ nổi (GlassWindow)
always-on-top, tự phát stream sau khi cửa sổ đã hiện ra, kèm icon khay hệ
thống (TrayIcon) để hiện/ẩn, bật/tắt stream, thoát app.
"""

import sys
import re
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from PySide6.QtCore import QTimer

from config_loader import load_config, build_rtsp_url
from glass_window import GlassWindow
from tray import TrayIcon


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

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("[WARN] Hệ thống không có khay hệ thống (system tray) — icon khay sẽ không hiện.")

    config = load_config()
    rtsp_url = build_rtsp_url(config["rtsp"])
    print(f"[INFO] Đang kết nối tới: {_mask_credentials(rtsp_url)}")

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
