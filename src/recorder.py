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

--- Task 5: tích hợp StoragePolicy (src/recording/storage.py) ---

StoragePolicy được gọi ở CẤP CALLER (start()/_rotate_segment()), KHÔNG
gọi bên trong _start_segment() — _start_segment() vẫn chỉ biết cách tạo
một đoạn, không biết/không quan tâm chính sách lưu trữ. Trước khi tạo
BẤT KỲ đoạn nào (đoạn đầu tiên trong start(), hoặc đoạn kế tiếp trong
_rotate_segment()), self._enforce_storage_policy_or_abort() kiểm tra
dung lượng đĩa còn trống:

- ALLOW / ALLOW_LOW_SPACE: cho phép tạo đoạn (ALLOW_LOW_SPACE vẫn tạo
  đoạn, chỉ là dấu hiệu cảnh báo sớm, không phải một cách xử lý khác).
- DISK_FULL: KHÔNG tạo VLC instance nào — session chuyển sang
  RecordingStatus.DISK_FULL, timer liên quan (watchdog/segment_timer)
  được dừng, recording_error được emit.
- CHECK_FAILED: cùng cách xử lý như DISK_FULL (không tạo VLC, dừng
  timer, emit recording_error) nhưng session chuyển sang
  RecordingStatus.FAILED — không biết chắc còn đủ chỗ hay không thì coi
  như không an toàn, nhưng đây không phải "hết đĩa" nên dùng trạng thái
  lỗi chung thay vì DISK_FULL.

QUAN TRỌNG: kiểm tra chính sách lưu trữ cho đoạn ĐẦU TIÊN diễn ra khi
session vẫn còn ở STARTING — KHÔNG chuyển session sang RECORDING trước
để "mượn" đường DISK_FULL từ RECORDING. Làm vậy sẽ khiến session bị đánh
dấu RECORDING sai lệch nếu _start_segment() sau đó thất bại (xem
test_start_vlc_instance_creation_failure_propagates_uncaught — session
phải ở lại STARTING khi lỗi này xảy ra, không được "nhảy cóc" qua
RECORDING). Thay vào đó, recording/session.py (Task 5) được mở rộng
thêm đúng hai transition còn thiếu: STARTING -> DISK_FULL (mới) và
STARTING -> FAILED (đã có sẵn từ Task 2) — nhờ vậy session có thể
chuyển thẳng từ STARTING sang DISK_FULL/FAILED mà không cần đi qua
RECORDING trước. session.transition_to(RECORDING) chỉ được gọi SAU KHI
_start_segment() của đoạn đầu tiên đã thành công, giữ đúng ngữ nghĩa
gốc trước Task 5.

--- Task 7: tích hợp RecordingMetadataStore (src/recording/metadata.py) ---

self._metadata_store (một RecordingMetadataStore trỏ vào session_dir
của phiên hiện tại) được tạo trong start(), CÙNG thời điểm với
self._storage_policy. Việc ghi session.json chỉ diễn ra ở đúng BA thời
điểm rõ ràng, không rải rác:

1. "initial metadata" — NGAY sau khi session chuyển sang STARTING và
   session_dir đã tồn tại, TRƯỚC _enforce_storage_policy_or_abort() và
   TRƯỚC bất kỳ VLC nào được tạo. Đây là bản ghi sớm nhất có thể, để
   nếu crash xảy ra trước khi đoạn đầu tiên kịp ghi, session.json vẫn
   phản ánh đúng "phiên này đã từng bắt đầu STARTING lúc nào".
2. "finalize" — mỗi khi MỘT ĐOẠN được finalize (_finalize_active_segment
   trong _rotate_segment()/stop()/_check_state()), NGAY sau khi finalize
   xong (VLC của đoạn đó đã release từ trước — xem
   _release_current_vlc_player()/_finalize_active_segment() ở trên).
   self._session.recalculate_total_bytes() được gọi trước khi save() để
   total_bytes trên đĩa luôn khớp tổng size_bytes các đoạn ĐÃ hoàn tất.
