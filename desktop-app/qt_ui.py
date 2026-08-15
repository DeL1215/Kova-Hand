"""Qt presentation layer for Kova Hand.

The BLE, MediaPipe, and AI workers are injected from main.py.  This module owns
only the high-DPI desktop interface and UI event wiring.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path

import config
from ai_chat import AiChatClient
from motion_plan import MotionPlanError, MotionStep, PoseStep, WaitStep, parse_motion_plan
from PySide6.QtCore import QByteArray, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QStackedLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


BG = "#F5F5F7"
SURFACE = "#FFFFFF"
TEXT = "#17181C"
MUTED = "#6E7179"
BORDER = "#D7D9DF"
FIELD_BORDER = "#C8CBD3"
ACCENT = "#0071E3"
GREEN = "#22A06B"
WARNING = "#F5B700"
RED = "#D92D20"
ASSET_DIR = Path(__file__).resolve().parent / "assets"
ICON_DIR = ASSET_DIR / "icons"
CHEVRON_ICON = (ICON_DIR / "chevron-down.svg").as_posix()


STYLE = f"""
QWidget {{
    color: {TEXT};
    font-family: "Noto Sans TC";
}}
QMainWindow, QWidget#Root {{ background: {BG}; }}
QWidget#CardShell {{ background: transparent; }}
QFrame#CardSurface {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
QFrame#Hairline {{ background: #D5D7DC; border: 0; }}
QFrame#Preview, QTextEdit {{
    background: #F6F7F9;
    border: 1px solid {FIELD_BORDER};
    border-radius: 12px;
}}
QTextEdit {{ padding: 10px; selection-background-color: #CFE5FF; }}
QComboBox {{
    background: #FBFBFC;
    border: 1px solid #BFC3CC;
    border-radius: 10px;
    padding: 0 40px 0 12px;
}}
QComboBox:hover, QComboBox:focus {{ border-color: #8E939D; }}
QComboBox::drop-down {{ border: 0; width: 38px; }}
QComboBox::down-arrow {{
    image: url("{CHEVRON_ICON}");
    width: 16px;
    height: 16px;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    selection-background-color: #E9F2FF;
    selection-color: {TEXT};
    padding: 5px;
}}
QPushButton {{
    min-height: 36px;
    padding: 0 15px;
    border: 0;
    border-radius: 10px;
    font-weight: 600;
}}
QPushButton[variant="secondary"] {{ background: #F0F1F3; color: {TEXT}; }}
QPushButton[variant="secondary"]:hover {{ background: #E5E6E9; }}
QPushButton[variant="dark"] {{ background: #202124; color: white; }}
QPushButton[variant="dark"]:hover {{ background: #343538; }}
QPushButton[variant="blue"] {{ background: {ACCENT}; color: white; }}
QPushButton[variant="blue"]:hover {{ background: #0064C8; }}
QPushButton[variant="danger"] {{ background: {RED}; color: white; }}
QPushButton[variant="danger"]:hover {{ background: #B42318; }}
QPushButton:disabled {{ background: #E7E8EB; color: #9A9DA5; }}
QSlider {{ min-height: 24px; }}
QSlider::groove:horizontal {{ height: 4px; background: #CFD2D8; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 12px;
    margin: -6px 0;
    background: white;
    border: 2px solid #AEB3BD;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ border-color: {ACCENT}; }}
QSplitter::handle {{ background: transparent; width: 14px; }}
"""


def _font(size: int, weight=QFont.Weight.Normal, mono: bool = False) -> QFont:
    font = QFont("Cascadia Mono" if mono else "Noto Sans TC", size)
    font.setWeight(weight)
    return font


def _svg_icon(name: str, color: str, size: int = 18) -> QIcon:
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        return QIcon()
    data = path.read_text(encoding="utf-8").replace("#000", color).encode("utf-8")
    renderer = QSvgRenderer(QByteArray(data))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def _logo_pixmap(size: int = 42) -> QPixmap:
    from PIL import Image, ImageColor

    logo = Image.open(ASSET_DIR / "kova-logo.png").convert("RGBA")
    bounds = logo.getchannel("A").getbbox()
    if bounds:
        logo = logo.crop(bounds)
    ink = Image.new("RGBA", logo.size, (*ImageColor.getrgb(TEXT), 255))
    ink.putalpha(logo.getchannel("A"))
    logo = ink
    logo.thumbnail((size * 2, size * 2), Image.Resampling.LANCZOS)
    raw = logo.tobytes("raw", "RGBA")
    image = QImage(raw, logo.width, logo.height, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(image).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


def _set_variant(button: QPushButton, variant: str) -> None:
    button.setProperty("variant", variant)
    button.style().unpolish(button)
    button.style().polish(button)


class Bridge(QObject):
    ble = Signal(str, object)
    ai = Signal(str, str)


class StatusDot(QLabel):
    def __init__(self, color: str = "#A6ABB4"):
        super().__init__()
        self.setFixedSize(8, 8)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.setStyleSheet(f"background:{color}; border-radius:4px;")


class Card(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CardShell")
        shell = QVBoxLayout(self)
        shell.setContentsMargins(8, 6, 8, 12)
        shell.setSpacing(0)

        self.body = QFrame()
        self.body.setObjectName("CardSurface")
        shell.addWidget(self.body)

        shadow = QGraphicsDropShadowEffect(self.body)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(20, 24, 32, 30))
        self.body.setGraphicsEffect(shadow)


class MotorRow(QWidget):
    def __init__(self, motor: dict, changed):
        super().__init__()
        self.motor = motor
        self.changed = changed
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        name = QLabel(motor["title"])
        name.setFont(_font(11, QFont.Weight.DemiBold))
        name.setFixedWidth(140)
        self.value_label = QLabel(f'{motor["initial"]}°')
        self.value_label.setFont(_font(17, QFont.Weight.Bold, mono=True))
        self.value_label.setFixedWidth(62)

        control = QWidget()
        control_layout = QVBoxLayout(control)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(3)
        labels = QHBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        minimum = QLabel(f'{motor["min"]}°')
        middle = QLabel(f'{round((motor["min"] + motor["max"]) / 2)}°')
        maximum = QLabel(f'{motor["max"]}°')
        for label in (minimum, middle, maximum):
            label.setFont(_font(9, mono=True))
            label.setStyleSheet(f"color:{MUTED};")
        labels.addWidget(minimum)
        labels.addStretch()
        labels.addWidget(middle)
        labels.addStretch()
        labels.addWidget(maximum)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(motor["min"], motor["max"])
        self.slider.setValue(motor["initial"])
        self.slider.setSingleStep(1)
        self.slider.setFixedHeight(24)
        self.slider.valueChanged.connect(self._value_changed)
        control_layout.addLayout(labels)
        control_layout.addWidget(self.slider)

        layout.addWidget(name)
        layout.addWidget(self.value_label)
        layout.addWidget(control, 1)

    def _value_changed(self, angle: int) -> None:
        self.value_label.setText(f"{angle}°")
        self.changed(self.motor["channel"], angle)

    def center(self) -> None:
        self.slider.setValue(round((self.motor["min"] + self.motor["max"]) / 2))

    def set_external_value(self, angle: float) -> int:
        value = min(self.motor["max"], max(self.motor["min"], round(angle)))
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self.value_label.setText(f"{value}°")
        return value


class KovaQtWindow(QMainWindow):
    def __init__(self, controller_type, tracker_type):
        super().__init__()
        self.setFont(_font(11))
        self.setWindowTitle(config.APP_TITLE)
        self.resize(1280, 1020)
        self.setMinimumSize(1100, 840)
        self.bridge = Bridge()
        self.bridge.ble.connect(self._handle_ble_event)
        self.bridge.ai.connect(self._handle_ai_event)
        self.controller = controller_type(lambda event, payload: self.bridge.ble.emit(event, payload))
        self.hand_tracker = tracker_type()
        self.ai_chat = AiChatClient()
        self.connected = False
        self.hand_enabled = False
        self.ai_plan: list[MotionStep] = []
        self.ai_step_index = 0
        self.motor_rows_by_channel = {}
        self._build_ui()

        self.hand_timer = QTimer(self)
        self.hand_timer.timeout.connect(self._poll_hand_tracker)
        self.hand_timer.start(33)

        self.ai_motion_timer = QTimer(self)
        self.ai_motion_timer.setSingleShot(True)
        self.ai_motion_timer.timeout.connect(self._run_ai_step)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(30, 14, 30, 30)
        page.setSpacing(14)

        page.addWidget(self._build_header())
        page.addWidget(self._build_connection())
        workspace = QSplitter(Qt.Orientation.Horizontal)
        workspace.setChildrenCollapsible(False)
        workspace.setHandleWidth(4)
        workspace.addWidget(self._build_motors())
        workspace.addWidget(self._build_hand_panel())
        workspace.setStretchFactor(0, 46)
        workspace.setStretchFactor(1, 54)
        workspace.setSizes([540, 640])
        page.addWidget(workspace, 1)
        page.addWidget(self._build_ai_panel())

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(60)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(_logo_pixmap())
        logo.setFixedSize(48, 48)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        separator = QFrame()
        separator.setObjectName("Hairline")
        separator.setFixedSize(1, 34)
        text = QVBoxLayout()
        text.setSpacing(0)
        title = QLabel("Kova Hand")
        title.setFont(_font(20, QFont.Weight.Bold))
        subtitle = QLabel("機器手控制台")
        subtitle.setFont(_font(10))
        subtitle.setStyleSheet(f"color:{MUTED};")
        text.addWidget(title)
        text.addWidget(subtitle)
        layout.addWidget(logo)
        layout.addWidget(separator)
        layout.addLayout(text)
        layout.addStretch()
        return header

    def _button(self, text: str, icon: str, variant: str, slot, width: int) -> QPushButton:
        color = "#FFFFFF" if variant in ("dark", "blue", "danger") else TEXT
        button = QPushButton(text)
        button.setIcon(_svg_icon(icon, color))
        button.setIconSize(QSize(17, 17))
        button.setFixedWidth(width)
        _set_variant(button, variant)
        button.clicked.connect(slot)
        return button

    def _build_connection(self) -> Card:
        card = Card()
        card.setFixedHeight(84)
        layout = QHBoxLayout(card.body)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(10)
        self.bluetooth_label = QLabel()
        self.bluetooth_label.setPixmap(_svg_icon("bluetooth", TEXT).pixmap(18, 18))
        label = QLabel("藍牙裝置")
        label.setFont(_font(12, QFont.Weight.DemiBold))
        self.device_box = QComboBox()
        self.device_box.setFixedHeight(38)
        self.device_box.addItem("尚未掃描裝置")
        self.scan_button = self._button("掃描", "refresh", "secondary", self._scan, 88)
        self.connect_button = self._button("連線", "link", "dark", self._connect, 112)
        self.status_dot = StatusDot()
        self.status_label = QLabel("尚未連線")
        self.status_label.setStyleSheet(f"color:{MUTED};")
        self.status_label.setMinimumWidth(96)
        layout.addWidget(self.bluetooth_label)
        layout.addWidget(label)
        layout.addWidget(self.device_box, 1)
        layout.addWidget(self.scan_button)
        layout.addWidget(self.connect_button)
        layout.addSpacing(4)
        layout.addWidget(self.status_dot)
        layout.addWidget(self.status_label)
        return card

    def _build_motors(self) -> Card:
        card = Card()
        layout = QVBoxLayout(card.body)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)
        header = QHBoxLayout()
        title = QLabel("馬達控制")
        title.setFont(_font(15, QFont.Weight.Bold))
        center = self._button("全部置中", "layout-align-center", "secondary", self._center_all, 104)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(center)
        layout.addLayout(header)
        self.motor_rows = []
        for motor in config.MOTORS:
            row = MotorRow(motor, self._send_angle)
            layout.addWidget(row, 1)
            self.motor_rows.append(row)
            self.motor_rows_by_channel[motor["channel"]] = row
        return card

    def _build_hand_panel(self) -> Card:
        card = Card()
        layout = QVBoxLayout(card.body)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)
        title = QLabel("手部辨識操控")
        title.setFont(_font(15, QFont.Weight.Bold))
        layout.addWidget(title)

        self.preview = QFrame()
        self.preview.setObjectName("Preview")
        self.preview_stack = QStackedLayout(self.preview)
        self.preview_stack.setContentsMargins(1, 1, 1, 1)
        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.addStretch()
        camera_icon = QLabel()
        camera_icon.setPixmap(_svg_icon("camera", "#8B8E95", 36).pixmap(36, 36))
        camera_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        camera_text = QLabel("攝影機預覽\n開啟後顯示手部辨識畫面")
        camera_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        camera_text.setStyleSheet(f"color:{MUTED};")
        placeholder_layout.addWidget(camera_icon)
        placeholder_layout.addWidget(camera_text)
        placeholder_layout.addStretch()
        self.camera_label = QLabel()
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_stack.addWidget(placeholder)
        self.preview_stack.addWidget(self.camera_label)
        layout.addWidget(self.preview, 1)

        actions = QHBoxLayout()
        self.hand_status_dot = StatusDot()
        self.hand_status_label = QLabel("手部辨識尚未啟動")
        self.hand_status_label.setStyleSheet(f"color:{MUTED};")
        self.hand_button = self._button(
            "開啟手部辨識", "player-play", "dark", self._toggle_hand_tracking, 154
        )
        actions.addWidget(self.hand_status_dot)
        actions.addWidget(self.hand_status_label)
        actions.addStretch()
        actions.addWidget(self.hand_button)
        layout.addLayout(actions)
        note = QLabel("只追蹤左手 · 四指與拇指雙關節控制馬達 0～5")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet(f"color:{MUTED};")
        layout.addWidget(note)
        return card

    def _build_ai_panel(self) -> Card:
        card = Card()
        card.setFixedHeight(284)
        outer = QVBoxLayout(card.body)
        outer.setContentsMargins(18, 12, 18, 16)
        outer.setSpacing(8)
        meta = QHBoxLayout()
        title = QLabel("AI 控制")
        title.setFont(_font(15, QFont.Weight.Bold))
        model_label = QLabel("模型")
        model_label.setFont(_font(10))
        model_label.setStyleSheet(f"color:{MUTED};")
        model = QLabel(self.ai_chat.model)
        model.setFont(_font(10))
        self.ai_status_label = QLabel("待命")
        self.ai_status_label.setFont(_font(10))
        self.ai_status_label.setStyleSheet(f"color:{MUTED};")
        meta.addWidget(title)
        meta.addSpacing(18)
        meta.addWidget(model_label)
        meta.addWidget(model)
        meta.addSpacing(16)
        status_label = QLabel("狀態")
        status_label.setFont(_font(10))
        status_label.setStyleSheet(f"color:{MUTED};")
        meta.addWidget(status_label)
        meta.addWidget(self.ai_status_label)
        meta.addStretch()
        outer.addLayout(meta)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_header = QHBoxLayout()
        input_title = QLabel("輸入訊息")
        input_title.setFont(_font(11, QFont.Weight.DemiBold))
        input_title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.ai_send_button = self._button("送出", "send-2", "blue", self._send_ai_message, 94)
        left_header.addWidget(input_title)
        left_header.addStretch()
        left_header.addWidget(self.ai_send_button)
        self.ai_input = QTextEdit()
        self.ai_input.setFont(_font(11))
        left_layout.addLayout(left_header)
        left_layout.addWidget(self.ai_input)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        response_title = QLabel("對話紀錄")
        response_title.setFont(_font(11, QFont.Weight.DemiBold))
        response_title.setFixedHeight(36)
        response_title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.ai_output = QTextEdit()
        self.ai_output.setFont(_font(11))
        self.ai_output.setPlainText("後台\n模型設定已載入，等待你的訊息。")
        self.ai_output.setReadOnly(True)
        right_layout.addWidget(response_title)
        right_layout.addWidget(self.ai_output)
        body.addWidget(left)
        body.addWidget(right)
        body.setHandleWidth(24)
        body.setStretchFactor(0, 43)
        body.setStretchFactor(1, 57)
        body.setSizes([480, 650])
        outer.addWidget(body, 1)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._send_ai_message)
        return card

    def _scan(self) -> None:
        self.scan_button.setEnabled(False)
        self.status_dot.set_color(WARNING)
        self.status_label.setText("正在掃描…")
        self.controller.scan()

    def _connect(self) -> None:
        if self.connected:
            self.controller.disconnect()
        else:
            self.controller.connect(self.device_box.currentText())

    def _handle_ble_event(self, event: str, payload) -> None:
        if event == "devices":
            self.device_box.clear()
            self.device_box.addItems(payload or ["尚未找到裝置"])
            preferred = next(
                (name for name in payload if config.BLE_DEVICE_NAME.lower() in name.lower()), None
            )
            if preferred:
                self.device_box.setCurrentText(preferred)
            self.scan_button.setEnabled(True)
            if not self.connected:
                self.status_dot.set_color("#A6ABB4")
        elif event == "status":
            self.status_label.setText(str(payload))
            if payload in ("正在掃描…", "正在連線…"):
                self.status_dot.set_color(WARNING)
        elif event == "connected":
            self.connected = bool(payload)
            self.status_dot.set_color(GREEN if self.connected else "#A6ABB4")
            self.status_label.setText("已連線" if self.connected else "連線已中斷")
            self.bluetooth_label.setPixmap(
                _svg_icon("bluetooth", ACCENT if self.connected else TEXT).pixmap(18, 18)
            )
            self.connect_button.setText("中斷連線" if self.connected else "連線")
            self.connect_button.setIcon(
                _svg_icon("unlink" if self.connected else "link", "#FFFFFF")
            )
            _set_variant(self.connect_button, "danger" if self.connected else "dark")
        elif event == "error":
            self.scan_button.setEnabled(True)
            self.status_dot.set_color(RED)
            self.status_label.setText("發生錯誤")
            QMessageBox.critical(self, "Kova Hand", str(payload))

    def _send_angle(self, channel: int, angle: int) -> None:
        if self.connected:
            self.controller.send_angle(channel, angle)

    def _center_all(self) -> None:
        for row in self.motor_rows:
            row.center()

    def _apply_controls(
        self, values: dict[int, float], preserve_unspecified: bool = False
    ) -> None:
        angles = {}
        for control in config.HAND_CONTROLS:
            channel = control["channel"]
            row = self.motor_rows_by_channel.get(channel)
            if row is None:
                continue
            if channel not in values:
                if preserve_unspecified:
                    angles[channel] = row.slider.value()
                continue
            amount = 1.0 - values[channel] if control.get("invert") else values[channel]
            target = row.motor["min"] + amount * (row.motor["max"] - row.motor["min"])
            angles[channel] = row.set_external_value(target)
        if self.connected and len(angles) == 6:
            self.controller.send_hand_angles(angles)

    def _apply_hand_controls(self, values: dict[int, float]) -> None:
        self._apply_controls(values)

    def _apply_ai_pose(self, step: PoseStep) -> None:
        values = {
            channel: value / 100
            for channel, value in enumerate(step.values)
            if value is not None
        }
        self._apply_controls(values, preserve_unspecified=True)

    def _send_ai_message(self) -> None:
        message = self.ai_input.toPlainText().strip()
        if not message:
            self.ai_status_label.setText("請先輸入訊息")
            self.ai_status_label.setStyleSheet(f"color:{RED};")
            return
        if self.hand_enabled:
            self.ai_status_label.setText("請先關閉手部辨識")
            self.ai_status_label.setStyleSheet(f"color:{RED};")
            return
        self.ai_input.clear()
        self.ai_send_button.setEnabled(False)
        self.hand_button.setEnabled(False)
        self.ai_status_label.setText("正在等待模型回覆")
        self.ai_status_label.setStyleSheet(f"color:{ACCENT};")
        self._append_ai_message("你", message)
        threading.Thread(target=self._request_ai, args=(message,), daemon=True).start()

    def _request_ai(self, message: str) -> None:
        try:
            self.bridge.ai.emit("reply", self.ai_chat.ask(message))
        except Exception as error:
            self.bridge.ai.emit("error", str(error))

    def _handle_ai_event(self, event: str, message: str) -> None:
        self._append_ai_message("AI" if event == "reply" else "後台", message)
        if event == "error":
            self.ai_status_label.setText("請檢查設定")
            self.ai_status_label.setStyleSheet(f"color:{RED};")
            self.ai_send_button.setEnabled(True)
            self.hand_button.setEnabled(True)
            return
        try:
            plan = parse_motion_plan(message, self.ai_chat.gestures)
        except MotionPlanError as error:
            self._append_ai_message("後台", f"動作格式無效：{error}")
            self.ai_status_label.setText("動作格式無效")
            self.ai_status_label.setStyleSheet(f"color:{RED};")
            self.ai_send_button.setEnabled(True)
            self.hand_button.setEnabled(True)
            return
        self._start_ai_plan(plan)

    def _start_ai_plan(self, plan: list[MotionStep]) -> None:
        self.ai_motion_timer.stop()
        self.ai_plan = plan
        self.ai_step_index = 0
        self._run_ai_step()

    def _run_ai_step(self) -> None:
        if self.ai_step_index >= len(self.ai_plan):
            self.ai_status_label.setText("動作完成" if self.connected else "動作預覽完成 · 尚未連線")
            self.ai_status_label.setStyleSheet(f"color:{GREEN if self.connected else MUTED};")
            self.ai_send_button.setEnabled(True)
            self.hand_button.setEnabled(True)
            return

        step = self.ai_plan[self.ai_step_index]
        self.ai_step_index += 1
        progress = f"{self.ai_step_index}/{len(self.ai_plan)}"
        self.ai_status_label.setStyleSheet(f"color:{ACCENT};")
        if isinstance(step, PoseStep):
            self.ai_status_label.setText(f"執行動作 {progress}")
            self._apply_ai_pose(step)
            self.ai_motion_timer.start(config.AI_ACTION_INTERVAL_MS)
        elif isinstance(step, WaitStep):
            self.ai_status_label.setText(f"等待 {step.milliseconds / 1000:g} 秒 · {progress}")
            self.ai_motion_timer.start(step.milliseconds)

    def _append_ai_message(self, role: str, message: str) -> None:
        if self.ai_output.toPlainText().strip():
            self.ai_output.append("")
        self.ai_output.append(f"{role}\n{message}")
        self.ai_output.verticalScrollBar().setValue(self.ai_output.verticalScrollBar().maximum())

    def _toggle_hand_tracking(self) -> None:
        if self.hand_enabled:
            self.hand_enabled = False
            self.hand_button.setEnabled(False)
            self.hand_tracker.stop()
            return
        self.hand_enabled = True
        self.hand_button.setText("正在啟動…")
        self.hand_button.setEnabled(False)
        self.hand_status_label.setText("正在開啟攝影機…")
        self.hand_status_dot.set_color(WARNING)
        self.hand_tracker.start()

    def _poll_hand_tracker(self) -> None:
        try:
            while True:
                event, payload = self.hand_tracker.events.get_nowait()
                if event == "started":
                    self.hand_button.setText("關閉手部辨識")
                    self.hand_button.setIcon(_svg_icon("player-stop", "#FFFFFF"))
                    _set_variant(self.hand_button, "danger")
                    self.hand_button.setEnabled(True)
                    self.hand_status_label.setText(f"攝影機 {payload} · 等待手部進入畫面")
                    self.hand_status_dot.set_color(GREEN)
                elif event == "status":
                    self.hand_status_label.setText(str(payload))
                elif event == "hand_controls":
                    self._apply_hand_controls(payload)
                elif event == "error":
                    self.hand_enabled = False
                    self.hand_status_label.setText("手部辨識啟動失敗")
                    self.hand_status_dot.set_color(RED)
                    QMessageBox.critical(self, "手部辨識操控", str(payload))
                elif event == "stopped":
                    self.hand_enabled = False
                    self.hand_button.setText("開啟手部辨識")
                    self.hand_button.setIcon(_svg_icon("player-play", "#FFFFFF"))
                    _set_variant(self.hand_button, "dark")
                    self.hand_button.setEnabled(True)
                    if self.hand_status_label.text() != "手部辨識啟動失敗":
                        self.hand_status_label.setText("手部辨識尚未啟動")
                        self.hand_status_dot.set_color("#A6ABB4")
                    self.preview_stack.setCurrentIndex(0)
        except queue.Empty:
            pass

        frame_data = self.hand_tracker.pop_frame()
        now = time.monotonic()
        if frame_data is None or now - self.hand_tracker.last_preview_at < (
            config.CAMERA_PREVIEW_INTERVAL_MS / 1000
        ):
            return
        self.hand_tracker.last_preview_at = now
        rgb, _ = frame_data
        height, width, channels = rgb.shape
        image = QImage(
            rgb.data, width, height, channels * width, QImage.Format.Format_RGB888
        ).copy()
        pixmap = QPixmap.fromImage(image)
        target = self.preview.size() - QSize(2, 2)
        scaled = pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - target.width()) // 2)
        y = max(0, (scaled.height() - target.height()) // 2)
        self.camera_label.setPixmap(scaled.copy(x, y, target.width(), target.height()))
        self.preview_stack.setCurrentIndex(1)

    def closeEvent(self, event) -> None:
        self.hand_timer.stop()
        self.hand_tracker.close()
        self.controller.close()
        event.accept()


def run(controller_type, tracker_type) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = KovaQtWindow(controller_type, tracker_type)
    window.show()
    return app.exec()
