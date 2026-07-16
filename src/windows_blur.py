"""
windows_blur.py
Bật hiệu ứng "Acrylic blur behind window" trên Windows 10/11 qua API không
chính thức SetWindowCompositionAttribute (dwmapi/user32). Đây là cách phổ
biến để có nền mờ kính thật (blur nội dung phía sau cửa sổ), khác với việc
chỉ vẽ 1 lớp màu bán trong suốt (không có blur thật).

An toàn trên các OS khác (Linux/Mac dùng để dev/test): mọi lỗi được nuốt,
hàm trả về False và code gọi nó sẽ tự fallback sang vẽ nền bán trong suốt
thường (xem glass_window.py).
"""

import sys
import ctypes


def _pack_gradient_color(r: int, g: int, b: int, a: int) -> int:
    """SetWindowCompositionAttribute nhận màu dạng ABGR (không phải ARGB)."""
    return (a << 24) | (b << 16) | (g << 8) | r


def enable_acrylic_blur(hwnd: int, r=32, g=32, b=32, alpha=180) -> bool:
    """
    Bật acrylic blur cho cửa sổ có handle `hwnd`.
    r,g,b,alpha: màu phủ lên trên lớp blur (0-255), alpha thấp hơn = blur rõ hơn,
    thấy xuyên hậu cảnh nhiều hơn; alpha cao hơn = ngả về màu đục hơn.
    Trả về True nếu bật thành công, False nếu không hỗ trợ (không phải Windows,
    Windows quá cũ, hoặc API bị chặn).
    """
    if not sys.platform.startswith("win"):
        return False

    try:
        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_int),
                ("AnimationId", ctypes.c_int),
            ]

        class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t),
            ]

        ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
        WCA_ACCENT_POLICY = 19

        accent = ACCENT_POLICY()
        accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 0
        accent.GradientColor = _pack_gradient_color(r, g, b, alpha)
        accent.AnimationId = 0

        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = WCA_ACCENT_POLICY
        data.SizeOfData = ctypes.sizeof(accent)
        data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)

        set_window_composition_attribute = ctypes.windll.user32.SetWindowCompositionAttribute
        result = set_window_composition_attribute(hwnd, ctypes.pointer(data))
        return bool(result)
    except Exception as exc:  # pragma: no cover - chỉ log, không được crash app
        print(f"[WARN] Không bật được acrylic blur: {exc}")
        return False
