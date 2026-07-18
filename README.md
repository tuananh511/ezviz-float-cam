# EzvizFloatCam

Ứng dụng Windows nhỏ gọn, hiển thị camera Ezviz (qua RTSP) dưới dạng cửa sổ nổi ở góc màn hình, luôn hiển thị phía trên các cửa sổ khác, giao diện kính mờ bo góc.

> ✅ **Trạng thái hiện tại: Sprint 7 — Installer + Uninstaller (đang chờ đóng gói Release chính thức)**
> App đã đầy đủ tính năng, đã build được file `.exe` và installer chuẩn Windows. Bản Release đính kèm file cài đặt sẽ sớm có ở trang [Releases](../../releases) — trong lúc chờ, bạn vẫn có thể tự build hoặc chạy từ source theo hướng dẫn bên dưới.

---

## Tính năng

- [x] Kết nối và hiển thị stream RTSP từ camera Ezviz
- [x] Giao diện bo góc, hiệu ứng kính mờ (glass), luôn nổi trên cùng, kéo-thả & resize góc
- [x] Icon khay hệ thống — bật/tắt stream, ẩn/hiện cửa sổ, thoát
- [x] Cấu hình kết nối (IP/user/pass) qua giao diện, không cần sửa file
- [x] Khởi động cùng Windows (tuỳ chọn, bật/tắt trong Cài đặt hoặc lúc cài installer)
- [x] Mute & Ghi hình khẩn cấp — icon riêng trên cửa sổ nổi
- [x] Tự động kết nối lại khi mất tín hiệu — hiện hình nhiễu "MẤT TÍN HIỆU" thay vì màn đen, tự khôi phục khi có mạng lại
- [x] Hộp thoại "Giới thiệu" (About) — icon góc dưới-trái cửa sổ
- [x] File cài đặt `.exe` — không cần cài Python
- [x] Installer + Uninstaller chuẩn Windows (Inno Setup) — tương thích Control Panel / Revo Uninstaller
- [ ] GitHub Release chính thức kèm file cài đặt (đang hoàn tất)

---

## Dành cho người dùng phổ thông (khuyến nghị)

Vào trang [Releases](../../releases), tải file `EzvizFloatCam-Setup-x.x.x.exe` mới nhất, chạy và làm theo hướng dẫn cài đặt. Không cần cài Python.

