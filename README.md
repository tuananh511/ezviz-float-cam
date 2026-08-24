# EzvizFloatCam

> Ứng dụng Windows hiển thị luồng RTSP từ camera Ezviz trong một cửa sổ nổi luôn nằm trên cùng màn hình.

[![License](https://img.shields.io/github/license/tuananh511/ezviz-float-cam)](https://github.com/tuananh511/ezviz-float-cam/blob/main/LICENSE)

## Ứng dụng làm gì

EzvizFloatCam kết nối tới camera Ezviz qua RTSP và hiển thị luồng video trong một cửa sổ nhỏ, không viền, bo góc, hiệu ứng kính mờ (Acrylic blur), luôn nổi trên các cửa sổ khác. Cửa sổ có thể kéo-thả và resize tự do, có icon khay hệ thống để ẩn/hiện, và hỗ trợ ghi hình khẩn cấp (luồng chất lượng cao) khi cần.

## Tính năng hiện có

- Kết nối và hiển thị stream RTSP từ camera Ezviz (`src/stream_widget.py`, `src/glass_window.py`)
- Giao diện bo góc, hiệu ứng kính mờ, luôn nổi trên cùng, kéo-thả và resize góc dưới-phải
- Icon khay hệ thống (`src/tray.py`) — ẩn/hiện cửa sổ, bật/tắt stream, mở Cài đặt, thoát
- Cấu hình kết nối (IP/port/user/pass/loại luồng) qua giao diện Cài đặt, có nút "Kiểm tra kết nối" trước khi lưu (`src/settings_dialog.py`)
- Tắt tiếng (mute) và ghi hình khẩn cấp ngay từ icon trên cửa sổ nổi
- Tự kết nối lại khi mất tín hiệu (màn nhiễu "ĐANG KẾT NỐI LẠI" / "MẤT TÍN HIỆU"), tự khôi phục khi có tín hiệu trở lại
- Hộp thoại "Giới thiệu" (About)
- Tuỳ chọn khởi động cùng Windows qua registry HKCU, không cần quyền admin (`src/autostart.py`)

## Kiến trúc ghi hình khẩn cấp (Emergency Recording)

Ghi hình khẩn cấp (`src/recorder.py`, gói `src/recording/`) được xây dựng thành các module domain tách biệt, mỗi module một trách nhiệm, phần lớn không phụ thuộc PySide6/VLC:

| Module | Vai trò |
|---|---|
| `recording/session.py` | Domain model `RecordingSession`/`RecordingSegment` — state machine thuần (STARTING → RECORDING → STOPPING → STOPPED/FAILED/DISK_FULL), không phụ thuộc gì ngoài stdlib |
| `src/recorder.py` (`EmergencyRecorder`) | Ghi hình theo từng đoạn (segment) nối tiếp, mỗi đoạn dài `SEGMENT_DURATION_S` = 300 giây, gộp lại thành một phiên logic; mỗi phiên có thư mục riêng `save_dir/emergency_<session_id>/` |
| `recording/storage.py` (`StoragePolicy`) | Kiểm tra dung lượng đĩa trống trước khi tạo đoạn ghi mới — dưới `DEFAULT_MIN_FREE_BYTES` (1 GiB) thì từ chối (DISK_FULL), dưới `DEFAULT_LOW_FREE_BYTES` (2 GiB) thì vẫn cho phép nhưng có thể cảnh báo sớm. Không có khả năng xoá file |
| `recording/metadata.py` (`RecordingMetadataStore`) | Lưu/đọc `session.json` trong thư mục mỗi phiên, ghi nguyên tử (`os.replace()`), validate chặt khi đọc |
| `recording/recovery.py` (`recover_all`/`recover_session`) | Sau khi app khởi động lại từ một lần crash/mất điện, quét các thư mục phiên còn dở (STARTING/RECORDING/STOPPING) và đưa chúng về trạng thái kết thúc (FAILED) dựa trên bằng chứng file `.mkv` thực tế trên đĩa — không xoá file, không tự resume VLC/RTSP |
| `recording/startup.py` (`run_startup_recovery`) | Điểm gọi duy nhất để chạy recovery lúc khởi động app, trước khi `EmergencyRecorder` có thể bắt đầu phiên mới (được `src/main.py` gọi) |
| Thông báo khay hệ thống | `src/main.py` hiện balloon notification (qua `QSystemTrayIcon.showMessage`) báo số phiên đã khôi phục/không thể khôi phục hoàn toàn sau khi `run_startup_recovery()` chạy |
| `recording/retention.py` (`RetentionCriteria`/`is_eligible_for_cleanup`/`find_eligible_sessions`) | Xác định (không xoá) phiên ghi hình nào đủ điều kiện dọn dẹp: trạng thái kết thúc (STOPPED/FAILED/DISK_FULL), `protected=False`, và cũ hơn mốc thời gian do caller truyền vào. Chưa được gọi từ bất kỳ luồng thực thi nào của app — chỉ là policy độc lập |

## Yêu cầu

- Windows 10/11 (mục tiêu chính; một phần code có fallback an toàn khi chạy trên Linux/macOS để dev/test, nhưng đây không phải môi trường được hỗ trợ chính thức)
- [Python 3.10+](https://www.python.org/downloads/) nếu chạy từ mã nguồn
- [VLC media player](https://www.videolan.org/vlc/) bản desktop đã cài — cần để có `libvlc.dll`
- Camera Ezviz đã bật RTSP (trong app Ezviz: **Cài đặt thiết bị → Tính năng nâng cao → Địa chỉ Platform/RTSP**, bật RTSP và đặt mật khẩu riêng cho RTSP)

Thư viện Python (`requirements.txt`): `PySide6>=6.6.0`, `python-vlc>=3.0.20000`.

## Cài đặt / thiết lập

```bash
git clone https://github.com/tuananh511/ezviz-float-cam.git
cd ezviz-float-cam
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Để đóng gói thành `.exe`/installer riêng: xem thêm `requirements-dev.txt`, `build_exe.bat` và `installer/setup.iss`.

## Chạy ứng dụng

```bash
cd src
python main.py
```

Lần chạy đầu tiên app tự tạo file cấu hình tại `%APPDATA%\EzvizFloatCam\config.json` (copy từ `config/default_config.json`). Cách khuyến nghị để cấu hình camera là qua giao diện: click phải icon khay hệ thống → **Cài đặt...** → nhập thông tin RTSP → **Kiểm tra kết nối** → **Lưu**. Cũng có thể sửa trực tiếp `config.json`, cấu trúc xem `config/default_config.json`.

## Chạy test

```bash
pip install -r requirements-dev.txt
pytest
```

Bộ test dùng `pytest`, cấu hình trong `pytest.ini` (`testpaths = tests`). Các test liên quan tới VLC dùng fake/stub (xem `tests/conftest.py`), không cần cài camera thật hay VLC thật để chạy.

## Cấu trúc dự án

```
src/
  main.py                 # entry point
  glass_window.py         # cửa sổ nổi, hiệu ứng kính mờ, icon hành động
  stream_widget.py        # render video RTSP qua libVLC (memory callback)
  tray.py                 # icon khay hệ thống
  settings_dialog.py      # dialog cấu hình + kiểm tra kết nối
  config_loader.py        # đọc/ghi config.json theo user
  autostart.py            # khởi động cùng Windows (registry HKCU)
  windows_blur.py         # hiệu ứng Acrylic blur (Windows API)
  recorder.py             # EmergencyRecorder — ghi hình khẩn cấp theo đoạn
  recording/              # domain model + policy cho ghi hình (xem bảng kiến trúc ở trên)
tests/                    # pytest, ánh xạ theo từng module trên
config/default_config.json
installer/setup.iss        # cấu hình Inno Setup
build_exe.bat               # build .exe bằng PyInstaller
```

## Tình trạng phát triển

Dự án đang được phát triển tích cực. Phần giao diện/kết nối RTSP cốt lõi đã ổn định qua nhiều sprint; phần kiến trúc ghi hình khẩn cấp (bảng ở trên) đang được xây dựng dần theo từng module độc lập và đã có bộ test đi kèm cho từng phần, nhưng một số phần (ví dụ `retention.py`) vẫn ở dạng policy độc lập, chưa được nối vào luồng chạy thực tế của app.

## License

MIT — xem [LICENSE](LICENSE).
