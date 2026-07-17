"""
recorder.py — Sprint 5.5: Ghi hình khẩn cấp

Ghi lại luồng RTSP "main" (chất lượng cao) ra file .mkv cục bộ, HOÀN TOÀN
ĐỘC LẬP với StreamWidget đang hiển thị (cửa sổ chính dùng luồng "sub" nhẹ
để xem trực tiếp, mượt hơn) — cùng nguyên tắc "1 phiên libVLC riêng" đã dùng
cho nút "Kiểm tra kết nối" ở Sprint 4 (settings_dialog.py), tránh 2 luồng
tranh chấp nhau hoặc làm giật hình đang xem khi bấm ghi.

Dùng `sout=#std{access=file,mux=mkv,dst=...}` — đây là REMUX thẳng (không
decode/transcode) nên rất nhẹ CPU, và KHÔNG mở cửa sổ video nào (không cần
gắn video_set_callbacks hay set_hwnd) vì không có bước hiển thị nào cả.

Lý do chọn MKV thay vì MP4 (quyết định bổ sung sau khi hoàn thành S5.5):
MP4 ghi bảng chỉ mục file ("moov atom") vào CUỐI file, chỉ được ghi hoàn
chỉnh khi quá trình dừng diễn ra đúng quy trình (gọi stop()/_cleanup()).
Nếu app bị crash, mất điện, hoặc bị Task Manager "End task" giữa lúc đang
ghi — đúng tình huống "sự cố không tắt được" mà tính năng khẩn cấp này cần
chống chịu — file .mp4 dở dang thường KHÔNG đọc được. MKV (Matroska) không
có giới hạn này: ghi index dần trong lúc quay, nên file dở dang do ngắt đột
ngột vẫn phát được (có thể mất vài giây cuối, nhưng không mất trắng cả file).
"""

import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

import vlc

from config_loader import build_rtsp_url

_SUBDIR = "EzvizFloatCam"


def default_recording_dir() -> Path:
    """Thư mục GỢI Ý mặc định — chỉ dùng làm placeholder trong Cài đặt hoặc
    làm phương án dự phòng lúc bấm ghi nếu người dùng chưa từng chọn thư mục
    riêng. KHÔNG tự ghi giá trị này vào config.json nếu người dùng chưa xác
    nhận (giữ đúng nguyên tắc "để người dùng chọn qua Cài đặt")."""
    return Path.home() / "Videos" / _SUBDIR


class EmergencyRecorder(QObject):
    recording_started = Signal(str)   # đường dẫn file vừa bắt đầu ghi
    recording_stopped = Signal(str)   # đường dẫn file vừa dừng ghi (đã lưu)
    recording_error = Signal(str)     # thông báo lỗi hiển thị cho người dùng

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instance = None
        self.media_player = None
        self._filepath: str | None = None
        self._start_time: datetime.datetime | None = None

        # theo dõi trạng thái mỗi 500ms để phát hiện lỗi kết nối luồng main
        # (vd sai mật khẩu, camera không hỗ trợ main stream, mất mạng...)
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(500)
        self._watchdog.timeout.connect(self._check_state)

    def is_recording(self) -> bool:
        return self.media_player is not None

    def elapsed_seconds(self) -> int:
        if self._start_time is None:
            return 0
        return int((datetime.datetime.now() - self._start_time).total_seconds())

    def start(self, rtsp_cfg: dict, save_dir: str = ""):
        if self.is_recording():
            return

        try:
            target_dir = Path(save_dir) if save_dir else default_recording_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.recording_error.emit(f"Không tạo được thư mục lưu ghi hình: {exc}")
            return

        # Luôn ép dùng luồng "main" (chất lượng cao) để ghi hình khẩn cấp,
        # BẤT KỂ cửa sổ chính đang xem bằng luồng nào (thường là "sub").
        main_cfg = dict(rtsp_cfg)
        main_cfg["stream_type"] = "main"
        url = build_rtsp_url(main_cfg)

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = target_dir / f"emergency_{stamp}.mkv"
        self._filepath = str(filepath)

        vlc_args = ["--no-xlib", "--rtsp-tcp", "--quiet"]
        self.instance = vlc.Instance(vlc_args)
        self.media_player = self.instance.media_player_new()

        media = self.instance.media_new(url)
        # sout dùng dấu "/" thay vì "\" cho an toàn cú pháp (VLC vẫn hiểu
        # đúng đường dẫn Windows viết theo kiểu "/").
        dst = self._filepath.replace("\\", "/")
        media.add_option(f":sout=#std{{access=file,mux=mkv,dst={dst}}}")
        media.add_option(":sout-keep")
        self.media_player.set_media(media)
        self.media_player.play()

        self._start_time = datetime.datetime.now()
        self._watchdog.start()
        self.recording_started.emit(self._filepath)

    def _check_state(self):
        if self.media_player is None:
            return
        if self.media_player.get_state() == vlc.State.Error:
            path = self._filepath
            self._cleanup()
            self.recording_error.emit(
                "Mất kết nối luồng ghi hình (main) — file có thể không đầy đủ:\n"
                f"{path}"
            )

    def stop(self):
        if not self.is_recording():
            return
        path = self._filepath
        self._cleanup()
        self.recording_stopped.emit(path or "")

    def _cleanup(self):
        self._watchdog.stop()
        if self.media_player is not None:
            self.media_player.stop()
            self.media_player.release()
        if self.instance is not None:
            self.instance.release()
        self.media_player = None
        self.instance = None
        self._start_time = None
