"""
settings_dialog.py — Sprint 4: Cài đặt kết nối

Dialog nhập IP/port/user/pass RTSP + loại luồng (sub/main), có nút "Kiểm tra
kết nối" test thật bằng 1 phiên libVLC RIÊNG (không dùng chung instance với
StreamWidget đang chạy trong cửa sổ chính — tránh 2 phiên libVLC tranh chấp
nhau) trước khi lưu.

Dialog KHÔNG tự lưu config hay đụng vào StreamWidget đang chạy — chỉ trả về
dict rtsp mới qua get_rtsp_config() khi exec() == Accepted. Việc lưu config
+ reconnect StreamWidget do nơi gọi (tray.py) xử lý, giữ dialog này thuần UI.
"""

import vlc

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QSpinBox, QPushButton,
    QLabel, QFileDialog, QFrame, QStackedWidget, QProgressBar, QWidget,
)
from PySide6.QtCore import QDir, QTimer, Qt

from config_loader import build_rtsp_url
from motion import (
    POST_ROLL_MAX_S, POST_ROLL_MIN_S, get_motion_config,
)
from recorder import default_recording_dir
from recording import resolve_recording_base_dir
from recording.cleanup import (
    MAX_MAX_GB, MIN_MAX_GB, get_retention_config, summarize_usage,
)
from recording.summary import format_size
from ui_widgets import SegmentedControl, ToggleSwitch
import autostart

_TEST_TIMEOUT_MS = 6000
_TEST_POLL_MS = 300

# Giao diện tối kiểu Apple: nền #1c1c1e, thẻ #2c2c2e bo góc, đường kẻ #3a3a3c,
# xanh nhấn #0a84ff. Chỉ dùng stylesheet Qt — không thêm thư viện nào.
_STYLE = """
QDialog { background-color: #1c1c1e; }
QLabel { color: #f5f5f7; font-size: 13px; }
QLabel#rowHint, QLabel#note, QLabel#section { color: #8e8e93; font-size: 11px; }
QLabel#section { font-weight: 600; padding: 4px 4px 0 4px; }
QFrame#card { background-color: #2c2c2e; border-radius: 10px; }
QFrame#sep { background-color: #3a3a3c; border: none; min-height: 1px; max-height: 1px; }
QLineEdit, QSpinBox {
    background-color: #1c1c1e; color: #f5f5f7; border: 1px solid transparent;
    border-radius: 6px; padding: 5px 8px; selection-background-color: #0a84ff;
}
QLineEdit:focus, QSpinBox:focus { border: 1px solid #0a84ff; }
QLineEdit:read-only { color: #c7c7cc; }
QPushButton {
    background-color: #3a3a3c; color: #f5f5f7; border: none;
    border-radius: 6px; padding: 6px 14px;
}
QPushButton:hover { background-color: #48484a; }
QPushButton:pressed { background-color: #545458; }
QPushButton:disabled { color: #6c6c70; }
QPushButton:checked { background-color: #0a84ff; }
QPushButton#primary { background-color: #0a84ff; color: #ffffff; font-weight: 600; padding: 6px 22px; }
QPushButton#primary:hover { background-color: #3b9bff; }
QPushButton#primary:pressed { background-color: #0067d6; }
QProgressBar { background-color: #1c1c1e; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; }
QProgressBar::chunk { background-color: #0a84ff; border-radius: 3px; }
QProgressBar[level="warn"]::chunk { background-color: #ff9f0a; }
QProgressBar[level="full"]::chunk { background-color: #ff453a; }
"""

_CONTROL_W = 230   # bề rộng ô nhập bên phải mỗi hàng cài đặt


