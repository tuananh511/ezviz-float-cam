# EzvizFloatCam

> Giám sát camera Ezviz qua RTSP trong một cửa sổ nổi luôn nằm trên cùng màn hình.

[![Release](https://img.shields.io/github/v/release/tuananh511/ezviz-float-cam?include_prereleases&label=release)](https://github.com/tuananh511/ezviz-float-cam/releases)
[![License](https://img.shields.io/github/license/tuananh511/ezviz-float-cam)](https://github.com/tuananh511/ezviz-float-cam/blob/main/LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/tuananh511/ezviz-float-cam/build.yml?branch=main)](https://github.com/tuananh511/ezviz-float-cam/actions)

## Overview

EzvizFloatCam là ứng dụng Windows nhỏ gọn, hiển thị luồng RTSP từ camera Ezviz dưới dạng cửa sổ nổi ở góc màn hình, luôn ở trên các cửa sổ khác, với giao diện kính mờ bo góc. Dự án đang phát triển theo từng sprint — hiện tại (Sprint 4) mới chạy được từ source code Python, chưa có bản `.exe` đóng gói.

## Features

- Kết nối và hiển thị stream RTSP từ camera Ezviz
- Giao diện bo góc, hiệu ứng kính mờ (glass), luôn nổi trên cùng, kéo-thả & resize góc
- Icon khay hệ thống — bật/tắt stream, ẩn/hiện cửa sổ, thoát
- Cấu hình kết nối (IP/user/pass) qua giao diện, không cần sửa file
- *(Sắp có)* Tuỳ chọn khởi động cùng Windows
- *(Sắp có)* File cài đặt `.exe` — không cần cài Python
- *(Sắp có)* Gỡ cài đặt chuẩn qua Control Panel / Revo Uninstaller

## Installation

**Yêu cầu:**
- Windows 10/11
- [Python 3.10+](https://www.python.org/downloads/)
- [VLC media player](https://www.videolan.org/vlc/) (bản desktop, cần cài để có `libvlc.dll`)
- Camera Ezviz đã bật RTSP (trong app Ezviz: **Cài đặt thiết bị → Tính năng nâng cao → Địa chỉ Platform/RTSP**, bật RTSP và đặt mật khẩu riêng cho RTSP)

```bash
git clone https://github.com/tuananh511/ezviz-float-cam.git
cd ezviz-float-cam
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

**Cấu hình camera** — cách khuyến nghị là qua giao diện: chạy app lần đầu, click phải vào icon khay hệ thống → **Cài đặt...** → nhập IP/port/user/mật khẩu RTSP → bấm **Kiểm tra kết nối** để test trước khi lưu → bấm **Lưu**. App tự kết nối lại ngay, không cần khởi động lại.

Cách thủ công: chạy thử 1 lần để app tự tạo file config tại `%APPDATA%\EzvizFloatCam\config.json`, rồi sửa trực tiếp:

```json
{
  "rtsp": {
    "ip": "192.168.1.100",
    "port": 554,
    "username": "admin",
    "password": "mat-khau-rtsp-cua-ban",
    "stream_type": "sub",
    "channel": "ch1"
  }
}
```

> `stream_type`: dùng `"sub"` cho luồng nhẹ (khuyến nghị cho cửa sổ nhỏ), `"main"` cho luồng nét/nặng hơn.
> ⚠️ Mật khẩu RTSP hiện được lưu dạng plaintext trong `config.json` (không commit lên GitHub, chỉ tài khoản Windows của bạn đọc được) — nếu cần bảo mật cao hơn, hãy đặt mật khẩu RTSP riêng cho camera trong app Ezviz.

**Chạy ứng dụng:**

```bash
cd src
python main.py
```

Cửa sổ hiện ra ở dạng nổi, không viền, bo góc, luôn nằm trên cùng — kéo-thả bất kỳ đâu (kể cả trên video) để di chuyển, kéo góc dưới-phải để đổi kích thước. Vị trí và kích thước tự lưu lại cho lần mở sau.

**Icon khay hệ thống:** click trái/double-click để ẩn/hiện cửa sổ; click phải để mở menu **Ẩn/Hiện cửa sổ**, **Bật/Tắt stream**, **Cài đặt...**, **Thoát** (cách duy nhất để thoát hẳn app — Alt+F4 hoặc đóng cửa sổ chỉ ẩn đi).

## Roadmap

- [ ] Tuỳ chọn khởi động cùng Windows
- [ ] Đóng gói file cài đặt `.exe` — không cần cài Python
- [ ] Gỡ cài đặt chuẩn qua Control Panel / Revo Uninstaller

## License

MIT