**Yêu cầu duy nhất:** máy cần có sẵn [VLC media player](https://www.videolan.org/vlc/) (bản desktop) để có `libvlc.dll` — app dùng chung thư viện giải mã video với VLC, chưa đóng gói kèm theo installer.

Sau khi cài xong, gỡ cài đặt như phần mềm bình thường qua **Control Panel → Apps & Features** hoặc qua Revo Uninstaller.

---

## Dành cho người muốn chạy/build từ source code

### Yêu cầu

- Windows 10/11
- [Python 3.10+](https://www.python.org/downloads/)
- [VLC media player](https://www.videolan.org/vlc/) (bản desktop, cần cài để có `libvlc.dll`)
- Camera Ezviz đã bật RTSP (trong app Ezviz: **Cài đặt thiết bị → Tính năng nâng cao → Địa chỉ Platform/RTSP**, bật RTSP và đặt mật khẩu riêng cho RTSP)

### Cài đặt

```
git clone https://github.com/tuananh511/ezviz-float-cam.git
cd ezviz-float-cam
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Cấu hình camera

**Cách khuyến nghị — qua giao diện:** chạy app lần đầu (xem mục "Chạy" bên dưới), click phải vào icon khay hệ thống → **Cài đặt...** → nhập IP/port/user/mật khẩu RTSP của camera → bấm **Kiểm tra kết nối** để test thật trước khi lưu → bấm **Lưu**. App sẽ tự kết nối lại ngay với thông tin mới, không cần khởi động lại.

**Cách thủ công (dự phòng):** nếu muốn sửa trực tiếp, chạy thử 1 lần để app tự tạo file config tại `%APPDATA%\EzvizFloatCam\config.json`, rồi mở file đó lên sửa:

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
> ⚠️ Mật khẩu RTSP hiện được lưu dạng plaintext (không mã hoá) trong `config.json` trên máy bạn — file này không commit lên GitHub và chỉ tài khoản Windows của bạn đọc được (`%APPDATA%` theo user), nhưng đây không phải mã hoá thật sự. Nếu cần bảo mật cao hơn, cân nhắc đặt mật khẩu RTSP riêng cho camera (khác mật khẩu chính) trong app Ezviz.

### Chạy

```
cd src
python main.py
```

Cửa sổ hiện ra sẽ ở dạng nổi, không viền, bo góc, luôn nằm trên cùng — kéo-thả bất kỳ đâu trên cửa sổ (kể cả trên video) để di chuyển, kéo ở góc dưới-phải để đổi kích thước. Vị trí và kích thước sẽ tự lưu lại cho lần mở sau.

> Hiệu ứng "kính mờ" (blur nội dung phía sau cửa sổ) chỉ hoạt động thật trên Windows 10/11. Nếu chạy thử trên hệ điều hành khác, ứng dụng sẽ tự chuyển sang nền bán trong suốt thường (không có blur).

### Icon khay hệ thống

Ứng dụng chạy nền qua 1 icon ở khay hệ thống (system tray, góc dưới-phải màn hình cạnh đồng hồ):

- **Click trái / double-click vào icon**: ẩn/hiện cửa sổ camera.
- **Click phải vào icon** để mở menu:
  * **Ẩn/Hiện cửa sổ**
  * **Bật/Tắt stream** — dừng stream để tiết kiệm CPU/băng thông mà không cần đóng app.
  * **Cài đặt...** — mở dialog nhập IP/port/user/mật khẩu RTSP, khởi động cùng Windows, có nút "Kiểm tra kết nối" để test trước khi lưu.
  * **Thoát** — thoát hẳn ứng dụng (đây là cách duy nhất để thoát app).

> Lưu ý: cửa sổ camera không có nút đóng/titlebar (frameless). Nếu bấm Alt+F4 hoặc lỡ đóng cửa sổ bằng cách khác, app **chỉ ẩn cửa sổ đi** (icon khay vẫn còn) chứ không thoát hẳn — bấm lại vào icon khay hoặc chọn "Hiện cửa sổ" để mở lại.

### Icon trên cửa sổ nổi

- **Góc trên-trái:** chấm trạng thái kết nối — xanh lá (đang xem), vàng cam (đang kết nối lại), đỏ (mất tín hiệu/đã dừng).
- **Góc trên-phải:** icon mute / ghi hình khẩn cấp.
- **Góc dưới-trái:** icon "i" — mở hộp thoại Giới thiệu (phiên bản, link GitHub, giấy phép MIT).
- **Góc dưới-phải:** tay cầm kéo để resize cửa sổ.

Khi mất kết nối camera, cửa sổ tự chuyển sang hiển thị hình nhiễu kèm chữ "ĐANG KẾT NỐI LẠI" / "MẤT TÍN HIỆU" thay vì màn đen, và tự khôi phục khi có tín hiệu trở lại — không cần mở lại app.

### Đóng gói thành file `.exe`

```
build_exe.bat
```
(hoặc `pyinstaller ezvizfloatcam.spec --noconfirm` nếu đã tự cài PyInstaller). File exe xuất ra tại `dist\EzvizFloatCam.exe` — chạy độc lập, không cần Python trên máy, nhưng vẫn cần cài sẵn VLC.

### Đóng gói thành installer (Inno Setup)

Yêu cầu [Inno Setup 6](https://jrsoftware.org/isinfo.php). Sau khi có `dist\EzvizFloatCam.exe`:

```
ISCC.exe installer\setup.iss
```

File cài đặt xuất ra tại `dist_installer\EzvizFloatCam-Setup-x.x.x.exe`. Đây là bản Windows installer chuẩn: đăng ký vào Apps & Features, hỗ trợ tuỳ chọn tạo icon Desktop/khởi động cùng Windows lúc cài, và gỡ được qua Control Panel hoặc Revo Uninstaller.

---

## Đóng góp / Báo lỗi

Đây là dự án cá nhân đang phát triển dần. Nếu gặp lỗi khi chạy thử, vui lòng tạo [Issue](../../issues) kèm mô tả lỗi và log console.

## License

MIT
