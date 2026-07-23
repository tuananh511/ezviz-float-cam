# EzvizFloatCam

> Giám sát camera Ezviz qua RTSP trong một cửa sổ nổi luôn nằm trên cùng màn hình.

[![Release](https://img.shields.io/github/v/release/tuananh511/ezviz-float-cam?include_prereleases&label=release)](https://github.com/tuananh511/ezviz-float-cam/releases)
[![License](https://img.shields.io/github/license/tuananh511/ezviz-float-cam)](https://github.com/tuananh511/ezviz-float-cam/blob/main/LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/tuananh511/ezviz-float-cam/build.yml?branch=main)](https://github.com/tuananh511/ezviz-float-cam/actions)

## Overview

EzvizFloatCam là ứng dụng Windows nhỏ gọn, hiển thị luồng RTSP từ camera Ezviz dưới dạng cửa sổ nổi ở góc màn hình, luôn ở trên các cửa sổ khác, với giao diện kính mờ bo góc. Dự án đã hoàn thành toàn bộ roadmap ban đầu (**v0.7.0**) — có sẵn file cài đặt `.exe` cho người dùng phổ thông, không cần biết code hay cài Python.

## Features

- Kết nối và hiển thị stream RTSP từ camera Ezviz
- Giao diện bo góc, hiệu ứng kính mờ (glass), luôn nổi trên cùng, kéo-thả & resize góc dưới-phải
- Icon khay hệ thống — bật/tắt stream, ẩn/hiện cửa sổ, thoát
- Cấu hình kết nối (IP/user/pass) qua giao diện, có nút "Kiểm tra kết nối" trước khi lưu
- Tắt tiếng (mute) và ghi hình khẩn cấp (luồng chất lượng cao) ngay từ icon trên cửa sổ nổi
- Tự kết nối lại khi mất tín hiệu (hiện màn nhiễu "ĐANG KẾT NỐI LẠI" / "MẤT TÍN HIỆU" thay vì màn đen), tự khôi phục khi có mạng lại
- Hộp thoại "Giới thiệu" (About) hiện phiên bản, link GitHub, giấy phép
- Tuỳ chọn khởi động cùng Windows
- File cài đặt `.exe` chuẩn — không cần cài Python để dùng
- Gỡ cài đặt chuẩn qua Control Panel / Revo Uninstaller

## Installation

### Cách 1 — File cài đặt (khuyến nghị cho người dùng phổ thông)

1. Cài [VLC media player](https://www.videolan.org/vlc/) (bản desktop) nếu máy chưa có — cần để có `libvlc.dll`.
2. Tải file cài đặt mới nhất từ [trang Releases](https://github.com/tuananh511/ezviz-float-cam/releases).
3. Chạy file `EzvizFloatCam-Setup-x.x.x.exe` — không cần quyền admin, không hiện UAC.
4. Gỡ cài đặt qua **Control Panel → Apps & Features** hoặc Revo Uninstaller như phần mềm thông thường.

### Cách 2 — Chạy từ mã nguồn (cho dev)

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

Tự đóng gói file `.exe`/installer riêng: xem `requirements-dev.txt`, `build_exe.bat` và `installer/setup.iss`.

## Usage

**Cấu hình camera** — cách khuyến nghị là qua giao diện: click phải vào icon khay hệ thống → **Cài đặt...** → nhập IP/port/user/mật khẩu RTSP → bấm **Kiểm tra kết nối** để test trước khi lưu → bấm **Lưu**. App tự kết nối lại ngay, không cần khởi động lại. Trong cùng dialog có thể tick **"Khởi động cùng Windows"**.

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

**Chạy ứng dụng** (nếu dùng từ source):

```bash
cd src
python main.py
```

Cửa sổ hiện ra ở dạng nổi, không viền, bo góc, luôn nằm trên cùng — kéo-thả bất kỳ đâu (kể cả trên video) để di chuyển, kéo góc dưới-phải để đổi kích thước. Vị trí và kích thước tự lưu lại cho lần mở sau.

**Icon trên cửa sổ:**
- Góc trên-phải: icon mute (tắt/bật tiếng) và icon ghi hình khẩn cấp (chấm đỏ + `REC mm:ss` khi đang ghi, dùng luồng chất lượng cao, lưu vào thư mục chọn ở Cài đặt)
- Góc dưới-trái: chấm trạng thái kết nối (xanh lá = đang kết nối, vàng cam = đang thử kết nối lại, đỏ = mất tín hiệu/đã dừng) và icon "i" mở hộp thoại **Giới thiệu**
- Góc dưới-phải: tay cầm resize

**Icon khay hệ thống:** click trái/double-click để ẩn/hiện cửa sổ; click phải để mở menu **Ẩn/Hiện cửa sổ**, **Bật/Tắt stream**, **Cài đặt...**, **Thoát** (cách duy nhất để thoát hẳn app — Alt+F4 hoặc đóng cửa sổ chỉ ẩn đi).

**Mất kết nối camera:** nếu rớt mạng/camera treo, cửa sổ tự chuyển sang màn nhiễu "ĐANG KẾT NỐI LẠI" rồi "MẤT TÍN HIỆU" nếu kéo dài, và tự khôi phục ngay khi có tín hiệu trở lại — không cần mở lại app.

## Roadmap

Toàn bộ roadmap ban đầu đã hoàn thành trong bản phát hành `v0.7.0`. Một số hướng mở rộng có thể cân nhắc sau này:

- [ ] Tự động cài kèm VLC redistributable trong installer
- [ ] Resize từ cả 4 góc/4 cạnh thay vì chỉ góc dưới-phải
- [x] Icon `.ico` riêng cho app thay vì icon mặc định Windows (`assets/app_icon.ico`, Sprint 8)
- [ ] Mã hoá mật khẩu RTSP trong `config.json` (hiện lưu plaintext)

## License

MIT
