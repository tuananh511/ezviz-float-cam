"""
recorder.py — Sprint 5.5: Ghi hình khẩn cấp (Task 3: chia đoạn/segment)

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

--- Task 3: ghi hình chia đoạn (segmented recording) ---

Một PHIÊN ghi hình khẩn cấp (RecordingSession, xem recording/session.py)
giờ có thể gồm NHIỀU file .mkv vật lý (RecordingSegment) nối tiếp nhau,
mỗi đoạn dài khoảng SEGMENT_DURATION_S giây, nhưng vẫn là MỘT phiên logic
duy nhất (cùng session_id) từ góc nhìn của GlassWindow/is_recording().
Mỗi phiên có thư mục riêng: save_dir/emergency_<session_id>/.

Nguyên tắc chọn: khi hết thời gian một đoạn, DỪNG HẲN VLC media player của
đoạn đó rồi mới TẠO MỚI một VLC instance/media_player cho đoạn tiếp theo —
không cố "mutate" một đối tượng vlc.Media đang chạy để đổi file đích giữa
chừng (vòng đời rõ ràng, dễ kiểm thử/khôi phục hơn là chỉnh sửa in-place).
"""

import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

import vlc

from config_loader import build_rtsp_url
from recording import (
    InvalidTransitionError,
    RecordingSegment,
    RecordingSession,
    RecordingStatus,
)

_SUBDIR = "EzvizFloatCam"

# Task 3: độ dài mỗi đoạn ghi hình khẩn cấp, tính bằng giây. Chưa có cấu
# hình cho người dùng chỉnh — đây là hằng số duy nhất cho scope này.
SEGMENT_DURATION_S = 300


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def default_recording_dir() -> Path:
    """Thư mục GỢI Ý mặc định — chỉ dùng làm placeholder trong Cài đặt hoặc
    làm phương án dự phòng lúc bấm ghi nếu người dùng chưa từng chọn thư mục
    riêng. KHÔNG tự ghi giá trị này vào config.json nếu người dùng chưa xác
    nhận (giữ đúng nguyên tắc "để người dùng chọn qua Cài đặt")."""
    return Path.home() / "Videos" / _SUBDIR


