# EzvizFloatCam

Ứng dụng Windows nhỏ gọn, hiển thị camera Ezviz (qua RTSP) dưới dạng cửa sổ nổi ở góc màn hình, luôn hiển thị phía trên các cửa sổ khác.

> ⚠️ **Trạng thái hiện tại: Sprint 5.6 — Tự kết nối lại & Giới thiệu (About)**
> Ứng dụng mới chỉ chạy được từ source code Python, **chưa có file `.exe` để tải về dùng ngay**. Bản cài đặt `.exe` sẽ có ở các sprint sau (đóng gói + installer). Người dùng phổ thông vui lòng chờ bản Release chính thức.

---

## Tính năng dự kiến (đang phát triển dần theo sprint)

- [x] Kết nối và hiển thị stream RTSP từ camera Ezviz
- [x] Giao diện bo góc, hiệu ứng kính mờ (glass), luôn nổi trên cùng, kéo-thả & resize góc
- [x] Icon khay hệ thống — bật/tắt stream, ẩn/hiện cửa sổ, thoát
- [x] Cấu hình kết nối (IP/user/pass) qua giao diện, không cần sửa file
- [x] Tuỳ chọn khởi động cùng Windows
- [x] Bật/tắt tiếng (mute) — icon trên cửa sổ nổi
- [x] Ghi hình khẩn cấp — luồng chất lượng cao, lưu file .mkv cục bộ
- [x] Tự kết nối lại khi mất mạng/camera rớt, hiện màn hình "Mất tín hiệu" thay vì đứng hình đen sì
- [x] Hộp thoại "Giới thiệu" (About) — icon góc dưới-trái cửa sổ camera
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

```powershell
cd src
python main.py
```

Cửa sổ hiện ra sẽ ở dạng nổi, không viền, bo góc, luôn nằm trên cùng — kéo-thả bất kỳ đâu trên cửa sổ (kể cả trên video) để di chuyển, kéo ở góc dưới-phải để đổi kích thước. Vị trí và kích thước sẽ tự lưu lại cho lần mở sau.

> Hiệu ứng "kính mờ" (blur nội dung phía sau cửa sổ) chỉ hoạt động thật trên Windows 10/11. Nếu chạy thử trên hệ điều hành khác, ứng dụng sẽ tự chuyển sang nền bán trong suốt thường (không có blur).

### Icon khay hệ thống

Ứng dụng chạy nền qua 1 icon ở khay hệ thống (system tray, góc dưới-phải màn hình cạnh đồng hồ):

- **Click trái / double-click vào icon**: ẩn/hiện cửa sổ camera.
- **Click phải vào icon** để mở menu:
  - **Ẩn/Hiện cửa sổ**
  - **Bật/Tắt stream** — dừng stream để tiết kiệm CPU/băng thông mà không cần đóng app.
  - **Cài đặt...** — mở dialog nhập IP/port/user/mật khẩu RTSP, có nút "Kiểm tra kết nối" để test trước khi lưu. Lưu xong app tự kết nối lại ngay.
  - **Thoát** — thoát hẳn ứng dụng (đây là cách duy nhất để thoát app).

> Lưu ý: cửa sổ camera không có nút đóng/titlebar (frameless). Nếu bấm Alt+F4 hoặc lỡ đóng cửa sổ bằng cách khác, app **chỉ ẩn cửa sổ đi** (icon khay vẫn còn) chứ không thoát hẳn — bấm lại vào icon khay hoặc chọn "Hiện cửa sổ" để mở lại.

### Mute & Ghi hình khẩn cấp

Góc trên-phải cửa sổ camera có 2 icon nhỏ:

- **Icon loa** (bên phải) — bật/tắt tiếng. Trạng thái được lưu lại, lần mở app sau vẫn giữ nguyên.
- **Icon chấm tròn** (bên trái, cạnh icon loa) — bấm để bắt đầu **ghi hình khẩn cấp**: app mở 1 kết nối RTSP RIÊNG tới **luồng chất lượng cao (main)** của camera (khác với luồng nhẹ đang xem trực tiếp) và ghi thẳng ra file `.mkv` cục bộ, kèm chữ `REC mm:ss` hiện bên cạnh trong lúc đang ghi. Bấm lại icon để dừng và lưu file.
  - Video được lưu vào thư mục cấu hình ở **Cài đặt... → Thư mục lưu ghi hình khẩn cấp** (nút "Duyệt..." để tự chọn nơi lưu, hoặc "Dùng thư mục gợi ý" để dùng `%USERPROFILE%\Videos\EzvizFloatCam`). Nếu chưa từng cấu hình, app tự dùng thư mục gợi ý này khi bấm ghi lần đầu.
  - Tên file dạng `emergency_YYYYMMDD_HHMMSS.mkv`. Dùng MKV thay vì MP4 vì MKV vẫn phát được ngay cả khi bị ngắt đột ngột (app crash, mất điện...) — xem chi tiết lý do trong `PROJECT_MEMORY.md`.
  - Ghi hình dùng cơ chế remux trực tiếp (không giải mã lại), nên rất nhẹ CPU và không ảnh hưởng tới luồng đang xem trong cửa sổ chính.
  - Nếu mất kết nối tới luồng main giữa chừng (vd sai cấu hình, mất mạng), app sẽ báo lỗi bằng hộp thoại và dừng ghi — file đã ghi tới thời điểm đó vẫn được giữ lại.

### Tự kết nối lại & màn hình "Mất tín hiệu"

Khi RTSP bị rớt (mất mạng, camera tắt, sai cấu hình...), cửa sổ camera sẽ:

1. Tự thử kết nối lại tối đa 5 lần, thời gian chờ giữa các lần tăng dần (1.5s → 3s → 5s → 8s → 12s). Trong lúc này, màn hình hiện nhiễu kiểu TV cũ kèm chữ **"ĐANG KẾT NỐI LẠI"** và số lần đã thử — không còn đứng hình đen sì như trước.
2. Nếu vẫn thất bại sau 5 lần, chuyển sang màn hình **"MẤT TÍN HIỆU"** và tiếp tục tự thử lại mỗi 15 giây (không giới hạn số lần) — tự khôi phục ngay khi camera/mạng có lại, không cần mở lại app.
3. Chấm trạng thái ở góc trên-trái cửa sổ đổi màu theo 3 trạng thái: xanh lá (đang xem bình thường), vàng cam (đang kết nối/kết nối lại), đỏ (mất tín hiệu hoặc đã dừng stream).

### Giới thiệu (About)

Icon **"i"** nhỏ ở góc dưới-trái cửa sổ camera (cạnh chấm trạng thái phía trên, đối xứng với tay cầm resize ở góc dưới-phải) — bấm vào để xem tên app, số phiên bản, link GitHub và giấy phép mã nguồn mở (MIT).

---

## Đóng góp / Báo lỗi

Đây là dự án cá nhân đang phát triển dần. Nếu gặp lỗi khi chạy thử, vui lòng tạo [Issue](../../issues) kèm mô tả lỗi và log console.

## License

MIT