3. "failure" — mỗi khi session chuyển sang một trạng thái kết thúc do
   lỗi (DISK_FULL/FAILED, trong _enforce_storage_policy_or_abort() và
   trong nhánh except của _rotate_segment()), NGAY sau transition đó.

KHÔNG có lần ghi nào xảy ra ngay khi một đoạn MỚI bắt đầu (kể cả đoạn
đầu tiên trong start() hay đoạn kế tiếp sau rotate) — self._session
trong bộ nhớ vẫn là nguồn sự thật khi đang ghi dở một đoạn; session.json
chỉ cần phản ánh đúng trạng thái tại các mốc ổn định (bắt đầu phiên,
đoạn vừa hoàn tất, phiên kết thúc/lỗi), không cần cập nhật liên tục.

Chính sách khi save() thất bại (self._persist_metadata(), xem docstring
của hàm) chia làm hai trường hợp, tuỳ thời điểm:

- Ghi "initial metadata" trong start() thất bại: KHÔNG có VLC nào đã bị
  đụng tới ở bước này (đúng bất biến "không đụng VLC trước khi storage
  policy cho phép"), nên start() dừng lại NGAY, coi như một lỗi khởi
  động (cùng nhóm với lỗi mkdir ở trên) — session chuyển sang FAILED,
  KHÔNG có _start_segment() nào được gọi, không VLC nào được tạo.
- Ghi "finalize"/"failure" thất bại (sau khi VLC của đoạn đó đã release
  xong): recorder KHÔNG hoàn tác các bước đã xảy ra (VLC đã release,
  session đã transition đúng ngữ nghĩa) — một session.json không ghi
  được không được phép biến thành việc "rò rỉ" VLC hay việc bịa/giữ lại
  một session.json cũ sai lệch. recording_error được emit để báo lỗi ghi
  metadata, nhưng vòng đời ghi hình (VLC/segment/session) tiếp tục như
  không có RecordingMetadataStore.
"""

import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

import vlc

from config_loader import build_rtsp_url
from recording import (
    InvalidTransitionError,
    RecordingMetadataStore,
    RecordingSegment,
    RecordingSession,
    RecordingStatus,
    StorageDecision,
    StoragePolicy,
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

        # Task 5: chính sách kiểm tra dung lượng đĩa cho phiên hiện tại
        # (tạo mới trong start(), gắn với self._session_dir của phiên đó).
        self._storage_policy: StoragePolicy | None = None

        # Task 7: lưu trữ session.json cho phiên hiện tại (tạo mới trong
        # start(), gắn với self._session_dir của phiên đó — xem ghi chú
        # Task 7 ở đầu file cho các thời điểm ghi và chính sách lỗi).
        self._metadata_store: RecordingMetadataStore | None = None

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
        self._storage_policy = StoragePolicy(session_dir)
        self._metadata_store = RecordingMetadataStore(session_dir)

        # Task 7: ghi "initial metadata" NGAY sau khi session_dir tồn tại
        # và session đã STARTING, TRƯỚC storage-policy check và TRƯỚC bất
        # kỳ VLC nào (xem ghi chú Task 7 ở đầu file). Nếu ghi thất bại,
        # coi như một lỗi khởi động — dừng lại NGAY, không tạo VLC nào,
        # cùng cách xử lý như lỗi mkdir ở trên.
        if not self._persist_metadata():
            self._transition_session_safely(
                RecordingStatus.FAILED,
                error="Không ghi được session.json ban đầu",
            )
            return

        # Task 5: kiểm tra chính sách lưu trữ TRƯỚC khi tạo đoạn đầu
        # tiên, trong khi session vẫn còn ở STARTING (xem ghi chú Task 5
        # ở đầu file — session KHÔNG được chuyển sang RECORDING sớm chỉ
        # để hợp lệ hoá DISK_FULL).
        if not self._enforce_storage_policy_or_abort():
            return

        # Đoạn đầu tiên: giữ nguyên hành vi trước Task 3 — lỗi ở bước tạo
        # VLC instance KHÔNG được bắt ở đây, sẽ propagate ra ngoài start()
        # (xem test_start_vlc_instance_creation_failure_propagates_uncaught).
        # Việc bắt lỗi có kiểm soát (transition FAILED + recording_error)
        # chỉ áp dụng cho các đoạn xoay vòng tiếp theo, xem _rotate_segment().
        # Session vẫn ở STARTING cho tới khi bước này thành công — nếu nó
        # raise, session KHÔNG được đánh dấu RECORDING (xem ghi chú Task 5).
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
        media = None
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
            # Task 10: "media" (từ instance.media_new()) là TÀI NGUYÊN VLC
            # THỨ BA có thể đã được tạo cục bộ trước khi một bước sau đó
            # (add_option/set_media/play) thất bại — trước bản vá này, chỉ
            # media_player/instance được release() ở đây, còn media thì
            # KHÔNG, bất kể docstring phía trên đã claim ngược lại. Giải
            # phóng nó ở đây khớp đúng nguyên tắc "mọi tài nguyên VLC cục bộ
            # đã tạo phải được dọn trước khi exception propagate" cho CẢ BA
            # loại tài nguyên (Instance/MediaPlayer/Media), không chỉ hai.
            if media_player is not None:
                media_player.stop()
                media_player.release()
            if media is not None:
                media.release()
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

    # ------------------------------------------------------------------
    # Task 7: tích hợp RecordingMetadataStore — xem ghi chú Task 7 ở đầu
    # file cho ĐÚNG BA thời điểm gọi hàm này (initial/finalize/failure)
    # và chính sách khi save() thất bại.
    # ------------------------------------------------------------------

    def _persist_metadata(self) -> bool:
        """Ghi self._session ra session.json qua self._metadata_store.

        Luôn recalculate_total_bytes() trước khi save() để total_bytes
        trên đĩa chỉ tính các đoạn ĐÃ hoàn tất (completed=True) — không
        bao giờ tính một đoạn đang ghi dở.

        KHÔNG BAO GIỜ raise ra ngoài: mọi exception từ save() (OSError,
        MetadataError, ...) đều bị bắt lại ở đây, emit recording_error,
        rồi trả về False. Hàm này bản thân KHÔNG đụng tới VLC theo bất
        kỳ cách nào — ở mọi nơi gọi hàm này, VLC của đoạn liên quan hoặc
        chưa từng được tạo (lần ghi "initial" trong start()) hoặc đã
        được stop()/release() từ trước (lần ghi "finalize"/"failure",
        luôn diễn ra SAU _release_current_vlc_player()) — nên một lần
        save() thất bại không thể khiến VLC bị rò rỉ dù caller xử lý
        giá trị trả về (True/False) như thế nào.

        Trả về True nếu ghi thành công. Caller tự quyết định phải làm gì
        khi nhận False — start() coi đây là lỗi khởi động (dừng lại,
        không tạo VLC); các nơi gọi khác (sau khi VLC đã release) chỉ
        cần để recording_error đã được emit ở đây báo cho người dùng,
        không hoàn tác bất kỳ bước nào đã xảy ra.
        """
        if self._session is None or self._metadata_store is None:
            return False
        self._session.recalculate_total_bytes()
        try:
            self._metadata_store.save(self._session)
        except Exception as exc:  # noqa: BLE001 - OSError, MetadataError, ...
            self.recording_error.emit(
                "Không ghi được session.json (không ảnh hưởng tới file "
                f"ghi hình đang có trên đĩa):\n{exc}"
            )
            return False
        return True

    def _transition_session_safely(self, new_status: RecordingStatus, **kwargs):
        if self._session is None:
            return
        try:
            self._session.transition_to(new_status, **kwargs)
        except InvalidTransitionError:
            pass

    # ------------------------------------------------------------------
    # Task 5: tích hợp StoragePolicy — gọi ở cấp caller, TRƯỚC khi tạo
    # bất kỳ đoạn ghi hình mới nào (đoạn đầu tiên trong start(), hoặc
    # đoạn kế tiếp trong _rotate_segment()).
    # ------------------------------------------------------------------

    def _enforce_storage_policy_or_abort(self) -> bool:
        """Kiểm tra self._storage_policy TRƯỚC khi caller được phép gọi
        _start_segment(). Trả về True nếu được phép tạo đoạn mới
        (ALLOW/ALLOW_LOW_SPACE) — caller tiếp tục như bình thường.

        Trả về False nếu bị từ chối (DISK_FULL/CHECK_FAILED) — trong
        trường hợp đó, hàm này đã TỰ xử lý toàn bộ hậu quả (không tạo
        VLC nào ở đây hay ở caller): dừng watchdog/segment_timer, xoá
        _start_time, chuyển self._session sang trạng thái kết thúc phù
        hợp (DISK_FULL hoặc FAILED), và emit recording_error. Caller chỉ
        cần return ngay khi nhận False — KHÔNG được gọi _start_segment()
        sau đó."""
        result = self._storage_policy.check()
        if result.allows_new_segment():
            return True

        self._watchdog.stop()
        self._segment_timer.stop()
        self._start_time = None

        if result.decision is StorageDecision.DISK_FULL:
            self._transition_session_safely(
                RecordingStatus.DISK_FULL, error=result.reason
            )
            self.recording_error.emit(
                "Hết dung lượng đĩa — đã dừng ghi hình khẩn cấp:\n"
                f"{result.reason}"
            )
        else:  # StorageDecision.CHECK_FAILED
            self._transition_session_safely(
                RecordingStatus.FAILED, error=result.reason
            )
            self.recording_error.emit(
                "Không kiểm tra được dung lượng đĩa — đã dừng ghi hình "
                f"khẩn cấp:\n{result.reason}"
            )

        # Task 7: ghi metadata "failure" (DISK_FULL/FAILED) NGAY sau khi
        # session đã transition — không có VLC nào bị đụng ở nhánh này
        # (đoạn kế tiếp chưa từng được tạo), nên một lần save() thất bại
        # ở đây chỉ thêm một recording_error nữa, không cần xử lý gì hơn
        # (đã return False ngay sau đây).
        self._persist_metadata()
        return False

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

        # Task 7: ghi metadata "finalize" NGAY sau khi đoạn cũ đã hoàn
        # tất — VLC của đoạn đó đã release ở bước trên, session.json giờ
        # phản ánh đúng đoạn vừa xong + total_bytes chính xác, bất kể
        # bước kế tiếp (storage check / tạo đoạn mới) có thành công hay
        # không.
        self._persist_metadata()

        # Task 5: kiểm tra chính sách lưu trữ TRƯỚC khi tạo đoạn kế tiếp.
        # Nếu bị từ chối, _enforce_storage_policy_or_abort() đã tự dừng
        # timer + chuyển session sang DISK_FULL/FAILED + emit
        # recording_error — không tạo VLC nào ở đây, không finalize thêm
        # lần nữa (đoạn cũ đã finalize ở trên), không xoá segment nào.
        if not self._enforce_storage_policy_or_abort():
            return

        try:
            self._start_segment()
        except Exception as exc:  # noqa: BLE001 - lỗi VLC có thể là nhiều loại
            self._watchdog.stop()
            self._segment_timer.stop()
            self._start_time = None
            self._transition_session_safely(RecordingStatus.FAILED, error=str(exc))
            # Task 7: ghi metadata "failure" — không VLC nào bị đụng ở
            # đây (đoạn cũ đã release ở trên, đoạn mới chưa từng được
            # gán vào self.instance/self.media_player vì _start_segment()
            # chỉ gán sau khi mọi bước thành công).
            self._persist_metadata()
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
            # Task 7: ghi metadata "failure" — VLC đã release ở trên,
            # đoạn hiện tại đã finalize (completed=True) trước lần ghi
            # này, khớp docstring _persist_metadata().
            self._persist_metadata()
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

        # Task 7: ghi metadata "final" — MỘT lần ghi duy nhất, sau khi cả
        # đoạn cuối đã finalize (ở trên) VÀ session đã STOPPED (ended_at
        # đã được set), nên bản ghi này chứa đầy đủ: đoạn cuối completed,
        # total_bytes chính xác, status STOPPED, ended_at khớp thời điểm
        # dừng thật.
        self._persist_metadata()

        self.recording_stopped.emit(path or "")
