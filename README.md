# EzvizFloatCam

> Cửa sổ nổi hiển thị luồng RTSP từ camera Ezviz trên Windows — kèm ghi hình thủ công, tự động ghi khi có chuyển động và tự dọn bản ghi cũ.

[![Release](https://img.shields.io/github/v/release/tuananh511/ezviz-float-cam)](https://github.com/tuananh511/ezviz-float-cam/releases)
[![License](https://img.shields.io/github/license/tuananh511/ezviz-float-cam)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)

## Giới thiệu

EzvizFloatCam kết nối tới camera Ezviz qua RTSP và hiển thị video trong một cửa sổ nhỏ, không viền, bo góc, hiệu ứng kính mờ (Acrylic), luôn nằm trên cùng các cửa sổ khác — để vừa làm việc vừa để mắt tới camera. App nằm ở khay hệ thống, có thể tự khởi động cùng Windows.

Ngoài xem trực tiếp, app còn có:

- **Ghi hình thủ công** bằng nút REC ngay trên cửa sổ (luồng chất lượng cao, chia đoạn 5 phút).
- **Tự động ghi khi có chuyển động**, hiện huy hiệu `AUTO REC` + viền cam trên hình, chạy độc lập với nút REC.
- **Tự xoá bản ghi tự động cũ** khi thư mục ghi hình vượt ngưỡng dung lượng; ghi thủ công không bao giờ bị tự xoá.
- **Khôi phục phiên ghi dở dang** sau khi app/máy bị tắt đột ngột.

## Tính năng

**Xem trực tiếp**

- Hiển thị stream RTSP, cửa sổ bo góc – kính mờ – luôn nổi, kéo-thả, resize bằng góc dưới-phải (giữ đúng tỉ lệ video).
- Tự kết nối lại khi mất tín hiệu (màn nhiễu "ĐANG KẾT NỐI LẠI" / "MẤT TÍN HIỆU"), tự khôi phục khi có tín hiệu.
- Giao diện gọn như trình phát video hiện đại: các nút (REC, tắt tiếng, thông tin, tay cầm resize) **chỉ hiện khi rê chuột vào cửa sổ** và mờ dần khi chuột rời đi, để lại hình sạch. Thông tin trạng thái (chấm kết nối, `REC`, `AUTO REC`) luôn hiện.
- Tắt tiếng (mute) ngay từ icon trên cửa sổ.
- Icon khay hệ thống: ẩn/hiện cửa sổ, bật/tắt stream, bật/tắt ghi tự động, mở Cài đặt, thoát.
- Hộp **Cài đặt** chia 3 tab (Kết nối / Ghi hình / Chuyển động), dùng công tắc gạt và thanh chọn kiểu Apple, có nút "Kiểm tra kết nối" trước khi lưu và thanh hiển thị mức dùng dung lượng.
- Tuỳ chọn khởi động cùng Windows (registry HKCU, không cần quyền admin).

**Ghi hình**

- Ghi thủ công (REC): luồng `main`, mỗi đoạn tối đa 5 phút, lưu `.mkv`.
- Ghi tự động theo chuyển động: độ nhạy 3 mức, thời gian ghi thêm sau chuyển động cuối, bỏ qua thay đổi ánh sáng, bỏ qua chuyển động quá ngắn, bỏ qua lúc camera tự xoay, có thể giới hạn vùng theo dõi (ROI).
- Tuỳ chọn ghi thêm **đoạn ngắn TRƯỚC khi phát hiện chuyển động** (pre-roll).
- Kiểm tra dung lượng ổ đĩa trước mỗi đoạn: dưới 1 GiB trống thì từ chối ghi (an toàn cho ổ hệ thống).
- Tự xoá bản ghi tự động cũ nhất khi thư mục ghi hình vượt ngưỡng (mặc định 20 GB).
- Mỗi lần ghi có thư mục tên theo ngày giờ và file `thong-tin.txt` tiếng Việt để xem nhanh.

## Tải về và dùng ngay

1. Cài [VLC media player](https://www.videolan.org/vlc/) bản desktop (app dùng `libvlc.dll` của VLC).
2. Vào trang [Releases](https://github.com/tuananh511/ezviz-float-cam/releases), tải `EzvizFloatCam.exe` của bản mới nhất, để vào một thư mục bất kỳ rồi chạy. Không cần cài Python.
3. Click phải icon ở khay hệ thống → **Cài đặt...** → nhập thông tin camera → **Kiểm tra kết nối** → **Lưu**.

> Windows SmartScreen có thể cảnh báo vì file chưa được ký số. Chọn **More info → Run anyway** nếu bạn tin tưởng nguồn tải.

### Chuẩn bị camera

Camera cần bật RTSP: trong app Ezviz vào **Cài đặt thiết bị → Tính năng nâng cao → Địa chỉ Platform/RTSP**, bật RTSP và đặt mật khẩu cho RTSP. App dựng địa chỉ theo dạng:

```
rtsp://<user>:<mật khẩu>@<IP camera>:554/h264/<channel>/<sub|main>/av_stream
```

Camera và máy tính phải cùng mạng LAN. Nên đặt IP tĩnh (hoặc gán IP cố định trong router) cho camera để địa chỉ không đổi.

## Sử dụng

| Thao tác | Cách làm |
|---|---|
| Di chuyển / đổi cỡ cửa sổ | Kéo cửa sổ / kéo góc dưới-phải |
| Ghi hình thủ công | Rê chuột vào cửa sổ, bấm nút REC trên góc trên-phải, bấm lần nữa để dừng. Khi đang ghi nút REC và `REC mm:ss` luôn hiện |
| Tắt/bật tiếng | Icon loa trên cửa sổ (khi đang tắt tiếng icon luôn hiện, màu đỏ) |
| Thông tin phiên bản | Icon `i` góc dưới-trái (hiện khi rê chuột) |
| Bật/tắt ghi tự động | Menu khay hệ thống → **Tự động ghi khi có chuyển động** |
| Đổi cấu hình | Menu khay → **Cài đặt...** |
| Ẩn / hiện / thoát | Menu khay hệ thống |

Các nút điều khiển chỉ hiện khi chuột ở trong cửa sổ. Chấm tròn góc trên-trái cho biết trạng thái kết nối (xanh: đang xem, vàng: đang kết nối, đỏ: mất tín hiệu). Khi đang ghi tự động, cửa sổ có **viền cam** và huy hiệu `AUTO REC mm:ss` ở góc dưới-trái; khi ghi tay thì `REC` đỏ ở góc trên-phải. Hai chế độ chạy được cùng lúc.

## Tự động ghi khi có chuyển động

App lấy mẫu khung hình đang xem (~2 khung/giây), so với "nền" để phát hiện chuyển động. Khi có chuyển động ở vài lần lấy mẫu liên tiếp, app bắt đầu một phiên ghi riêng, và ghi thêm `post_roll_s` giây sau chuyển động cuối rồi dừng.

- **Độc lập với REC thủ công**: ghi tự động dùng một recorder riêng (phiên libVLC riêng, thư mục riêng đuôi `_TuDong`). Bật/tắt cái này không ảnh hưởng cái kia, file không bao giờ ghi đè nhau.
- **Chống báo nhầm** (xem thêm mục "Giảm báo nhầm" bên dưới): bỏ qua vệt sáng (đèn cửa, đèn pha), bỏ qua chuyển động quá ngắn, và bỏ qua lúc camera tự xoay hoặc tự đổi sáng toàn khung (chuyển IR ngày/đêm).
- **Khi lỗi** (đầy ổ đĩa, mất luồng): huy hiệu đổi thành `AUTO REC LỖI` khoảng 15 giây, app nghỉ 60 giây rồi mới thử lại, không hiện hộp thoại làm phiền.
- **Độ nhạy**: chỉnh trong Cài đặt (`Thấp` / `Vừa` / `Cao`). Nếu báo nhầm nhiều thì giảm độ nhạy hoặc khoanh vùng theo dõi; nếu bỏ sót thì tăng.
- **Vùng theo dõi (ROI)**: đặt `roi` trong `config.json`, ví dụ chỉ theo dõi nửa phải khung hình quanh cửa: `"roi": [0.5, 0.0, 1.0, 1.0]` (tỉ lệ 0–1: trái, trên, phải, dưới).

### Giảm báo nhầm

Ghi tự động có 4 lớp lọc, chỉnh trong **Cài đặt → Chuyển động**:

| Tình huống hay gặp | Cách app xử lý | Chỉnh ở đâu |
|---|---|---|
| Đèn cửa bật, đèn pha xe quét qua (ánh sáng đổi nhưng không có người) | **Bỏ qua thay đổi ánh sáng**: so sánh sau khi trừ độ lệch sáng trung bình của từng ô nhỏ, nên chỉ phần *cấu trúc* hình ảnh đổi (người/vật đi vào) mới tính, vệt sáng thì bỏ qua | Công tắc "Bỏ qua thay đổi ánh sáng" (`motion.ignore_light_changes`) |
| Vệt sáng/chuyển động thoáng qua | **Chuyển động phải kéo dài** ít nhất N giây mới bắt đầu ghi (cho phép vài nhịp "đứng yên" xen giữa khi người đi chậm) | "Chuyển động phải kéo dài" (`motion.min_duration_s`, mặc định 2 giây) |
| Camera tự xoay (theo dõi chuyển động, tự quay về vị trí, quét 360°) làm đổi gần như toàn khung | Nhận ra "camera đang di chuyển", **tạm dừng phát hiện** cho tới `camera_settle_s` giây sau lần xoay cuối, rồi lấy lại khung hình làm nền | `motion.camera_settle_s` (mặc định 10 giây) |
| Đổi sáng toàn khung (camera tự chỉnh phơi sáng, chuyển IR) | Coi là đổi cảnh, không phải chuyển động, cũng tạm dừng như trên | — |

Lưu ý:

- Do bỏ qua ánh sáng, một vật **đồng màu, đặc, che kín cả ô** (vd người mặc đồ trơn đứng sát camera) chủ yếu được nhận ra qua phần *viền* của nó. Nếu thấy bỏ sót người, tắt "Bỏ qua thay đổi ánh sáng" hoặc tăng độ nhạy.
- Nếu camera tự xoay khi đang theo dõi người thật, thời điểm xoay không được tính là chuyển động; bản ghi tự dừng sau `post_roll_s` kể từ chuyển động thật cuối cùng.
- Cách dứt điểm nhất cho camera tự xoay là **tắt tính năng theo dõi chuyển động / tự quay về vị trí / tự hiệu chỉnh** trong app Ezviz (tên mục tuỳ đời camera) nếu bạn không cần.
- Nếu vẫn báo nhầm do một vùng cố định (cửa kính, cây cối, màn hình TV...), khoanh vùng theo dõi bằng `motion.roi`.

### Ghi đoạn trước chuyển động (pre-roll)

Ghi tự động chỉ bắt đầu sau khi chuyển động đã kéo dài đủ lâu, nên vài giây đầu của sự kiện dễ bị mất. Đặt **"Ghi thêm đoạn trước chuyển động"** (`motion.pre_roll_s`, 0–30 giây, mặc định **tắt**) để app giữ một bộ đệm cuốn chiếu và ghi thêm đoạn ngay trước khi phát hiện.

- Cách hoạt động: một phiên VLC riêng chạy liên tục trên luồng **nhẹ (sub)**, ghi các đoạn ~2 giây vào thư mục tạm (`%TEMP%\EzvizFloatCam\preroll`) và tự xoá đoạn cũ; khi có chuyển động, các đoạn gần nhất được ghép thành `00-truoc-chuyen-dong.ts` trong thư mục lần ghi.
- **Đánh đổi**: thêm một kết nối RTSP liên tục tới camera (nếu camera giới hạn số kết nối, có thể gây rớt kết nối) và ghi đĩa liên tục một lượng nhỏ (cỡ bitrate luồng nhẹ, ghi đè trong thư mục tạm). Vì vậy mặc định tắt.
- Đoạn trước chuyển động có chất lượng luồng nhẹ và **không có tiếng**; có thể hở khoảng 1–3 giây giữa cuối đoạn này và lúc bản ghi chính bắt đầu.
- Lỗi bộ đệm (mất kết nối, thiếu VLC...) chỉ làm mất đoạn pre-roll; ghi tự động vẫn chạy bình thường, bộ đệm tự khởi động lại sau 15 giây.

## Thư mục ghi hình

Mặc định lưu ở `%USERPROFILE%\Videos\EzvizFloatCam` (đổi trong Cài đặt). Mỗi lần ghi là một thư mục đặt tên theo ngày giờ (giờ địa phương) và loại ghi:

```
Videos\EzvizFloatCam\
├─ 2026-11-22_14-30-05_TuDong\      ← ghi TỰ ĐỘNG khi có chuyển động
│   ├─ 00-truoc-chuyen-dong.ts      ← (chỉ khi bật pre-roll) đoạn ngay TRƯỚC khi phát hiện chuyển động
│   ├─ 14-30-05.mkv                 ← mỗi đoạn tối đa 5 phút, đặt tên theo giờ bắt đầu
│   ├─ 14-35-05.mkv
│   ├─ thong-tin.txt                ← ghi chú dễ đọc: bắt đầu/kết thúc, thời lượng, dung lượng, trạng thái
│   └─ session.json                 ← dữ liệu máy đọc (khôi phục sau crash), không cần quan tâm
└─ 2026-11-22_16-02-11_ThuCong\     ← ghi THỦ CÔNG (nút REC), được bảo vệ khỏi tự xoá
```

Thư mục kiểu cũ vẫn được nhận ra: `emergency_<id>` coi là ghi thủ công (được bảo vệ), `emergency_motion_<id>` coi là ghi tự động.

## Tự xoá bản ghi cũ

Trong **Cài đặt...** đặt "Dung lượng tối đa thư mục ghi hình" (mặc định 20 GB, bật sẵn). Mỗi 60 giây, sau mỗi lần ghi tự động kết thúc và khi khởi động app, app cộng dung lượng các thư mục ghi hình. Nếu vượt ngưỡng thì **xoá dần bản ghi TỰ ĐỘNG cũ nhất** cho tới khi còn khoảng 90% ngưỡng.

- **Ghi thủ công không bao giờ bị tự xoá**, nhưng vẫn tính vào dung lượng. Nếu riêng ghi thủ công đã vượt ngưỡng, app chỉ cảnh báo ở console và không xoá thêm gì.
- Không bao giờ xoá phiên đang ghi, phiên chưa kết thúc, hay thư mục không có `session.json` hợp lệ.
- Thư mục/file lạ bạn để chung trong thư mục ghi hình không bị tính và không bị đụng tới. Chỉ xoá đúng file app tạo (`.mkv`, `session.json`, `thong-tin.txt`); nếu thư mục phiên còn file lạ thì thư mục được giữ lại.
- **Xoá là xoá vĩnh viễn** (không qua Thùng rác). Muốn giữ một bản ghi tự động: chép/di chuyển nó ra ngoài thư mục ghi hình, hoặc đặt `"protected": true` trong `session.json` của nó.

## Cấu hình (`config.json`)

File nằm ở `%APPDATA%\EzvizFloatCam\config.json`, tự tạo ở lần chạy đầu từ `config/default_config.json`. Nên chỉnh qua **Cài đặt...**; sửa tay chỉ cần khi muốn dùng các khoá không có trên giao diện (đóng app trước khi sửa). Các mục `motion` và `retention` là tuỳ chọn — thiếu thì dùng giá trị mặc định.

| Khoá | Mặc định | Ý nghĩa |
|---|---|---|
| `rtsp.ip` / `port` / `username` / `password` | `192.168.1.100` / `554` / `admin` / rỗng | Thông tin kết nối camera |
| `rtsp.stream_type` | `sub` | Luồng để xem: `sub` (nhẹ) hoặc `main` (nét) |
| `rtsp.channel` | `ch1` | Kênh camera |
| `window.width` / `height` | `320` / `200` | Kích thước cửa sổ |
| `window.pos_x` / `pos_y` | `null` | Vị trí (tự lưu khi di chuyển) |
| `window.opacity` / `corner_radius` | `0.95` / `16` | Độ trong suốt / độ bo góc |
| `autostart` | `false` | Khởi động cùng Windows |
| `audio.muted` | `false` | Tắt tiếng |
| `recording.save_dir` | rỗng | Thư mục lưu; rỗng = `Videos\EzvizFloatCam` |
| `motion.enabled` | `true` | Bật/tắt ghi tự động |
| `motion.sensitivity` | `medium` | `low` / `medium` / `high` |
| `motion.post_roll_s` | `15` | Ghi thêm sau chuyển động cuối, 5–300 giây |
| `motion.stream_type` | `main` | Luồng để ghi tự động: `main` (nét) hoặc `sub` (nhẹ hơn, dùng khi camera giới hạn số kết nối cùng lúc) |
| `motion.roi` | `null` | `null` = cả khung; hoặc `[x0, y0, x1, y1]` tỉ lệ 0–1 |
| `motion.min_duration_s` | `2.0` | Chuyển động phải kéo dài ít nhất bấy nhiêu giây mới bắt đầu ghi (0.5–10) |
| `motion.ignore_light_changes` | `true` | Bỏ qua thay đổi ánh sáng cục bộ (đèn cửa, đèn pha) |
| `motion.camera_settle_s` | `10` | Camera tự xoay/đổi cảnh thì tạm dừng phát hiện bấy nhiêu giây sau lần cuối (0–120) |
| `motion.pre_roll_s` | `0` | Ghi thêm đoạn trước chuyển động, 0 = tắt, tối đa 30 giây |
| `retention.enabled` | `true` | Bật/tắt tự xoá bản ghi tự động cũ |
| `retention.max_gb` | `20` | Ngưỡng dung lượng thư mục ghi hình, 1–5000 GB |

## Giới hạn đã biết

- Ghi tự động bắt đầu **sau** khi phát hiện chuyển động (và sau `min_duration_s`), nên vài giây đầu của sự kiện có thể không có trong file; bật pre-roll để bù (có đánh đổi, xem trên).
- Người đứng yên rất lâu sẽ bị "nền" hấp thụ dần, ghi tự động sẽ dừng sau `post_roll_s`.
- Ban đêm / thiếu sáng thì nhiễu hình tăng, phát hiện chuyển động kém ổn định hơn. Việc nhận ra "camera đang xoay" dựa trên heuristic, chưa được thử với mọi đời camera Ezviz.
- Ghi tay và ghi tự động cùng chạy sẽ mở thêm một kết nối RTSP tới camera; nếu camera rớt kết nối thì đặt `motion.stream_type` là `sub`.
- Xoá tự động là vĩnh viễn (xem mục trên).
- Chỉ hỗ trợ chính thức Windows 10/11. Một phần code có fallback để dev/test trên Linux/macOS nhưng không phải môi trường được hỗ trợ.

## Phát triển

### Chạy từ mã nguồn

Cần [Python 3.10+](https://www.python.org/downloads/) và VLC desktop. Với [uv](https://docs.astral.sh/uv/):

```powershell
git clone https://github.com/tuananh511/ezviz-float-cam.git
cd ezviz-float-cam
uv venv
uv pip install -r requirements-dev.txt
cd src
uv run main.py
```

Hoặc dùng `venv` + `pip` như bình thường (`python -m venv venv`, `venv\Scripts\activate`, `pip install -r requirements-dev.txt`, `python src\main.py`).

### Chạy test

```powershell
uv run pytest
```

Test dùng `pytest` (`pytest.ini`: `testpaths = tests`), phần VLC được giả lập bằng stub trong `tests/conftest.py`, nên không cần camera hay VLC thật để chạy.

### Build file .exe

```powershell
.\build_exe.bat
```

Script dùng `.venv\` nếu có, và build bằng PyInstaller (onefile, không hiện console) ra `dist\EzvizFloatCam.exe`. Nếu bạn có sẵn file `ezvizfloatcam.spec` (file này bị `.gitignore`) thì script build theo spec đó. Máy chạy file exe vẫn cần cài VLC.

### Phát hành bản mới

1. Sửa `APP_VERSION` trong `src/version.py`, chạy `uv run pytest`, commit.
2. Tạo tag `vX.Y.Z` và push cả commit lẫn tag.
3. `.\build_exe.bat`, chạy thử `dist\EzvizFloatCam.exe`.
4. Trên GitHub: **Releases → Draft a new release**, chọn tag, đính kèm `EzvizFloatCam.exe`, dán ghi chú phát hành.

## Kiến trúc

```
src/
  main.py                 entry point; chạy khôi phục phiên dở dang lúc khởi động
  glass_window.py         cửa sổ nổi, điều khiển hiện khi rê chuột, icon REC/mute/about, huy hiệu AUTO REC
  stream_widget.py        render video RTSP qua libVLC (memory callback); cấp khung hình cho phát hiện chuyển động
  tray.py                 icon khay hệ thống và menu
  settings_dialog.py      dialog cấu hình 3 tab + kiểm tra kết nối
  ui_widgets.py           công tắc gạt (ToggleSwitch) và thanh chọn (SegmentedControl) tự vẽ bằng QPainter
  config_loader.py        đọc/ghi config.json theo user
  autostart.py            khởi động cùng Windows (registry HKCU)
  windows_blur.py         hiệu ứng Acrylic blur (Windows API)
  recorder.py             EmergencyRecorder: ghi theo đoạn, dùng chung cho ghi tay (kind=manual) và ghi tự động (kind=auto)
  motion.py               phát hiện chuyển động + chính sách bắt đầu/dừng ghi (stdlib thuần)
  motion_controller.py    nối StreamWidget -> motion -> recorder tự động (Qt)
  preroll_buffer.py       bộ đệm cuốn chiếu (VLC livehttp) cho đoạn trước chuyển động (Qt + libVLC)
  cleanup_controller.py   chạy dọn dẹp dung lượng định kỳ (Qt)
  recording/              domain + policy ghi hình (stdlib thuần, không phụ thuộc PySide6/VLC)
    session.py            RecordingSession/Segment, state machine STARTING→RECORDING→STOPPING→STOPPED/FAILED/DISK_FULL
    storage.py            StoragePolicy: kiểm tra ổ đĩa trống trước mỗi đoạn
    metadata.py           session.json: ghi nguyên tử (os.replace), validate chặt khi đọc
    naming.py             quy ước tên thư mục/file ghi hình
    summary.py            thong-tin.txt dễ đọc
    recovery.py           đưa phiên dở dang (crash/mất điện) về trạng thái kết thúc, dựa trên file .mkv thực tế
    startup.py            điểm gọi khôi phục lúc khởi động app
    retention.py          policy: phiên nào đủ điều kiện bị dọn
    cleanup.py            quét thư mục, lập kế hoạch và xoá bản ghi cũ vượt ngưỡng
    preroll.py            dựng chuỗi sout bộ đệm, chọn/ghép đoạn đệm (stdlib thuần)
tests/                    pytest, ánh xạ theo từng module
config/default_config.json
assets/app_icon.ico
build_exe.bat             build .exe bằng PyInstaller
```

Nguyên tắc thiết kế: các module trong `recording/` và `motion.py` là code thuần (chỉ dùng thư viện chuẩn, không PySide6/VLC) nên test được không cần giao diện; các controller Qt chỉ làm phần "dây nối".

## License

MIT — xem [LICENSE](LICENSE).
