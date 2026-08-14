from __future__ import annotations

import asyncio
import math
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

import config

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # 仍可先開啟介面預覽
    BleakClient = BleakScanner = None

try:
    from PIL import Image, ImageOps, ImageTk
except ImportError:
    Image = ImageOps = ImageTk = None


BG = "#F4F6F8"
SURFACE = "#FFFFFF"
TEXT = "#18202B"
MUTED = "#667085"
BORDER = "#DCE2EA"
ACCENT = "#1769E0"
GREEN = "#169B62"
RED = "#C43D4B"
CAMERA_BG = "#F7F9FC"

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)


def _joint_angle(a, b, c) -> float:
    """Return the 3D angle ABC in degrees for MediaPipe landmarks."""

    first = (a.x - b.x, a.y - b.y, a.z - b.z)
    second = (c.x - b.x, c.y - b.y, c.z - b.z)
    first_length = math.sqrt(sum(value * value for value in first))
    second_length = math.sqrt(sum(value * value for value in second))
    if first_length < 1e-6 or second_length < 1e-6:
        return 180.0
    cosine = sum(x * y for x, y in zip(first, second)) / (first_length * second_length)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def finger_curl(landmarks, indices: tuple[int, int, int, int]) -> float:
    """Map PIP/DIP bending to 0.0 (straight) through 1.0 (closed)."""

    mcp, pip, dip, tip = (landmarks[index] for index in indices)
    total_bend = (180.0 - _joint_angle(mcp, pip, dip)) + (
        180.0 - _joint_angle(pip, dip, tip)
    )
    span = max(1.0, config.HAND_CURL_CLOSED_DEG - config.HAND_CURL_STRAIGHT_DEG)
    return max(0.0, min(1.0, (total_bend - config.HAND_CURL_STRAIGHT_DEG) / span))


