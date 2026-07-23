"""
config_loader.py
Đọc file cấu hình từ %APPDATA%\\EzvizFloatCam\\config.json (Windows).
Nếu chưa tồn tại, copy từ config/default_config.json làm mẫu.
"""

import json
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "EzvizFloatCam"


def get_config_dir() -> Path:
    """Trả về thư mục lưu config theo user, không phụ thuộc quyền admin."""
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    # fallback khi chạy trên Linux/Mac để test code (không phải mục tiêu chính)
    return Path.home() / f".{APP_NAME.lower()}"


def get_default_config_path() -> Path:
    """Đường dẫn tới file default_config.json đi kèm source/exe."""
    if getattr(sys, "frozen", False):
        # khi đã đóng gói bằng PyInstaller, base_path là thư mục chứa exe
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent.parent
    return base_path / "config" / "default_config.json"


def get_app_icon_path() -> Path:
    """Đường dẫn tới assets/app_icon.ico đi kèm source/exe (Sprint 8 - vụ
    icon). Dùng chung logic base_path với get_default_config_path() ở trên,
    vì PyInstaller onefile giải nén cả hai vào cùng thư mục tạm _MEIPASS."""
    if getattr(sys, "frozen", False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent.parent
    return base_path / "assets" / "app_icon.ico"


def load_config() -> dict:
    config_dir = get_config_dir()
    config_path = config_dir / "config.json"

    if not config_path.exists():
        config_dir.mkdir(parents=True, exist_ok=True)
        default_path = get_default_config_path()
        shutil.copy(default_path, config_path)

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def build_rtsp_url(rtsp_cfg: dict) -> str:
    """
    Dựng RTSP URL theo chuẩn Ezviz (nền Hikvision-based).
    Ví dụ: rtsp://admin:password@192.168.1.100:554/h264/ch1/sub/av_stream
    """
    username = rtsp_cfg["username"]
    password = rtsp_cfg["password"]
    ip = rtsp_cfg["ip"]
    port = rtsp_cfg.get("port", 554)
    channel = rtsp_cfg.get("channel", "ch1")
    stream_type = rtsp_cfg.get("stream_type", "sub")

    auth = f"{username}:{password}@" if username else ""
    return f"rtsp://{auth}{ip}:{port}/h264/{channel}/{stream_type}/av_stream"
