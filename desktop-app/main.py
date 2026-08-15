"""BLE and MediaPipe backend for the Kova Hand desktop app."""

from __future__ import annotations

import asyncio
import math
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import config

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # 仍可先開啟介面預覽
    BleakClient = BleakScanner = None


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


def finger_curl(
    landmarks,
    indices: tuple[int, int, int, int],
    straight_deg: float = config.HAND_CURL_STRAIGHT_DEG,
    closed_deg: float = config.HAND_CURL_CLOSED_DEG,
) -> float:
    """Map PIP/DIP bending to 0.0 (straight) through 1.0 (closed)."""

    mcp, pip, dip, tip = (landmarks[index] for index in indices)
    total_bend = (180.0 - _joint_angle(mcp, pip, dip)) + (
        180.0 - _joint_angle(pip, dip, tip)
    )
    span = max(1.0, closed_deg - straight_deg)
    return max(0.0, min(1.0, (total_bend - straight_deg) / span))


def thumb_cmc_inward(landmarks) -> float:
    """Map thumb opposition from CMC 0° (outward) to 90° (inward)."""

    spread = _joint_angle(landmarks[2], landmarks[0], landmarks[5])
    span = max(
        1.0,
        config.THUMB_CMC_OUTWARD_SPREAD_DEG - config.THUMB_CMC_INWARD_SPREAD_DEG,
    )
    return max(
        0.0,
        min(1.0, (config.THUMB_CMC_OUTWARD_SPREAD_DEG - spread) / span),
    )


class BleController:
    """在背景 asyncio loop 中執行 Bleak，避免阻塞桌面介面。"""

    def __init__(self, dispatch: Callable):
        self.dispatch = dispatch
        self.client = None
        self.devices: dict[str, object] = {}
        self.pending_angles: dict[int, int] = {}
        self.pending_hand_angles: tuple[int, ...] | None = None
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
        """Queue one compact binary packet containing all six channels."""

        if not self.client or not self.client.is_connected:
            return
        if any(channel not in angles for channel in range(6)):
            return
        values = tuple(max(0, min(180, round(angles[channel]))) for channel in range(6))
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
                    command = bytes((ord("B"), *angles))

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
    """在背景辨識左手並計算六個馬達控制量。"""

    def __init__(self):
        self.thread = None
        self.stop_event = threading.Event()
        self.events = queue.SimpleQueue()
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.running = False
        self.smoothed_controls: dict[int, float] = {}
        self.last_preview_at = 0.0

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.smoothed_controls.clear()
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

    def _smooth(self, channel: int, measured: float) -> float:
        previous = self.smoothed_controls.get(channel, measured)
        if measured in (0.0, 1.0):
            result = measured
        else:
            movement = abs(measured - previous)
            amount = min(
                config.HAND_SMOOTHING_MAX,
                config.HAND_SMOOTHING_MIN + movement * config.HAND_SMOOTHING_RESPONSE,
            )
            result = previous + amount * (measured - previous)
        self.smoothed_controls[channel] = result
        return result

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
                    controls = {}
                    for control in config.HAND_CONTROLS:
                        measured = (
                            finger_curl(
                                left_hand,
                                control["landmarks"],
                                control.get("straight_deg", config.HAND_CURL_STRAIGHT_DEG),
                                control.get("closed_deg", config.HAND_CURL_CLOSED_DEG),
                            )
                            if control["metric"] == "curl"
                            else thumb_cmc_inward(left_hand)
                        )
                        channel = control["channel"]
                        controls[channel] = self._smooth(channel, measured)
                    self.events.put(("hand_controls", controls))

                if frame_count % 15 == 0:
                    self.events.put((
                        "status",
                        "已偵測左手 · 控制馬達 0～5"
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


if __name__ == "__main__":
    from qt_ui import run

    raise SystemExit(run(BleController, HandTracker))