class BleController:
    """在背景 asyncio loop 中執行 Bleak，避免卡住 Tk 介面。"""

    def __init__(self, dispatch: Callable):
        self.dispatch = dispatch
        self.client = None
        self.devices: dict[str, object] = {}
        self.pending_angles: dict[int, int] = {}
        self.pending_hand_angles: tuple[int, int, int, int] | None = None
        self.pending_lock = threading.Lock()
        self.closing = threading.Event()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.writer_future = self._submit(self._write_loop())

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def scan(self):
        self._submit(self._scan())

    async def _scan(self):
        if BleakScanner is None:
            self.dispatch("error", "尚未安裝 bleak，請先執行 pip install -r requirements.txt")
            return
        self.dispatch("status", "正在掃描…")
        try:
            found = await BleakScanner.discover(timeout=5.0, return_adv=True)
            self.devices = {}
            service_uuid = config.BLE_SERVICE_UUID.lower()
            entries = []

            for device, advertisement in found.values():
                advertised_services = {
                    uuid.lower() for uuid in (advertisement.service_uuids or [])
                }
                is_kova_hand = service_uuid in advertised_services

                # Windows 有時不會填入 device.name，但 local_name 仍在廣播資料中。
                name = advertisement.local_name or device.name
                if is_kova_hand:
                    name = config.BLE_DEVICE_NAME
                elif not name:
                    name = "未命名裝置"

                display_name = f"{name}  ·  {device.address}"
                self.devices[display_name] = device
                entries.append((not is_kova_hand, display_name.lower(), display_name))

            # Kova-Hand 固定排在最前面，其餘裝置依名稱排序。
            visible_devices = [entry[2] for entry in sorted(entries)]
            self.dispatch("devices", visible_devices)
            self.dispatch("status", f"找到 {len(self.devices)} 個裝置")
        except Exception as exc:
            self.dispatch("error", f"掃描失敗：{exc}")

    def connect(self, display_name: str):
        self._submit(self._connect(display_name))

    def disconnect(self):
        self._submit(self._disconnect())

    async def _connect(self, display_name: str):
        device = self.devices.get(display_name)
        if device is None:
            self.dispatch("error", "請先掃描並選擇裝置")
            return
        try:
            if self.client and self.client.is_connected:
                await self.client.disconnect()
            self.dispatch("status", "正在連線…")
            self.client = BleakClient(device, disconnected_callback=self._disconnected)
            await self.client.connect()
            self._clear_pending_angles()
            self.dispatch("connected", True)
        except Exception as exc:
            self.client = None
            self.dispatch("error", f"連線失敗：{exc}")

    async def _disconnect(self):
        client = self.client
        self.client = None
        self._clear_pending_angles()
        if client and client.is_connected:
            await client.disconnect()
        self.dispatch("connected", False)

    def _disconnected(self, _client):
        self._clear_pending_angles()
        self.dispatch("connected", False)

    def send_angle(self, channel: int, angle: int):
        if not self.client or not self.client.is_connected:
            return
        with self.pending_lock:
            # 同一通道尚未送出的舊角度直接被新角度取代，不讓延遲持續累積。
            self.pending_angles[channel] = angle

    def send_hand_angles(self, angles: dict[int, int]):
        """Queue one compact packet containing channels 0 through 3."""

        if not self.client or not self.client.is_connected:
            return
        if any(channel not in angles for channel in range(4)):
            return
        values = tuple(max(0, min(180, round(angles[channel]))) for channel in range(4))
        with self.pending_lock:
            self.pending_hand_angles = values

    def _clear_pending_angles(self):
        with self.pending_lock:
            self.pending_angles.clear()
            self.pending_hand_angles = None

    async def _write_loop(self):
        """Serialize and rate-limit GATT writes while keeping only fresh angles."""

        interval = max(0.01, config.BLE_WRITE_INTERVAL_MS / 1000)
        while not self.closing.is_set():
            command = None
            with self.pending_lock:
                if self.pending_angles:
                    channel = next(iter(self.pending_angles))
                    angle = self.pending_angles.pop(channel)
                    command = f"S,{channel},{angle}\n".encode("ascii")
                elif self.pending_hand_angles is not None:
                    angles = self.pending_hand_angles
                    self.pending_hand_angles = None
                    command = f"H,{angles[0]},{angles[1]},{angles[2]},{angles[3]}\n".encode("ascii")

            if command is None:
                await asyncio.sleep(0.01)
                continue

            client = self.client
            if client and client.is_connected:
                try:
                    await client.write_gatt_char(
                        config.BLE_CHARACTERISTIC_UUID,
                        command,
                        response=False,
                    )
                except Exception as exc:
                    self._clear_pending_angles()
                    self.dispatch("error", f"傳送失敗：{exc}")

            await asyncio.sleep(interval)

    def close(self):
        self.closing.set()
        self._clear_pending_angles()

        async def disconnect():
            if self.client and self.client.is_connected:
                await self.client.disconnect()

        future = self._submit(disconnect())
        try:
            future.result(timeout=2)
        except Exception:
            pass
        try:
            self.writer_future.result(timeout=1)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


