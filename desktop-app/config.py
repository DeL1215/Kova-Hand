# SPDX-FileCopyrightText: 2026 Kova Hand Project
# SPDX-License-Identifier: MIT

"""Kova Hand 控制器設定。

測試不同馬達時，通常只需要修改這個檔案。
"""

APP_TITLE = "Kova Hand Control"

# 必須和 ESP32 韌體中的 UUID 完全相同。
BLE_DEVICE_NAME = "Kova-Hand"
BLE_SERVICE_UUID = "19b10000-e8f2-537e-4f6c-d104768a1214"
BLE_CHARACTERISTIC_UUID = "19b10001-e8f2-537e-4f6c-d104768a1214"

# 所有 BLE 馬達命令都由單一寫入器依序傳送，避免 Windows GATT 同時寫入而斷線。
# 六個手部控制值會合併成一個 7-byte BLE 封包。
BLE_WRITE_INTERVAL_MS = 35

# AI 連續動作間的最短間隔，確保每個 BLE 姿勢封包都有時間送出。
AI_ACTION_INTERVAL_MS = 90

# title: 介面顯示名稱
# channel: PCA9685 通道（0～15）
# min/max: 滑桿可調角度
# 六個控制通道，介面編號與 PCA9685 channel 都是 0～5。
MOTORS = [
    {"title": "馬達 - 食指", "channel": 0, "min": 0, "max": 180},
    {"title": "馬達 - 中指", "channel": 1, "min": 0, "max": 180},
    {"title": "馬達 - 無名指", "channel": 2, "min": 0, "max": 180},
    {"title": "馬達 - 小指", "channel": 3, "min": 0, "max": 180},
    {"title": "馬達 - 拇指彎曲", "channel": 4, "min": 0, "max": 180},
    {"title": "馬達 - 拇指CMC", "channel": 5, "min": 0, "max": 180},
]

# PCA9685 50 Hz PWM 端點（tick）。中指與拇指彎曲使用新批次 MG90S 的安全預設。
SERVO_PWM_DEFAULTS = {
    0: (150, 600),
    1: (150, 480),
    2: (150, 600),
    3: (150, 600),
    4: (150, 480),
    5: (150, 600),
}
SERVO_PWM_LIMITS = (80, 650)
SERVO_PWM_MIN_SPAN = 40

CAMERA_INDEX = 0
HAND_MODEL_PATH = "models/hand_landmarker.task"

# 這台攝影機的鏡像方向會讓 MediaPipe 以 Right 標記實際左手。
# 若日後更換攝影機後左右相反，只需要在這裡改成 "Left"。
HAND_LABEL_FOR_PHYSICAL_LEFT = "Right"

# MediaPipe 的預設門檻在一般攝影機下較不容易漏掉快速移動的手。
HAND_MIN_DETECTION_CONFIDENCE = 0.50
HAND_MIN_PRESENCE_CONFIDENCE = 0.50
HAND_MIN_TRACKING_CONFIDENCE = 0.50

# MediaPipe 左手腱繩控制。
# invert=False：手指伸直 -> MOTORS 的 min，握起 -> max。
# 若某顆馬達實際方向相反，只要把該列改成 invert=True。
HAND_CONTROLS = [
    {"name": "食指", "channel": 0, "metric": "curl", "landmarks": (5, 6, 7, 8), "invert": False},
    {"name": "中指", "channel": 1, "metric": "curl", "landmarks": (9, 10, 11, 12), "invert": False},
    {"name": "無名指", "channel": 2, "metric": "curl", "landmarks": (13, 14, 15, 16), "invert": False},
    {"name": "小指", "channel": 3, "metric": "curl", "landmarks": (17, 18, 19, 20), "invert": False},
    {"name": "拇指彎曲", "channel": 4, "metric": "thumb_curl", "landmarks": (1, 2, 3, 4), "straight_deg": 5.0, "closed_deg": 75.0, "invert": False},
    # 實機方向：手指內側為 0°，往手掌側邊展開為 180°。
    {"name": "拇指 CMC", "channel": 5, "metric": "cmc", "invert": True},
]

# PIP + DIP 兩個關節的總彎曲角度。低於 STRAIGHT 視為完全伸直，
# 高於 CLOSED 視為完全握起；中間值會連續映射到馬達角度。
HAND_CURL_STRAIGHT_DEG = 15.0
HAND_CURL_CLOSED_DEG = 110.0

# 攝影機量到的拇指展開角度會先正規化為 OUTWARD=0、INWARD=1，
# 再由 channel 5 的 invert 反轉成實機需要的 OUTWARD=180°、INWARD=0°。
THUMB_CMC_OUTWARD_SPREAD_DEG = 35.0
THUMB_CMC_INWARD_SPREAD_DEG = 15.0

# 先用短窗中位數排除單幀跳點，再以死區、自適應平滑和最大步幅抑制抖動。
# 所有數值皆以正規化控制量 0～1 表示。
HAND_FILTER_WINDOW = 3
HAND_DEAD_ZONE = 0.012
HAND_MAX_DELTA_PER_UPDATE = 0.25
HAND_SMOOTHING_MIN = 0.18
HAND_SMOOTHING_MAX = 0.70
HAND_SMOOTHING_RESPONSE = 2.2
HAND_CONTROL_FRAME_INTERVAL = 1

# 預覽不必與辨識同速；降低 UI 圖片縮放負擔，但不降低馬達更新率。
CAMERA_PREVIEW_INTERVAL_MS = 66
