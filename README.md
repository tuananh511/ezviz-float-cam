# EzvizFloatCam

Ứng dụng Windows nhỏ gọn, hiển thị camera Ezviz (qua RTSP) dưới dạng cửa sổ nổi ở góc màn hình, luôn hiển thị phía trên các cửa sổ khác.

> ⚠️ **Trạng thái hiện tại: Sprint 1 — bản test lõi (core viewer)**
> Ứng dụng mới chỉ chạy được từ source code Python, **chưa có file `.exe` để tải về dùng ngay**. Bản cài đặt `.exe` sẽ có ở các sprint sau (đóng gói + installer). Người dùng phổ thông vui lòng chờ bản Release chính thức.

---

## Tính năng dự kiến (đang phát triển dần theo sprint)

- [x] Kết nối và hiển thị stream RTSP từ camera Ezviz
- [ ] Giao diện bo góc, hiệu ứng kính mờ (glass), luôn nổi trên cùng
- [ ] Icon khay hệ thống — bật/tắt stream, ẩn/hiện cửa sổ
- [ ] Cấu hình kết nối (IP/user/pass) qua giao diện, không cần sửa file
- [ ] Tuỳ chọn khởi động cùng Windows
- [ ] File cài đặt `.exe` — không cần cài Python
- [ ] Gỡ cài đặt chuẩn qua Control Panel / Revo Uninstaller

---

## Dành cho người muốn chạy thử từ source code (giai đoạn hiện tại)

### Yêu cầu
- Windows 10/11
- [Python 3.10+](https://www.python.org/downloads/)
- [VLC media player](https://www.videolan.org/vlc/) (bản desktop, cần cài để có `libvlc.dll`)
- Camera Ezviz đã bật RTSP (trong app Ezviz: **Cài đặt thiết bị → Tính năng nâng cao → Địa chỉ Platform/RTSP**, bật RTSP và đặt mật khẩu riêng cho RTSP)

### Cài đặt

```powershell
git clone https://github.com/<tai-khoan-cua-ban>/ezviz-float-cam.git
cd ezviz-float-cam
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Cấu hình camera

Chạy thử 1 lần để ứng dụng tự tạo file config tại `%APPDATA%\EzvizFloatCam\config.json`, sau đó mở file đó lên sửa:

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

### Chạy

```powershell
cd src
python main.py
```

---

## Đóng góp / Báo lỗi

Đây là dự án cá nhân đang phát triển dần. Nếu gặp lỗi khi chạy thử, vui lòng tạo [Issue](../../issues) kèm mô tả lỗi và log console.

## License

MIT