def _make_card(rows) -> QFrame:
    """Thẻ bo góc chứa nhiều hàng, ngăn cách bằng đường kẻ mảnh."""
    card = QFrame()
    card.setObjectName("card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for i, row in enumerate(rows):
        if i:
            sep = QFrame()
            sep.setObjectName("sep")
            sep.setFixedHeight(1)
            wrap = QHBoxLayout()
            wrap.setContentsMargins(14, 0, 0, 0)
            wrap.addWidget(sep)
            lay.addLayout(wrap)
        lay.addWidget(row)
    return card


def _make_row(title: str, hint: str, control: QWidget | None) -> QWidget:
    """Một hàng cài đặt: tiêu đề (+ chú thích nhỏ) bên trái, điều khiển bên phải."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(12)

    text = QVBoxLayout()
    text.setSpacing(2)
    title_label = QLabel(title)
    title_label.setWordWrap(True)
    text.addWidget(title_label)
    if hint:
        hint_label = QLabel(hint)
        hint_label.setObjectName("rowHint")
        hint_label.setWordWrap(True)
        text.addWidget(hint_label)
    lay.addLayout(text, 1)

    if control is not None:
        lay.addWidget(control, 0, Qt.AlignVCenter | Qt.AlignRight)
    return row


def _section(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("section")
    return label


class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cài đặt — EzvizFloatCam")
        self.setModal(True)
        self.setStyleSheet(_STYLE)
        self.setMinimumWidth(520)

        rtsp_cfg = config.get("rtsp", {})
        self._config = config

        # ---------- trang 1: Kết nối ----------
        self.ip_edit = QLineEdit(rtsp_cfg.get("ip", ""))
        self.ip_edit.setPlaceholderText("vd: 192.168.1.100")
        self.ip_edit.setAlignment(Qt.AlignRight)
        self.ip_edit.setFixedWidth(_CONTROL_W)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(rtsp_cfg.get("port", 554))
        self.port_spin.setAlignment(Qt.AlignRight)
        self.port_spin.setFixedWidth(110)

        self.user_edit = QLineEdit(rtsp_cfg.get("username", ""))
        self.user_edit.setPlaceholderText("vd: admin")
        self.user_edit.setAlignment(Qt.AlignRight)
        self.user_edit.setFixedWidth(_CONTROL_W)

        self.pass_edit = QLineEdit(rtsp_cfg.get("password", ""))
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setAlignment(Qt.AlignRight)

        # Nút "Hiện/Ẩn" nằm cạnh ô mật khẩu (giữ tên thuộc tính cũ, vẫn là
        # nút bấm có toggled/isChecked như QCheckBox).
        self.show_pass_check = QPushButton("Hiện")
        self.show_pass_check.setCheckable(True)
        self.show_pass_check.setCursor(Qt.PointingHandCursor)
        self.show_pass_check.setFixedWidth(52)
        self.show_pass_check.toggled.connect(self._toggle_password_visibility)

        pass_box = QWidget()
        pass_lay = QHBoxLayout(pass_box)
        pass_lay.setContentsMargins(0, 0, 0, 0)
        pass_lay.setSpacing(6)
        self.pass_edit.setFixedWidth(_CONTROL_W - 58)
        pass_lay.addWidget(self.pass_edit)
        pass_lay.addWidget(self.show_pass_check)

        self.stream_combo = SegmentedControl(
            [("Nhẹ · sub", "sub"), ("Nét · main", "main")], track="#1c1c1e",
        )
        self.stream_combo.setCurrentData(rtsp_cfg.get("stream_type", "sub"))

        self.channel_edit = QLineEdit(rtsp_cfg.get("channel", "ch1"))
        self.channel_edit.setPlaceholderText("vd: ch1")
        self.channel_edit.setAlignment(Qt.AlignRight)
        self.channel_edit.setFixedWidth(110)

        # Sprint 5: đọc trạng thái THẬT từ registry (không đọc từ
        # config.json) — tránh lệch nếu người dùng tự xoá key bằng tay
        # (vd qua Task Manager > Startup) ngoài ý muốn của app.
        self.autostart_check = ToggleSwitch()
        self.autostart_check.setChecked(autostart.is_autostart_enabled())

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(18)

        self.test_btn = QPushButton("Kiểm tra kết nối")
        self.test_btn.clicked.connect(self._start_test)

        test_row = QHBoxLayout()
        test_row.setContentsMargins(4, 0, 4, 0)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.status_label, 1)

        page_connection = QWidget()
        pc = QVBoxLayout(page_connection)
        pc.setContentsMargins(0, 0, 0, 0)
        pc.setSpacing(6)
        pc.addWidget(_section("Camera"))
        pc.addWidget(_make_card([
            _make_row("Địa chỉ IP", "", self.ip_edit),
            _make_row("Cổng (port)", "", self.port_spin),
            _make_row("Tên đăng nhập", "", self.user_edit),
            _make_row("Mật khẩu", "", pass_box),
        ]))
        pc.addLayout(test_row)
        pc.addWidget(_section("Xem trực tiếp"))
        pc.addWidget(_make_card([
            _make_row("Chất lượng luồng xem", "Nhẹ (sub) được khuyến nghị — ít tốn CPU",
                      self.stream_combo),
            _make_row("Kênh (nâng cao)", "Thường không cần đổi", self.channel_edit),
            _make_row("Khởi động cùng Windows", "", self.autostart_check),
        ]))
        pc.addStretch(1)

        # ---------- trang 2: Ghi hình ----------
        # Sprint 5.5: thư mục lưu video. Để trống = lúc bấm ghi sẽ tự dùng thư
        # mục gợi ý mặc định (%USERPROFILE%\Videos\EzvizFloatCam) — ô này chỉ
        # HIỂN THỊ gợi ý qua placeholder, KHÔNG tự ghi giá trị đó vào config
        # nếu người dùng chưa bấm "Mặc định" hoặc tự chọn qua "Chọn...".
        recording_cfg = config.get("recording", {})
        self.record_dir_edit = QLineEdit()
        self.record_dir_edit.setReadOnly(True)
        self.record_dir_edit.setPlaceholderText(
            QDir.toNativeSeparators(str(default_recording_dir()))
        )
        self.record_dir_edit.textChanged.connect(self._on_record_dir_changed)
        self._set_record_dir(recording_cfg.get("save_dir", ""))

        self.record_browse_btn = QPushButton("Chọn...")
        self.record_browse_btn.clicked.connect(self._browse_record_dir)
        self.record_default_btn = QPushButton("Mặc định")
        self.record_default_btn.clicked.connect(self._use_default_record_dir)

        dir_row = QWidget()
        dr = QVBoxLayout(dir_row)
        dr.setContentsMargins(14, 10, 14, 12)
        dr.setSpacing(8)
        dr.addWidget(QLabel("Thư mục lưu ghi hình"))
        dr.addWidget(self.record_dir_edit)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addWidget(self.record_browse_btn)
        btns.addWidget(self.record_default_btn)
        btns.addStretch(1)
        dr.addLayout(btns)

        # Giới hạn dung lượng thư mục ghi hình + tự xoá bản ghi TỰ ĐỘNG cũ.
        retention_cfg = get_retention_config(config)
        self.retention_check = ToggleSwitch()
        self.retention_check.setChecked(retention_cfg["enabled"])

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(MIN_MAX_GB, MAX_MAX_GB)
        self.retention_spin.setSuffix(" GB")
        self.retention_spin.setValue(retention_cfg["max_gb"])
        self.retention_spin.setAlignment(Qt.AlignRight)
        self.retention_spin.setFixedWidth(110)
        self.retention_spin.valueChanged.connect(self._refresh_usage)

        self.usage_bar = QProgressBar()
        self.usage_bar.setTextVisible(False)
        self.usage_bar.setRange(0, 1000)

        self.retention_usage_label = QLabel("")
        self.retention_usage_label.setObjectName("rowHint")
        self.retention_usage_label.setWordWrap(True)

        usage_row = QWidget()
        ur = QVBoxLayout(usage_row)
        ur.setContentsMargins(14, 10, 14, 12)
        ur.setSpacing(8)
        ur.addWidget(self.usage_bar)
        ur.addWidget(self.retention_usage_label)

        self._usage = self._compute_usage(config)
        self._refresh_usage()

        page_recording = QWidget()
        pr = QVBoxLayout(page_recording)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(6)
        pr.addWidget(_section("Nơi lưu"))
        pr.addWidget(_make_card([dir_row]))
        pr.addWidget(_section("Dung lượng"))
        pr.addWidget(_make_card([
            _make_row("Tự xoá bản ghi tự động cũ",
                      "Khi đầy, xoá dần từ bản cũ nhất. Ghi thủ công (nút REC) "
                      "không bao giờ bị tự xoá.", self.retention_check),
            _make_row("Dung lượng tối đa", "Tính trên toàn bộ thư mục ghi hình",
                      self.retention_spin),
            usage_row,
        ]))
        pr.addStretch(1)

        # ---------- trang 3: Chuyển động ----------
        motion_cfg = get_motion_config(config)
        self.motion_check = ToggleSwitch()
        self.motion_check.setChecked(motion_cfg["enabled"])

        self.motion_sens_combo = SegmentedControl(
            [("Thấp", "low"), ("Vừa", "medium"), ("Cao", "high")],
        )
        self.motion_sens_combo.setCurrentData(motion_cfg["sensitivity"])

        self.motion_post_roll_spin = QSpinBox()
        self.motion_post_roll_spin.setRange(POST_ROLL_MIN_S, POST_ROLL_MAX_S)
        self.motion_post_roll_spin.setSuffix(" giây")
        self.motion_post_roll_spin.setValue(motion_cfg["post_roll_s"])
        self.motion_post_roll_spin.setAlignment(Qt.AlignRight)
        self.motion_post_roll_spin.setFixedWidth(110)

        motion_note = QLabel(
            "Độ nhạy Thấp ít báo nhầm, Cao dễ bắt chuyển động nhỏ. Muốn chỉ theo dõi "
            "một vùng (vd quanh cửa), đặt khoá \"roi\" trong config.json — xem README."
        )
        motion_note.setObjectName("note")
        motion_note.setWordWrap(True)
        motion_note.setContentsMargins(4, 0, 4, 0)

        page_motion = QWidget()
        pm = QVBoxLayout(page_motion)
        pm.setContentsMargins(0, 0, 0, 0)
        pm.setSpacing(6)
        pm.addWidget(_section("Ghi tự động"))
        pm.addWidget(_make_card([
            _make_row("Tự động ghi khi có chuyển động",
                      "Độc lập với nút REC thủ công", self.motion_check),
            _make_row("Độ nhạy", "", self.motion_sens_combo),
            _make_row("Ghi thêm sau chuyển động cuối",
                      "Ghi tiếp bao lâu sau lần chuyển động cuối cùng",
                      self.motion_post_roll_spin),
        ]))
        pm.addWidget(motion_note)
        pm.addStretch(1)

        # ---------- khung chính: thanh tab + trang + nút Huỷ/Lưu ----------
        self._stack = QStackedWidget()
        for page in (page_connection, page_recording, page_motion):
            self._stack.addWidget(page)

        self._tabs = SegmentedControl(
            [("Kết nối", 0), ("Ghi hình", 1), ("Chuyển động", 2)],
            stretch=True, track="#2c2c2e",
        )
        self._tabs.currentChanged.connect(self._stack.setCurrentIndex)

        self.cancel_btn = QPushButton("Huỷ")
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton("Lưu")
        self.save_btn.setObjectName("primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_save)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.save_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(self._tabs)
        layout.addWidget(self._stack, 1)
        layout.addLayout(bottom)

        self._test_instance = None
        self._test_player = None
        self._test_timer = None
        self._test_elapsed = 0

        # Mở hộp thoại là có thể gõ IP luôn (và không để thanh tab giữ focus,
        # tránh hiện viền focus xanh quanh thanh tab ngay khi mở).
        self.ip_edit.setFocus()

    # ---------- helpers ----------

    def _toggle_password_visibility(self, checked: bool):
        self.pass_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self.show_pass_check.setText("Ẩn" if checked else "Hiện")

    def _current_rtsp_dict(self) -> dict:
        return {
            "ip": self.ip_edit.text().strip(),
            "port": self.port_spin.value(),
            "username": self.user_edit.text().strip(),
            "password": self.pass_edit.text(),
            "stream_type": self.stream_combo.currentData(),
            "channel": self.channel_edit.text().strip() or "ch1",
        }

    def get_rtsp_config(self) -> dict:
        """Gọi sau khi exec() trả về Accepted để lấy config rtsp mới."""
        return self._current_rtsp_dict()

    def is_autostart_checked(self) -> bool:
        """Gọi sau khi exec() trả về Accepted để biết checkbox 'Khởi động
        cùng Windows' có đang được tick hay không."""
        return self.autostart_check.isChecked()

    def get_recording_config(self) -> dict:
        """Gọi sau khi exec() trả về Accepted để lấy thư mục lưu ghi hình
        khẩn cấp mới (Sprint 5.5)."""
        return {"save_dir": self.record_dir_edit.text().strip()}

    @staticmethod
    def _compute_usage(config: dict):
        """Mức dùng hiện tại của thư mục ghi hình (theo thư mục ĐÃ LƯU);
        None nếu không đọc được (chỉ là thông tin phụ)."""
        try:
            base = resolve_recording_base_dir(config.get("recording", {}).get("save_dir", ""))
            return summarize_usage(base)
        except Exception:  # noqa: BLE001
            return None

    def _refresh_usage(self, *_):
        """Vẽ lại thanh + dòng chữ mức dùng theo ngưỡng đang chọn (kể cả khi
        người dùng vừa kéo ô "Dung lượng tối đa", chưa bấm Lưu)."""
        u = self._usage
        cap_gb = self.retention_spin.value()
        if u is None:
            self.usage_bar.setValue(0)
            self.retention_usage_label.setText("")
            return
        ratio = u["total"] / (cap_gb * 1024 ** 3)
        self.usage_bar.setValue(min(1000, int(ratio * 1000)))
        level = "full" if ratio >= 1.0 else "warn" if ratio >= 0.9 else "ok"
        if self.usage_bar.property("level") != level:
            self.usage_bar.setProperty("level", level)
            self.usage_bar.style().unpolish(self.usage_bar)
            self.usage_bar.style().polish(self.usage_bar)
        self.retention_usage_label.setText(
            f"Đang dùng {format_size(u['total'])} / {cap_gb} GB  ·  "
            f"{format_size(u['auto'])} tự động (có thể xoá)  ·  "
            f"{format_size(u['protected'])} được giữ (thủ công/đang ghi)"
        )

    def get_retention_settings(self) -> dict:
        """Gọi sau khi exec() trả về Accepted để lấy cấu hình tự xoá."""
        return {
            "enabled": self.retention_check.isChecked(),
            "max_gb": self.retention_spin.value(),
        }

    def get_motion_config(self) -> dict:
        """Gọi sau khi exec() trả về Accepted để lấy cấu hình ghi tự động theo
        chuyển động (chỉ các khoá mà dialog này quản lý)."""
        return {
            "enabled": self.motion_check.isChecked(),
            "sensitivity": self.motion_sens_combo.currentData(),
            "post_roll_s": self.motion_post_roll_spin.value(),
        }

    # ---------- thư mục lưu ghi hình (Sprint 5.5) ----------

    def _set_record_dir(self, path: str):
        """Hiển thị đường dẫn kiểu Windows (dấu \\), luôn cuộn về ĐẦU chuỗi để
        thấy ổ đĩa/thư mục gốc thay vì bị cắt mất phần đầu."""
        self.record_dir_edit.setText(QDir.toNativeSeparators(path) if path else "")

    def _on_record_dir_changed(self, text: str):
        self.record_dir_edit.setCursorPosition(0)
        self.record_dir_edit.setToolTip(text)

    def _browse_record_dir(self):
        start_dir = self.record_dir_edit.text().strip() or str(default_recording_dir())
        chosen = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu ghi hình", start_dir,
        )
        if chosen:
            self._set_record_dir(chosen)

    def _use_default_record_dir(self):
        self._set_record_dir(str(default_recording_dir()))

    # ---------- kiểm tra kết nối ----------

    def _start_test(self):
        rtsp_cfg = self._current_rtsp_dict()
        if not rtsp_cfg["ip"]:
            self._set_status("Vui lòng nhập địa chỉ IP camera trước.", ok=False)
            return

        self._stop_test()  # phòng trường hợp bấm "Kiểm tra" 2 lần liên tiếp

        url = build_rtsp_url(rtsp_cfg)
        self._set_status("Đang kết nối thử...", ok=None)
        self.test_btn.setEnabled(False)

        # Dùng 1 instance libVLC RIÊNG cho việc test, không đụng tới
        # StreamWidget/instance đang chạy trong cửa sổ chính — 2 phiên libVLC
        # độc lập chạy song song không xung đột nhau (mỗi cái tự quản lý
        # decoder/buffer riêng).
        self._test_instance = vlc.Instance(["--no-xlib", "--rtsp-tcp", "--avcodec-hw=none"])
        self._test_player = self._test_instance.media_player_new()
        media = self._test_instance.media_new(url)
        media.add_option(":avcodec-hw=none")
        self._test_player.set_media(media)
        self._test_player.play()

        self._test_elapsed = 0
        self._test_timer = QTimer(self)
        self._test_timer.timeout.connect(self._poll_test)
        self._test_timer.start(_TEST_POLL_MS)

    def _poll_test(self):
        self._test_elapsed += _TEST_POLL_MS
        state = self._test_player.get_state()
        if state == vlc.State.Playing:
            self._stop_test()
            self._set_status("✓ Kết nối thành công! Camera phản hồi bình thường.", ok=True)
        elif state == vlc.State.Error:
            self._stop_test()
            self._set_status("✗ Kết nối thất bại — kiểm tra lại IP/port/user/mật khẩu.", ok=False)
        elif self._test_elapsed >= _TEST_TIMEOUT_MS:
            self._stop_test()
            self._set_status(
                "✗ Hết thời gian chờ — kiểm tra lại IP/mạng, hoặc camera đã bật RTSP chưa.",
                ok=False,
            )

    def _stop_test(self):
        if self._test_timer is not None:
            self._test_timer.stop()
            self._test_timer = None
        if self._test_player is not None:
            self._test_player.stop()
            self._test_player = None
        self._test_instance = None
        self.test_btn.setEnabled(True)

    def _set_status(self, message: str, ok):
        self.status_label.setText(message)
        if ok is True:
            color = "#40c86e"
        elif ok is False:
            color = "#dc4646"
        else:
            color = "#c8c832"
        self.status_label.setStyleSheet(f"color: {color};")

    # ---------- lưu / huỷ ----------

    def _on_save(self):
        rtsp_cfg = self._current_rtsp_dict()
        if not rtsp_cfg["ip"]:
            self._tabs.setCurrentIndex(0)  # quay về tab có ô IP để người dùng thấy lỗi
            self._set_status("Vui lòng nhập địa chỉ IP camera trước khi lưu.", ok=False)
            return
        self._stop_test()
        self.accept()

    def reject(self):
        self._stop_test()
        super().reject()

    def closeEvent(self, event):
        self._stop_test()
        super().closeEvent(event)