class EmergencyRecorder(QObject):
    recording_started = Signal(str)   # đường dẫn file (đoạn) vừa bắt đầu ghi
    recording_stopped = Signal(str)   # đường dẫn file (đoạn) vừa dừng ghi
    recording_error = Signal(str)     # thông báo lỗi hiển thị cho người dùng

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instance = None
        self.media_player = None
        self._filepath: str | None = None
        self._start_time: datetime.datetime | None = None

        # Task 3: trạng thái phiên ghi hình (nhiều đoạn, 1 session logic)
        self._session: RecordingSession | None = None
        self._session_dir: Path | None = None
        self._current_segment: RecordingSegment | None = None
        self._rtsp_url: str | None = None

        # theo dõi trạng thái mỗi 500ms để phát hiện lỗi kết nối luồng main
        # (vd sai mật khẩu, camera không hỗ trợ main stream, mất mạng...)
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(500)
        self._watchdog.timeout.connect(self._check_state)

        # Task 3: timer xoay vòng đoạn ghi hình — một QTimer DUY NHẤT,
        # single-shot, được start() lại sau mỗi lần xoay vòng thành công
        # (không bao giờ tạo thêm QTimer thứ hai).
        self._segment_timer = QTimer(self)
        self._segment_timer.setSingleShot(True)
        self._segment_timer.setInterval(SEGMENT_DURATION_S * 1000)
        self._segment_timer.timeout.connect(self._rotate_segment)

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
            base_dir = Path(save_dir) if save_dir else default_recording_dir()
            base_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.recording_error.emit(f"Không tạo được thư mục lưu ghi hình: {exc}")
            return

        # Luôn ép dùng luồng "main" (chất lượng cao) để ghi hình khẩn cấp,
        # BẤT KỂ cửa sổ chính đang xem bằng luồng nào (thường là "sub").
        # URL này được build MỘT LẦN và dùng lại cho mọi đoạn trong phiên.
        main_cfg = dict(rtsp_cfg)
        main_cfg["stream_type"] = "main"
        self._rtsp_url = build_rtsp_url(main_cfg)

        session = RecordingSession()
        session_dir = base_dir / f"emergency_{session.session_id}"
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.recording_error.emit(
                f"Không tạo được thư mục phiên ghi hình khẩn cấp: {exc}"
            )
            return

        session.transition_to(RecordingStatus.STARTING)
        self._session = session
        self._session_dir = session_dir

        # Đoạn đầu tiên: giữ nguyên hành vi trước Task 3 — lỗi ở bước tạo
        # VLC instance KHÔNG được bắt ở đây, sẽ propagate ra ngoài start()
        # (xem test_start_vlc_instance_creation_failure_propagates_uncaught).
        # Việc bắt lỗi có kiểm soát (transition FAILED + recording_error)
        # chỉ áp dụng cho các đoạn xoay vòng tiếp theo, xem _rotate_segment().
        self._start_segment()

        session.transition_to(RecordingStatus.RECORDING)
        self._start_time = datetime.datetime.now()
        self._watchdog.start()
        self._segment_timer.start()
        self.recording_started.emit(self._filepath)

    # ------------------------------------------------------------------
    # Task 3: vòng đời một đoạn (segment) ghi hình
    # ------------------------------------------------------------------

    def _build_segment_path(self) -> Path:
        """Đường dẫn file .mkv cho đoạn kế tiếp, trong thư mục phiên.

        Tên file dựa trên mốc thời gian hiện tại (sắp xếp theo thời gian
        một cách tự nhiên). Nếu trùng tên với một đoạn đã có trong phiên
        (cùng giây) hoặc trùng với một file đã tồn tại trên đĩa, thêm hậu
        tố "_NN" tăng dần — không bao giờ ghi đè lên một đoạn đã có.
        """
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        used_names = {
            Path(seg.path).name for seg in self._session.segments
        }

        candidate_name = f"{stamp}.mkv"
        suffix = 1
        while (
            candidate_name in used_names
            or (self._session_dir / candidate_name).exists()
        ):
            candidate_name = f"{stamp}_{suffix:02d}.mkv"
            suffix += 1

        return self._session_dir / candidate_name

    def _start_segment(self):
        """Tạo VLC instance/media_player MỚI và bắt đầu ghi một đoạn mới,
        gắn vào self._session hiện tại.

        An toàn khi có exception: nếu bất kỳ bước nào (Instance, media
        player, media, set_media, play) thất bại SAU KHI đã tạo được
        instance/media_player cục bộ, các tài nguyên VLC cục bộ đó được
        dừng/giải phóng NGAY trước khi exception được raise lại — không để
        rò rỉ. self.instance/self.media_player chỉ được gán khi mọi bước
        đã thành công, nên bug fix này không đổi observable behavior:
        exception vẫn propagate y như trước (start() ở đoạn đầu tiên vẫn
        để lỗi lọt ra ngoài, xem test_start_vlc_instance_creation_failure_propagates_uncaught).
        """
        segment_path = self._build_segment_path()

        vlc_args = ["--no-xlib", "--rtsp-tcp", "--quiet"]
        instance = None
        media_player = None
        try:
            instance = vlc.Instance(vlc_args)
            media_player = instance.media_player_new()

            media = instance.media_new(self._rtsp_url)
            # sout dùng dấu "/" thay vì "\" cho an toàn cú pháp (VLC vẫn
            # hiểu đúng đường dẫn Windows viết theo kiểu "/").
            dst = str(segment_path).replace("\\", "/")
            media.add_option(f":sout=#std{{access=file,mux=mkv,dst={dst}}}")
            media.add_option(":sout-keep")
            media_player.set_media(media)
            media_player.play()
        except Exception:
            if media_player is not None:
                media_player.stop()
                media_player.release()
            if instance is not None:
                instance.release()
            raise

        self.instance = instance
        self.media_player = media_player
        self._filepath = str(segment_path)

        segment = RecordingSegment(path=self._filepath, started_at=_utcnow())
        self._session.add_segment(segment)
        self._current_segment = segment

    def _release_current_vlc_player(self):
        """Dừng/giải phóng media_player + instance của đoạn ĐANG chạy,
        không đụng tới watchdog/segment_timer (dùng khi xoay vòng đoạn,
        lúc recording vẫn tiếp diễn ở đoạn kế tiếp).

        LUÔN gọi hàm này TRƯỚC _finalize_active_segment() — phải dừng hẳn
        VLC media player rồi mới lấy size_bytes/đánh dấu completed, để
        kích thước file và `ended_at` phản ánh đúng thời điểm file đã
        được VLC đóng/flush xong, không phải thời điểm còn đang ghi dở."""
        if self.media_player is not None:
            self.media_player.stop()
            self.media_player.release()
        if self.instance is not None:
            self.instance.release()
        self.media_player = None
        self.instance = None

    def _finalize_active_segment(self):
        """Đánh dấu đoạn đang ghi là completed (ghi lại thời gian kết thúc
        và kích thước file nếu lấy được).

        PHẢI được gọi SAU _release_current_vlc_player() — xem docstring ở
        đó. `ended_at` và `size_bytes` phải phản ánh trạng thái file SAU
        KHI VLC đã stop/release (đã flush/đóng file), không phải lúc file
        có thể vẫn đang được VLC ghi dở."""
        segment = self._current_segment
        if segment is None:
            return
        size_bytes = None
        try:
            size_bytes = Path(segment.path).stat().st_size
        except OSError:
            size_bytes = None
        segment.mark_completed(ended_at=_utcnow(), size_bytes=size_bytes)
        self._current_segment = None

    def _transition_session_safely(self, new_status: RecordingStatus, **kwargs):
        if self._session is None:
            return
        try:
            self._session.transition_to(new_status, **kwargs)
        except InvalidTransitionError:
            pass

    def _rotate_segment(self):
        """Gọi khi self._segment_timer hết giờ (hoặc trực tiếp, trong
        test): kết thúc đoạn hiện tại và bắt đầu đoạn kế tiếp, giữ nguyên
        session_id. Nếu không thể bắt đầu đoạn kế tiếp, dừng hẳn việc ghi
        hình (chuyển session sang FAILED) thay vì âm thầm coi như vẫn
        đang ghi."""
        if not self.is_recording() or self._session is None:
            return

        # Dừng hẳn VLC player của đoạn cũ TRƯỚC, rồi mới finalize segment
        # (size_bytes/ended_at chính xác) — xem docstring 2 hàm trên.
        self._release_current_vlc_player()
        self._finalize_active_segment()

        try:
            self._start_segment()
        except Exception as exc:  # noqa: BLE001 - lỗi VLC có thể là nhiều loại
            self._watchdog.stop()
            self._segment_timer.stop()
            self._start_time = None
            self._transition_session_safely(RecordingStatus.FAILED, error=str(exc))
            self.recording_error.emit(
                "Không thể bắt đầu đoạn ghi hình kế tiếp — đã dừng ghi hình "
                f"khẩn cấp:\n{exc}"
            )
            return

        # Đoạn kế tiếp đã bắt đầu thành công — hẹn giờ xoay vòng lần sau.
        self._segment_timer.start()

    def _check_state(self):
        if self.media_player is None:
            return
        if self.media_player.get_state() == vlc.State.Error:
            path = self._filepath
            self._watchdog.stop()
            self._segment_timer.stop()
            # Dừng hẳn VLC player TRƯỚC, rồi mới finalize segment — cùng
            # thứ tự như stop()/_rotate_segment(), xem docstring ở trên.
            self._release_current_vlc_player()
            self._finalize_active_segment()
            self._start_time = None
            self._transition_session_safely(
                RecordingStatus.FAILED,
                error="Mất kết nối luồng ghi hình (main)",
            )
            self.recording_error.emit(
                "Mất kết nối luồng ghi hình (main) — file có thể không đầy đủ:\n"
                f"{path}"
            )

    def stop(self):
        if not self.is_recording():
            return
        path = self._filepath
        self._watchdog.stop()
        self._segment_timer.stop()
        # Dừng hẳn VLC player TRƯỚC, rồi mới finalize segment — cùng thứ
        # tự như _rotate_segment()/_check_state(), xem docstring ở trên.
        self._release_current_vlc_player()
        self._finalize_active_segment()
        self._start_time = None

        self._transition_session_safely(RecordingStatus.STOPPING)
        self._transition_session_safely(RecordingStatus.STOPPED)

        self.recording_stopped.emit(path or "")
