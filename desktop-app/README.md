# Kova Hand Control

以 Windows 電腦透過 BLE 控制 ESP32-C3 與 PCA9685 的六路伺服馬達測試介面，並提供 MediaPipe Hands 攝影機預覽。

## 1. 安裝與啟動

在 PowerShell 執行：

```powershell
cd D:\2026CodeProjects\Kova-Hand\desktop-app
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

目前專案使用 `C:\Users\User\anaconda3\envs\KovaHand\python.exe`（Python 3.11）。直接啟動：

```powershell
C:\Users\User\anaconda3\envs\KovaHand\python.exe D:\2026CodeProjects\Kova-Hand\desktop-app\main.py
```

## 2. 修改滑桿

打開 `config.py`，修改 `MOTORS`。每筆設定都有：

- `title`：介面名稱
- `channel`：PCA9685 通道
- `min` / `max`：允許測試的角度範圍
- `initial`：啟動時的顯示角度

目前共有六個馬達控制，編號與 PCA9685 channel 都是 0～5。

## 3. 使用步驟

1. 用 PlatformIO 上傳韌體，並讓 ESP32-C3 重新啟動。
2. Windows 設定中開啟藍牙；不必先在 Windows 配對。
3. 開啟本程式，按「掃描」。
4. 選擇名稱包含 `Kova-Hand` 的裝置，按「連線」。
5. 顯示綠點與「已連線」後再拖動滑桿。

### MediaPipe Hands

按「開啟手部辨識」會開啟攝影機，只追蹤左手並顯示 21 點骨架；再按一次會停止控制、關閉並釋放攝影機。

- 食指、中指、無名指、小指依序控制馬達 0、1、2、3。
- 手指伸直會映射到該馬達的 `min`，握起會映射到 `max`，中間彎曲量會連續映射。
- 馬達 4、5 不受手部辨識控制，仍可用滑桿手動測試。
- 尚未連接 BLE 時只會更新介面滑桿，不會送出馬達命令。

映射可在 `config.py` 的 `HAND_FINGER_MOTORS` 修改。若某顆腱繩馬達方向相反，將該列的 `invert` 改成 `True`；每顆馬達的實際角度範圍仍由 `MOTORS` 的 `min` / `max` 決定。

桌面端會把馬達 0～3 的手部控制角度合併為一個小於 20 bytes 的 BLE 封包，並只保留最新一組角度，避免多指同時動作時塞滿 Windows GATT 佇列。ESP32 會每 20 ms 以小步進移向最新目標，讓多指同步且動作較平順。傳送間隔與最大步進可分別在 `config.py` 與韌體 `Config` 區塊調整。

若無法開啟攝影機：

- 關閉 Windows 相機、Teams、瀏覽器會議等可能占用攝影機的程式。
- 到「Windows 設定 → 隱私權與安全性 → 相機」，允許桌面應用程式使用相機。
- `config.py` 的 `CAMERA_INDEX` 可指定優先鏡頭；程式也會自動嘗試 index 0～4。

> 首次接馬達時，建議先把每個滑桿的範圍縮小（例如 70～110），確認機構方向與極限，避免拉斷手指結構或燒毀舵機。

## 4. ESP32-C3 與 PCA9685 接線

| ESP32-C3 | PCA9685 |
|---|---|
| GPIO 8 | SDA |
| GPIO 9 | SCL |
| 3.3V | VCC（邏輯電源） |
| GND | GND |

- 舵機電源請接 PCA9685 的 `V+`，使用足夠電流的獨立 5～6V 電源。
- 獨立電源 GND、PCA9685 GND、ESP32 GND 必須共地。
- 不要用 ESP32 的 5V/3.3V 腳直接供應六顆舵機。

## 5. 編譯與燒錄韌體

在 VS Code 開啟 `Kova-Hand-Firmware.code-workspace` 後，用 PlatformIO 的 Upload 按鈕燒錄。設定目前使用：

- Board：ESP32-C3-DevKitM-1
- Upload port：COM11（若你的裝置不是 COM11，請改 `platformio.ini`）
- Serial monitor：115200 baud

燒錄後序列埠顯示 `Kova-Hand firmware ready` 即代表 BLE 已開始廣播。韌體開機不會主動轉動舵機，收到第一筆滑桿指令後才會輸出。
