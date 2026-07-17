"""
autostart.py — Sprint 5: Khởi động cùng Windows

Bật/tắt tự khởi động app cùng Windows bằng cách ghi/xoá 1 giá trị trong
registry key HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run — không
cần quyền admin (HKCU chỉ áp dụng cho user hiện tại, đúng tinh thần "cài đặt
riêng cho bạn" của app, không cần chạy app với quyền Administrator).

An toàn trên non-Windows: mọi hàm trả về False/no-op ngay nếu không phải
Windows, chỉ import winreg (module chỉ tồn tại trên Windows) khi thật sự cần
— cùng convention với windows_blur.py đã có từ Sprint 2.
"""

import sys
import os

APP_NAME = "EzvizFloatCam"
_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _get_startup_command() -> str:
    """Dựng lệnh sẽ ghi vào registry Run key.

    - Nếu app đã đóng gói bằng PyInstaller (sys.frozen == True, sẽ có từ
      Sprint 6 trở đi): dùng thẳng sys.executable (chính là file .exe),
      không cần tham số gì thêm.
    - Nếu đang chạy từ source (giai đoạn hiện tại): dùng pythonw.exe (không
      hiện cửa sổ console đen mỗi lần Windows khởi động) + đường dẫn tuyệt
      đối tới main.py.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    python_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(python_dir, "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable  # fallback: vẫn chạy được, chỉ là có console đen

    main_script = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "main.py")
    )
    return f'"{pythonw}" "{main_script}"'


def is_autostart_enabled() -> bool:
    """Đọc trạng thái THẬT từ registry (không đọc từ config.json) — đây là
    nguồn chân lý duy nhất, phòng trường hợp người dùng tự xoá key bằng tay
    (vd qua Task Manager > Startup) mà không thông qua app, khiến config.json
    và registry lệch nhau."""
    if not _is_windows():
        return False

    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ
        )
    except OSError:
        return False

    try:
        winreg.QueryValueEx(key, APP_NAME)
        return True
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)


def set_autostart(enabled: bool) -> bool:
    """Bật/tắt khởi động cùng Windows. Trả về True nếu ghi/xoá registry
    thành công, False nếu thất bại (vd bị chặn quyền, hoặc không phải
    Windows) — nơi gọi (tray.py) nên xử lý trường hợp False bằng cách đọc
    lại is_autostart_enabled() để lưu đúng trạng thái thật, không chặn việc
    lưu các cài đặt khác."""
    if not _is_windows():
        return False

    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
        )
    except OSError:
        return False

    try:
        if enabled:
            winreg.SetValueEx(
                key, APP_NAME, 0, winreg.REG_SZ, _get_startup_command()
            )
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass  # đã không có sẵn từ trước -> coi như thành công
        return True
    except OSError:
        return False
    finally:
        winreg.CloseKey(key)
