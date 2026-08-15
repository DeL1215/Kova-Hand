# Kova Hand

Kova Hand 是一個正在開發中的腱繩驅動機器人左手專案。

目前包含：

- Python 桌面控制介面
- MediaPipe 左手辨識
- BLE 控制 ESP32-C3
- PCA9685 六路伺服馬達控制

## 專案結構

```text
desktop-app/main.py   Python 桌面程式
firmware/main.cpp      ESP32-C3 韌體程式
```

## 快速啟動

桌面程式使用 Python 3.11：

```powershell
cd desktop-app
pip install -r requirements.txt
python main.py
```

ESP32 韌體請使用 PlatformIO 開啟 `firmware` 資料夾進行編譯與燒錄。

> 專案仍在開發中，接線、校正與完整使用說明之後補充。