class HandTracker:
    """在背景執行攝影機、辨識左手，並計算四指彎曲量。"""

    def __init__(self):
        self.thread = None
        self.stop_event = threading.Event()
        self.events = queue.SimpleQueue()
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.running = False
        self.smoothed_curls: dict[int, float] = {}
        self.last_preview_at = 0.0

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.smoothed_curls.clear()
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.events.put(("status", "正在關閉攝影機…"))

    def close(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def pop_frame(self):
        with self.frame_lock:
            frame = self.latest_frame
            self.latest_frame = None
        return frame

    @staticmethod
    def _open_camera(cv2):
        preferred = config.CAMERA_INDEX
        indices = [preferred] + [index for index in range(5) if index != preferred]
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]

        for index in indices:
            for backend in backends:
                capture = cv2.VideoCapture(index, backend)
                if capture.isOpened():
                    return capture, index
                capture.release()
        return None, None

    def _run(self):
        capture = None
        landmarker = None
        try:
            import cv2
            import mediapipe as mp

            model_path = Path(__file__).resolve().parent / config.HAND_MODEL_PATH
            if not model_path.exists():
                raise FileNotFoundError(f"找不到模型：{model_path}")

            capture, camera_index = self._open_camera(cv2)
            if capture is None:
                raise RuntimeError(
                    "找不到可用攝影機（已嘗試 index 0～4）。請關閉其他相機程式，"
                    "並在 Windows 隱私權設定允許桌面應用程式使用相機。"
                )

            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
            options = mp.tasks.vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_hands=2,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
            self.events.put(("started", camera_index))
            started_at = time.monotonic()
            frame_count = 0

            while not self.stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError("攝影機讀取失敗")

                # Keep a mirrored selfie preview. The MediaPipe handedness label
                # corresponding to the physical left hand is camera-configurable.
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                timestamp_ms = int((time.monotonic() - started_at) * 1000)
                result = landmarker.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb),
                    timestamp_ms,
                )

                height, width = rgb.shape[:2]
                left_hand = None
                for landmarks, handedness in zip(result.hand_landmarks, result.handedness):
                    label = handedness[0].category_name if handedness else ""
                    if label != config.HAND_LABEL_FOR_PHYSICAL_LEFT:
                        continue
                    left_hand = landmarks
                    points = [
                        (int(mark.x * width), int(mark.y * height))
                        for mark in landmarks
                    ]
                    for start, end in HAND_CONNECTIONS:
                        cv2.line(rgb, points[start], points[end], (255, 255, 255), 2, cv2.LINE_AA)
                    for point in points:
                        cv2.circle(rgb, point, 4, (23, 105, 224), -1, cv2.LINE_AA)
                        cv2.circle(rgb, point, 6, (255, 255, 255), 1, cv2.LINE_AA)
                    break

                if left_hand is not None:
                    overlay_text = "LEFT HAND"
                    (text_width, _), _ = cv2.getTextSize(
                        overlay_text,
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        2,
                    )
                    cv2.putText(
                        rgb,
                        overlay_text,
                        ((width - text_width) // 2, 32),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (23, 105, 224),
                        2,
                        cv2.LINE_AA,
                    )

                frame_count += 1
                with self.frame_lock:
                    self.latest_frame = (rgb, 1 if left_hand is not None else 0)

                if left_hand is not None and frame_count % config.HAND_CONTROL_FRAME_INTERVAL == 0:
                    curls = {}
                    for finger in config.HAND_FINGER_MOTORS:
                        channel = finger["channel"]
                        measured = finger_curl(left_hand, finger["landmarks"])
                        previous = self.smoothed_curls.get(channel, measured)
                        if measured in (0.0, 1.0):
                            smoothed = measured
                        else:
                            movement = abs(measured - previous)
                            smoothing = min(
                                config.HAND_SMOOTHING_MAX,
                                config.HAND_SMOOTHING_MIN
                                + movement * config.HAND_SMOOTHING_RESPONSE,
                            )
                            smoothed = previous + smoothing * (measured - previous)
                        self.smoothed_curls[channel] = smoothed
                        curls[channel] = smoothed
                    self.events.put(("finger_curls", curls))

                if frame_count % 15 == 0:
                    self.events.put((
                        "status",
                        "已偵測左手 · 控制馬達 0～3"
                        if left_hand is not None
                        else "請將左手放入畫面",
                    ))
        except ImportError:
            self.events.put(("error", "缺少 MediaPipe 套件，請重新安裝 requirements.txt"))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            if capture is not None:
                capture.release()
            if landmarker is not None:
                landmarker.close()
            self.running = False
            self.events.put(("stopped", None))


class AngleSlider(tk.Canvas):
    """可點擊、拖動及用方向鍵控制的簡潔角度滑桿。"""

    def __init__(self, master, minimum: int, maximum: int, value: int, command: Callable):
        super().__init__(
            master,
            height=24,
            bg=SURFACE,
            highlightthickness=0,
            cursor="hand2",
            takefocus=True,
        )
        self.minimum = minimum
        self.maximum = maximum
        self.value = value
        self.command = command
        self.dragging = False
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Left>", lambda _event: self._step(-1))
        self.bind("<Right>", lambda _event: self._step(1))

    def _x_for_value(self) -> float:
        usable = max(1, self.winfo_width() - 24)
        ratio = (self.value - self.minimum) / max(1, self.maximum - self.minimum)
        return 12 + ratio * usable

    def _value_for_x(self, x: float) -> int:
        usable = max(1, self.winfo_width() - 24)
        ratio = min(1.0, max(0.0, (x - 12) / usable))
        return round(self.minimum + ratio * (self.maximum - self.minimum))

    def _draw(self):
        self.delete("all")
        y = 12
        end = max(12, self.winfo_width() - 12)
        knob_x = self._x_for_value()
        self.create_line(12, y, end, y, fill="#D9DEE6", width=5, capstyle="round")
        self.create_line(12, y, knob_x, y, fill=ACCENT, width=5, capstyle="round")
        self.create_oval(knob_x - 8, y - 8, knob_x + 8, y + 8, fill=SURFACE, outline=ACCENT, width=3)

    def set_value(self, value: int, notify: bool = True):
        self.value = min(self.maximum, max(self.minimum, round(value)))
        self._draw()
        if notify:
            self.command(self.value)

    def _press(self, event):
        self.focus_set()
        self.dragging = True
        self.set_value(self._value_for_x(event.x))

    def _move(self, event):
        if self.dragging:
            self.set_value(self._value_for_x(event.x))

    def _release(self, event):
        self.dragging = False
        self.set_value(self._value_for_x(event.x))
        self.event_generate("<<SliderReleased>>")

    def _step(self, amount: int):
        self.set_value(self.value + amount)
        self.event_generate("<<SliderReleased>>")


class RangeLabels(tk.Canvas):
    """使用與 AngleSlider 相同的 12px 軌道邊界，確保中點精準對齊。"""

    def __init__(self, master, minimum: int, maximum: int):
        super().__init__(master, height=19, bg=SURFACE, highlightthickness=0)
        self.minimum = minimum
        self.maximum = maximum
        self.bind("<Configure>", self._draw)

    def _draw(self, _event=None):
        self.delete("all")
        width = self.winfo_width()
        midpoint = round((self.minimum + self.maximum) / 2)
        font = ("Segoe UI", 9)
        self.create_text(12, 9, text=f"{self.minimum}°", anchor="w", fill=MUTED, font=font)
        self.create_text(width / 2, 9, text=f"{midpoint}°", anchor="center", fill=MUTED, font=font)
        self.create_text(width - 12, 9, text=f"{self.maximum}°", anchor="e", fill=MUTED, font=font)


class MotorRow(ttk.Frame):
    def __init__(self, master, motor: dict, on_change: Callable[[int, int], None]):
        super().__init__(master, style="Motor.TFrame", padding=(18, 10))
        self.motor = motor
        self.on_change = on_change
        self.value = tk.IntVar(value=motor["initial"])
        self.pending_send = None

        self.columnconfigure(2, weight=1, minsize=220)
        ttk.Label(self, text=motor["title"], style="MotorTitle.TLabel", width=8).grid(
            row=0, column=0, rowspan=2, sticky="w", padx=(0, 8)
        )
        self.value_label = ttk.Label(
            self, text=f"{self.value.get()}°", style="Value.TLabel", width=6
        )
        self.value_label.grid(row=0, column=1, rowspan=2, sticky="w", padx=(0, 10))

        self.scale = AngleSlider(
            self,
            minimum=motor["min"],
            maximum=motor["max"],
            value=motor["initial"],
            command=self._slider_changed,
        )
        self.scale.grid(row=1, column=2, sticky="ew")
        self.scale.bind("<<SliderReleased>>", self._released)

        self.range_labels = RangeLabels(self, motor["min"], motor["max"])
        self.range_labels.grid(row=0, column=2, sticky="ew", pady=(0, 1))

    def _slider_changed(self, raw_value):
        angle = round(float(raw_value))
        self.value.set(angle)
        self.value_label.configure(text=f"{angle}°")
        if self.pending_send:
            self.after_cancel(self.pending_send)
        self.pending_send = self.after(
            config.SEND_INTERVAL_MS,
            lambda: self.on_change(self.motor["channel"], self.value.get()),
        )

    def _released(self, _event):
        if self.pending_send:
            self.after_cancel(self.pending_send)
            self.pending_send = None
        self.on_change(self.motor["channel"], self.value.get())

    def center(self):
        center = round((self.motor["min"] + self.motor["max"]) / 2)
        self.value.set(center)
        self.value_label.configure(text=f"{center}°")
        self.scale.set_value(center, notify=False)
        self.on_change(self.motor["channel"], center)


class KovaHandApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(config.APP_TITLE)
        self.geometry(config.WINDOW_SIZE)
        self.minsize(1040, 680)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.controller = BleController(self._from_ble_thread)
        self.hand_tracker = HandTracker()
        self.connected = False
        self.hand_enabled = False
        self.camera_photo = None
        self.motor_rows_by_channel = {}
        self._build_styles()
        self._build_ui()
        self.after(33, self._poll_hand_tracker)

    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background=BG)
        style.configure("Panel.TFrame", background=SURFACE, relief="solid", borderwidth=1)
        style.configure("PanelInner.TFrame", background=SURFACE)
        style.configure("Motor.TFrame", background=SURFACE)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 25, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Field.TLabel", background=SURFACE, foreground=TEXT, font=("Segoe UI", 10, "bold"))
        style.configure("Status.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("MotorTitle.TLabel", background=SURFACE, foreground=TEXT, font=("Segoe UI", 12, "bold"))
        style.configure("Value.TLabel", background=SURFACE, foreground=TEXT, font=("Segoe UI", 18, "bold"))
        style.configure("Range.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Footer.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("PanelTitle.TLabel", background=SURFACE, foreground=TEXT, font=("Segoe UI", 15, "bold"))
        style.configure("CameraStatus.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("TCombobox", padding=8, font=("Segoe UI", 10))
        style.configure("Primary.TButton", background=ACCENT, foreground="white", padding=(18, 10), font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.map("Primary.TButton", background=[("active", "#0F56BE"), ("disabled", "#A9B6C9")])
        style.configure("Secondary.TButton", background="#EAF1FC", foreground=ACCENT, padding=(15, 10), font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#D9E7FA")])
        style.configure("Danger.TButton", background="#E9EEF5", foreground=TEXT, padding=(18, 11), font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#DCE3EC")])
        style.configure("Soft.TSeparator", background=BORDER)

    def _build_ui(self):
        from modern_ui import build_ui

        build_ui(self)

    def _build_legacy_ui(self):
        root = ttk.Frame(self, style="App.TFrame", padding=(28, 22, 28, 16))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        heading = ttk.Frame(root, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        ttk.Label(heading, text=config.APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(heading, text="機器人手部控制台", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))

        connection = ttk.Frame(root, style="Panel.TFrame", padding=(20, 16))
        connection.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="藍牙裝置", style="Field.TLabel").grid(row=0, column=0, padx=(0, 12))
        self.device_box = ttk.Combobox(connection, state="readonly", width=42)
        self.device_box.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.scan_button = ttk.Button(connection, text="掃描", style="Secondary.TButton", command=self._scan)
        self.scan_button.grid(row=0, column=2, padx=(0, 8))
        self.connect_button = ttk.Button(connection, text="連線", style="Primary.TButton", command=self._connect)
        self.connect_button.grid(row=0, column=3, padx=(0, 18))
        self.status_dot = tk.Canvas(connection, width=12, height=12, bg=SURFACE, highlightthickness=0)
        self.dot = self.status_dot.create_oval(2, 2, 10, 10, fill="#AAB1BC", outline="")
        self.status_dot.grid(row=0, column=4, padx=(0, 6))
        self.status_label = ttk.Label(connection, text="尚未連線", style="Status.TLabel", width=14)
        self.status_label.grid(row=0, column=5, sticky="w")
        workspace = ttk.Frame(root, style="App.TFrame")
        workspace.grid(row=2, column=0, sticky="nsew")
        workspace.columnconfigure(0, weight=1, uniform="workspace")
        workspace.columnconfigure(1, weight=1, uniform="workspace")
        workspace.rowconfigure(0, weight=1)

        motor_panel = ttk.Frame(workspace, style="Panel.TFrame", padding=(14, 14))
        motor_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        motor_panel.columnconfigure(0, weight=1)
        motor_header = ttk.Frame(motor_panel, style="PanelInner.TFrame")
        motor_header.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 10))
        motor_header.columnconfigure(0, weight=1)
        ttk.Label(motor_header, text="馬達控制", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(motor_header, text="全部置中", style="Secondary.TButton", command=self._center_all).grid(row=0, column=1)

        motor_list = ttk.Frame(motor_panel, style="PanelInner.TFrame")
        motor_list.grid(row=1, column=0, sticky="new")
        motor_list.columnconfigure(0, weight=1)
        self.motor_rows = []
        for index, motor in enumerate(config.MOTORS):
            row = MotorRow(motor_list, motor, self._send_angle)
            row.grid(row=index * 2, column=0, sticky="ew")
            self.motor_rows.append(row)
            if index < len(config.MOTORS) - 1:
                ttk.Separator(motor_list, style="Soft.TSeparator").grid(row=index * 2 + 1, column=0, sticky="ew")

        hand_panel = ttk.Frame(workspace, style="Panel.TFrame", padding=(18, 14))
        hand_panel.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        hand_panel.columnconfigure(0, weight=1)
        hand_panel.rowconfigure(1, weight=1)
        ttk.Label(hand_panel, text="MediaPipe Hands", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.camera_label = tk.Label(
            hand_panel,
            text="攝影機預覽\n等待啟動",
            bg=CAMERA_BG,
            fg="#AEB7C5",
            font=("Segoe UI", 14),
            justify="center",
            borderwidth=0,
        )
        self.camera_label.grid(row=1, column=0, sticky="nsew")

        hand_status = ttk.Frame(hand_panel, style="PanelInner.TFrame")
        hand_status.grid(row=2, column=0, sticky="ew", pady=(12, 10))
        self.hand_status_dot = tk.Canvas(hand_status, width=12, height=12, bg=SURFACE, highlightthickness=0)
        self.hand_dot = self.hand_status_dot.create_oval(2, 2, 10, 10, fill="#AAB1BC", outline="")
        self.hand_status_dot.pack(side="left", padx=(0, 7))
        self.hand_status_label = ttk.Label(hand_status, text="手部辨識尚未啟動", style="CameraStatus.TLabel")
        self.hand_status_label.pack(side="left")

        self.hand_button = ttk.Button(
            hand_panel,
            text="開啟手部辨識",
            style="Primary.TButton",
            command=self._toggle_hand_tracking,
        )
        self.hand_button.grid(row=3, column=0, sticky="ew")
        ttk.Label(
            hand_panel,
            text="僅顯示辨識結果，尚未控制馬達",
            style="CameraStatus.TLabel",
        ).grid(row=4, column=0, pady=(10, 0))

        ttk.Label(root, text="滑桿名稱與角度範圍可在 config.py 修改", style="Footer.TLabel").grid(row=3, column=0, pady=(10, 0))

    def _from_ble_thread(self, event: str, payload):
        self.after(0, lambda: self._handle_ble_event(event, payload))

    def _handle_ble_event(self, event: str, payload):
        if event == "devices":
            self.device_box["values"] = payload
            preferred = next((name for name in payload if config.BLE_DEVICE_NAME.lower() in name.lower()), None)
            if preferred:
                self.device_box.set(preferred)
            elif payload:
                self.device_box.current(0)
            self.scan_button.configure(state="normal")
        elif event == "status":
            self.status_label.configure(text=payload)
        elif event == "connected":
            self.connected = bool(payload)
            self.status_dot.itemconfigure(self.dot, fill=GREEN if self.connected else "#AAB1BC")
            self.status_label.configure(text="已連線" if self.connected else "連線已中斷")
            self.connect_button.configure(
                text="中斷連線" if self.connected else "連線",
                image=self.ui_icons["unlink" if self.connected else "connect"],
                style="Danger.TButton" if self.connected else "Primary.TButton",
            )
        elif event == "error":
            self.scan_button.configure(state="normal")
            self.status_dot.itemconfigure(self.dot, fill=RED)
            self.status_label.configure(text="發生錯誤")
            messagebox.showerror("Kova Hand", payload)

    def _scan(self):
        self.scan_button.configure(state="disabled")
        self.controller.scan()

    def _connect(self):
        if self.connected:
            self.controller.disconnect()
        else:
            self.controller.connect(self.device_box.get())

    def _send_angle(self, channel: int, angle: int):
        if self.connected:
            self.controller.send_angle(channel, angle)

    def _apply_finger_curls(self, curls: dict[int, float]):
        hand_angles = {}
        for finger in config.HAND_FINGER_MOTORS:
            channel = finger["channel"]
            row = self.motor_rows_by_channel.get(channel)
            if row is None or channel not in curls:
                continue
            amount = 1.0 - curls[channel] if finger.get("invert", False) else curls[channel]
            target = row.motor["min"] + amount * (row.motor["max"] - row.motor["min"])
            hand_angles[channel] = row.set_external_value(target)

        if self.connected and len(hand_angles) == 4:
            self.controller.send_hand_angles(hand_angles)

    def _center_all(self):
        for index, row in enumerate(self.motor_rows):
            row.center()
            if index < len(self.motor_rows) - 1:
                self.update_idletasks()

    def _toggle_hand_tracking(self):
        if self.hand_enabled:
            self.hand_enabled = False
            self.hand_button.configure(state="disabled")
            self.hand_tracker.stop()
        else:
            if ImageTk is None:
                messagebox.showerror("Kova Hand", "尚未安裝 Pillow，請安裝 requirements.txt")
                return
            self.hand_enabled = True
            self.hand_button.configure(text="正在啟動…", state="disabled")
            self.hand_status_label.configure(text="正在開啟攝影機…")
            self.hand_status_dot.itemconfigure(self.hand_dot, fill="#E6A23C")
            self.hand_tracker.start()

    def _poll_hand_tracker(self):
        try:
            while True:
                event, payload = self.hand_tracker.events.get_nowait()
                if event == "started":
                    self.hand_button.configure(
                        text="關閉手部辨識",
                        image=self.ui_icons["stop"],
                        style="Danger.TButton",
                        state="normal",
                    )
                    self.hand_status_label.configure(text=f"攝影機 {payload} · 等待手部進入畫面")
                    self.hand_status_dot.itemconfigure(self.hand_dot, fill=GREEN)
                elif event == "status":
                    self.hand_status_label.configure(text=payload)
                elif event == "finger_curls":
                    self._apply_finger_curls(payload)
                elif event == "error":
                    self.hand_enabled = False
                    self.hand_status_label.configure(text="手部辨識啟動失敗")
                    self.hand_status_dot.itemconfigure(self.hand_dot, fill=RED)
                    messagebox.showerror("MediaPipe Hands", payload)
                elif event == "stopped":
                    self.hand_enabled = False
                    self.hand_button.configure(
                        text="開啟手部辨識",
                        image=self.ui_icons["play"],
                        style="Primary.TButton",
                        state="normal",
                    )
                    if self.hand_status_label.cget("text") != "手部辨識啟動失敗":
                        self.hand_status_label.configure(text="手部辨識尚未啟動")
                        self.hand_status_dot.itemconfigure(self.hand_dot, fill="#AAB1BC")
                    self.camera_photo = None
                    self.camera_label.configure(
                        image=self.ui_icons["camera"],
                        compound="top",
                        text="攝影機預覽\n開啟後顯示手部辨識畫面",
                    )
        except queue.Empty:
            pass

        frame_data = self.hand_tracker.pop_frame()
        now = time.monotonic()
        preview_due = (
            now - self.hand_tracker.last_preview_at
            >= config.CAMERA_PREVIEW_INTERVAL_MS / 1000
        )
        if frame_data is not None and Image is not None and preview_due:
            self.hand_tracker.last_preview_at = now
            rgb, _hand_count = frame_data
            width = max(320, self.camera_label.winfo_width())
            height = max(240, self.camera_label.winfo_height())
            image = Image.fromarray(rgb)
            image = ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS)
            self.camera_photo = ImageTk.PhotoImage(image=image)
            self.camera_label.configure(image=self.camera_photo, text="")

        self.after(33, self._poll_hand_tracker)

    def _close(self):
        self.hand_tracker.close()
        self.controller.close()
        self.destroy()


if __name__ == "__main__":
    KovaHandApp().mainloop()
