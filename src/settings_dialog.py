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
    QDialog, QFormLayout, QVBoxLayout, QHBoxLayout, QLineEdit, QSpinBox,
    QComboBox, QCheckBox, QPushButton, QLabel, QDialogButtonBox,
)
from PySide6.QtCore import QTimer

from config_loader import build_rtsp_url
import autostart

_TEST_TIMEOUT_MS = 6000
_TEST_POLL_MS = 300

_STYLE = """
QDialog { background-color: #18181c; color: #eaeaea; }
QLabel { color: #eaeaea; }
QLineEdit, QSpinBox, QComboBox {
    background-color: #232328; color: #eaeaea; border: 1px solid #3a3a40;
    border-radius: 6px; padding: 4px 6px;
}
QPushButton {
    background-color: #2c2c33; color: #eaeaea; border: 1px solid #3a3a40;
    border-radius: 6px; padding: 5px 14px;
}
QPushButton:hover { background-color: #35353d; }
QPushButton:disabled { color: #777; }
QCheckBox { color: #eaeaea; }
"""


class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cài đặt kết nối — EzvizFloatCam")
        self.setModal(True)
        self.setStyleSheet(_STYLE)
        self.setMinimumWidth(380)

        rtsp_cfg = config.get("rtsp", {})

        self.ip_edit = QLineEdit(rtsp_cfg.get("ip", ""))
        self.ip_edit.setPlaceholderText("vd: 192.168.1.100")

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(rtsp_cfg.get("port", 554))

        self.user_edit = QLineEdit(rtsp_cfg.get("username", ""))
        self.user_edit.setPlaceholderText("vd: admin")

        self.pass_edit = QLineEdit(rtsp_cfg.get("password", ""))
        self.pass_edit.setEchoMode(QLineEdit.Password)

        self.show_pass_check = QCheckBox("Hiện mật khẩu")
        self.show_pass_check.toggled.connect(self._toggle_password_visibility)

        self.stream_combo = QComboBox()
        self.stream_combo.addItem("Nhẹ — sub stream (khuyến nghị)", "sub")
        self.stream_combo.addItem("Nét cao — main stream (nặng hơn)", "main")
        current_stream = rtsp_cfg.get("stream_type", "sub")
        idx = self.stream_combo.findData(current_stream)
        self.stream_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.channel_edit = QLineEdit(rtsp_cfg.get("channel", "ch1"))
        self.channel_edit.setPlaceholderText("vd: ch1 (thường không cần đổi)")

        # Sprint 5: đọc trạng thái THẬT từ registry (không đọc từ
        # config.json) — tránh lệch nếu người dùng tự xoá key bằng tay
        # (vd qua Task Manager > Startup) ngoài ý muốn của app.
        self.autostart_check = QCheckBox("Khởi động cùng Windows")
        self.autostart_check.setChecked(autostart.is_autostart_enabled())

        form = QFormLayout()
        form.addRow("Địa chỉ IP camera:", self.ip_edit)
        form.addRow("Port:", self.port_spin)
        form.addRow("Tên đăng nhập:", self.user_edit)
        form.addRow("Mật khẩu:", self.pass_edit)
        form.addRow("", self.show_pass_check)
        form.addRow("Loại luồng:", self.stream_combo)
        form.addRow("Channel (nâng cao):", self.channel_edit)
        form.addRow("", self.autostart_check)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        self.test_btn = QPushButton("Kiểm tra kết nối")
        self.test_btn.clicked.connect(self._start_test)

        test_row = QHBoxLayout()
        test_row.addWidget(self.test_btn)
        test_row.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Lưu")
        buttons.button(QDialogButtonBox.Cancel).setText("Huỷ")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(test_row)
        layout.addWidget(self.status_label)
        layout.addWidget(buttons)

        self._test_instance = None
        self._test_player = None
        self._test_timer = None
        self._test_elapsed = 0

    # ---------- helpers ----------

    def _toggle_password_visibility(self, checked: bool):
        self.pass_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

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
