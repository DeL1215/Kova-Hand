"""Kova Hand 控制器設定。

測試不同馬達時，通常只需要修改這個檔案。
"""

APP_TITLE = "Kova Hand Control"
WINDOW_SIZE = "1280x780"

# 必須和 ESP32 韌體中的 UUID 完全相同。
BLE_DEVICE_NAME = "Kova-Hand"
BLE_SERVICE_UUID = "19b10000-e8f2-537e-4f6c-d104768a1214"
BLE_CHARACTERISTIC_UUID = "19b10001-e8f2-537e-4f6c-d104768a1214"

# 拖動時最多每隔幾毫秒傳送一次，避免一次送出太多 BLE 封包。
SEND_INTERVAL_MS = 55

# 所有 BLE 馬達命令都由單一寫入器依序傳送，避免 Windows GATT 同時寫入而斷線。
# 手部控制會把四指合併成一包，40 ms 約為每秒 25 次同步更新。
BLE_WRITE_INTERVAL_MS = 35

# title: 介面顯示名稱
# channel: PCA9685 通道（0～15）
# min/max: 滑桿可調角度；initial: 程式啟動時顯示的角度
# 六個控制通道，介面編號與 PCA9685 channel 都是 0～5。
MOTORS = [
    {"title": "馬達 - 食指", "channel": 0, "min": 0, "max": 180, "initial": 90},
    {"title": "馬達 - 中指", "channel": 1, "min": 0, "max": 180, "initial": 90},
    {"title": "馬達 - 無名指", "channel": 2, "min": 0, "max": 180, "initial": 90},
    {"title": "馬達 - 小指", "channel": 3, "min": 0, "max": 180, "initial": 90},
    {"title": "馬達 4", "channel": 4, "min": 0, "max": 180, "initial": 90},
    {"title": "馬達 5", "channel": 5, "min": 0, "max": 180, "initial": 90},
]

CAMERA_INDEX = 0
HAND_MODEL_PATH = "models/hand_landmarker.task"

# 這台攝影機的鏡像方向會讓 MediaPipe 以 Right 標記實際左手。
# 若日後更換攝影機後左右相反，只需要在這裡改成 "Left"。
HAND_LABEL_FOR_PHYSICAL_LEFT = "Right"

# MediaPipe 左手腱繩控制。
# channel 0～3 依序是食指、中指、無名指、小指；馬達 4、5 不受手勢控制。
# invert=False：手指伸直 -> MOTORS 的 min，握起 -> max。
# 若某顆馬達實際方向相反，只要把該列改成 invert=True。
HAND_FINGER_MOTORS = [
    {"name": "食指", "channel": 0, "landmarks": (5, 6, 7, 8), "invert": False},
    {"name": "中指", "channel": 1, "landmarks": (9, 10, 11, 12), "invert": False},
    {"name": "無名指", "channel": 2, "landmarks": (13, 14, 15, 16), "invert": False},
    {"name": "小指", "channel": 3, "landmarks": (17, 18, 19, 20), "invert": False},
]

# PIP + DIP 兩個關節的總彎曲角度。低於 STRAIGHT 視為完全伸直，
# 高於 CLOSED 視為完全握起；中間值會連續映射到馬達角度。
HAND_CURL_STRAIGHT_DEG = 15.0
HAND_CURL_CLOSED_DEG = 150.0

# 0～1；越小越穩定但反應較慢。四指已合併成單一封包，可以每幀更新。
# 自適應平滑：手指只有小幅抖動時較穩，快速彎曲時則立刻跟上。
HAND_SMOOTHING_MIN = 0.16
HAND_SMOOTHING_MAX = 0.82
HAND_SMOOTHING_RESPONSE = 2.4
HAND_CONTROL_FRAME_INTERVAL = 1

# 預覽不必與辨識同速；降低 UI 圖片縮放負擔，但不降低馬達更新率。
CAMERA_PREVIEW_INTERVAL_MS = 66

