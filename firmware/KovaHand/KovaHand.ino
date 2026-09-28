// SPDX-FileCopyrightText: 2026 Kova Hand Project
// SPDX-License-Identifier: MIT

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <NimBLEDevice.h>
#include <Preferences.h>

// ============================================================
// Kova Hand：ESP32-C3 + PCA9685 + BLE 六路舵機控制器
// 單路指令：S,通道,角度\n，例如 S,0,90
// 六馬達同步指令：7 bytes，'B' 後接 channel 0～5 的 uint8 角度。
// ============================================================

namespace Config {

// ESP32-C3 連接 PCA9685 的 I2C 腳位。
constexpr uint8_t SDA_PIN = 8;
constexpr uint8_t SCL_PIN = 9;

constexpr uint8_t PCA9685_ADDRESS = 0x40;
constexpr uint8_t SERVO_COUNT = 6;
constexpr uint16_t SERVO_FREQUENCY_HZ = 50;
constexpr uint16_t SERVO_UPDATE_INTERVAL_MS = 20;
// 20 ms 走 8 度：仍有漸進移動，但不會明顯落後於手勢。
constexpr uint8_t SERVO_MAX_STEP_DEG = 8;
constexpr uint8_t SERVO_START_ANGLE_DEG = 0;

// 每顆舵機獨立校正。舊馬達沿用原本可到 180° 的端點；
// 新批次 MG90S 使用較短脈寬，避免在終點撞限位後回抽。
struct ServoPulseRange {
  uint16_t minimum;
  uint16_t maximum;
};

constexpr ServoPulseRange DEFAULT_SERVO_PULSE_RANGES[SERVO_COUNT] = {
    {150, 600},  // 0: 食指，舊馬達
    {150, 480},  // 1: 中指，新馬達
    {150, 600},  // 2: 無名指，舊馬達
    {150, 600},  // 3: 小指，舊馬達
    {150, 480},  // 4: 拇指彎曲，新馬達
    {150, 600},  // 5: 拇指 CMC，舊馬達
};

constexpr uint16_t SERVO_PULSE_FLOOR = 80;
constexpr uint16_t SERVO_PULSE_CEILING = 650;
constexpr uint16_t SERVO_PULSE_MIN_SPAN = 40;

// 必須與 desktop-app/config.py 完全一致。
constexpr char BLE_DEVICE_NAME[] = "Kova-Hand";
constexpr char BLE_SERVICE_UUID[] = "19b10000-e8f2-537e-4f6c-d104768a1214";
constexpr char BLE_CHARACTERISTIC_UUID[] = "19b10001-e8f2-537e-4f6c-d104768a1214";

}  // namespace Config

Adafruit_PWMServoDriver pwm(Config::PCA9685_ADDRESS);
Config::ServoPulseRange servoPulseRanges[Config::SERVO_COUNT];
int currentAngles[Config::SERVO_COUNT] = {};
int targetAngles[Config::SERVO_COUNT] = {};
bool servoEnabled[Config::SERVO_COUNT] = {};

bool validPulseRange(uint16_t minimum, uint16_t maximum) {
  return minimum >= Config::SERVO_PULSE_FLOOR &&
         maximum <= Config::SERVO_PULSE_CEILING &&
         maximum >= minimum + Config::SERVO_PULSE_MIN_SPAN;
}

void loadServoCalibration() {
  Preferences storage;
  const bool opened = storage.begin("servo-pwm", true);
  for (uint8_t channel = 0; channel < Config::SERVO_COUNT; ++channel) {
    const auto defaults = Config::DEFAULT_SERVO_PULSE_RANGES[channel];
    if (!opened) {
      servoPulseRanges[channel] = defaults;
      continue;
    }
    char minKey[8];
    char maxKey[8];
    snprintf(minKey, sizeof(minKey), "m%umin", channel);
    snprintf(maxKey, sizeof(maxKey), "m%umax", channel);
    const uint16_t minimum = storage.getUShort(minKey, defaults.minimum);
    const uint16_t maximum = storage.getUShort(maxKey, defaults.maximum);
    servoPulseRanges[channel] = validPulseRange(minimum, maximum)
        ? Config::ServoPulseRange{minimum, maximum}
        : defaults;
  }
  if (opened) {
    storage.end();
  }
}

bool saveServoCalibration(uint8_t channel, uint16_t minimum, uint16_t maximum) {
  if (channel >= Config::SERVO_COUNT || !validPulseRange(minimum, maximum)) {
    return false;
  }
  Preferences storage;
  if (!storage.begin("servo-pwm", false)) {
    return false;
  }
  char minKey[8];
  char maxKey[8];
  snprintf(minKey, sizeof(minKey), "m%umin", channel);
  snprintf(maxKey, sizeof(maxKey), "m%umax", channel);
  const bool saved = storage.putUShort(minKey, minimum) == sizeof(uint16_t) &&
                     storage.putUShort(maxKey, maximum) == sizeof(uint16_t);
  storage.end();
  if (saved) {
    servoPulseRanges[channel] = {minimum, maximum};
  }
  return saved;
}

void restoreServoState() {
  for (uint8_t channel = 0; channel < Config::SERVO_COUNT; ++channel) {
    const Config::ServoPulseRange& range = servoPulseRanges[channel];
    const uint16_t pulse = pwm.getPWM(channel, true);
    if (pulse < range.minimum || pulse > range.maximum) {
      continue;
    }

    const int pulseSpan = range.maximum - range.minimum;
    const int angle = ((pulse - range.minimum) * 180 + pulseSpan / 2) / pulseSpan;
    currentAngles[channel] = angle;
    targetAngles[channel] = angle;
    servoEnabled[channel] = true;
  }
}

void writeServoAngle(uint8_t channel, int angle) {
  if (channel >= Config::SERVO_COUNT) {
    return;
  }

  angle = constrain(angle, 0, 180);
  const Config::ServoPulseRange& range = servoPulseRanges[channel];
  const uint16_t pulse = map(
      angle,
      0,
      180,
      range.minimum,
      range.maximum);

  pwm.setPWM(channel, 0, pulse);
}

void setServoTarget(uint8_t channel, int angle) {
  if (channel >= Config::SERVO_COUNT) {
    return;
  }

  angle = constrain(angle, 0, 180);
  targetAngles[channel] = angle;

  // 第一次命令從預設零度漸進移動，避免多馬達同時瞬間跳角度的電流尖峰。
  if (!servoEnabled[channel]) {
    servoEnabled[channel] = true;
    currentAngles[channel] = Config::SERVO_START_ANGLE_DEG;
    if (currentAngles[channel] == targetAngles[channel]) {
      writeServoAngle(channel, currentAngles[channel]);
    }
  }
}

void updateServos() {
  static uint32_t lastUpdateMs = 0;
  const uint32_t now = millis();
  if (now - lastUpdateMs < Config::SERVO_UPDATE_INTERVAL_MS) {
    return;
  }
  lastUpdateMs = now;

  for (uint8_t channel = 0; channel < Config::SERVO_COUNT; ++channel) {
    if (!servoEnabled[channel] || currentAngles[channel] == targetAngles[channel]) {
      continue;
    }

    const int difference = targetAngles[channel] - currentAngles[channel];
    const int step = constrain(
        difference,
        -static_cast<int>(Config::SERVO_MAX_STEP_DEG),
        static_cast<int>(Config::SERVO_MAX_STEP_DEG));
    currentAngles[channel] += step;
    writeServoAngle(channel, currentAngles[channel]);
  }
}

class ServoCommandCallbacks final : public NimBLECharacteristicCallbacks {
  void onRead(NimBLECharacteristic* characteristic) override {
    uint8_t state[Config::SERVO_COUNT];
    for (uint8_t channel = 0; channel < Config::SERVO_COUNT; ++channel) {
      state[channel] = servoEnabled[channel] ? currentAngles[channel] : 0xFF;
    }
    characteristic->setValue(state, sizeof(state));
  }

  void onWrite(NimBLECharacteristic* characteristic) override {
    const std::string command = characteristic->getValue();

    int calibrationChannel = -1;
    unsigned int minimumPulse = 0;
    unsigned int maximumPulse = 0;
    if (sscanf(
            command.c_str(),
            "C,%d,%u,%u",
            &calibrationChannel,
            &minimumPulse,
            &maximumPulse) == 3) {
      const bool valid = calibrationChannel >= 0 &&
                         calibrationChannel < Config::SERVO_COUNT &&
                         minimumPulse <= UINT16_MAX && maximumPulse <= UINT16_MAX;
      if (!valid || !saveServoCalibration(
                        static_cast<uint8_t>(calibrationChannel),
                        static_cast<uint16_t>(minimumPulse),
                        static_cast<uint16_t>(maximumPulse))) {
        Serial.println("Invalid servo calibration");
        return;
      }
      Serial.printf(
          "Servo %d calibration -> %u..%u ticks\n",
          calibrationChannel,
          minimumPulse,
          maximumPulse);
      return;
    }

    if (command.size() == Config::SERVO_COUNT + 1 && command[0] == 'B') {
      for (uint8_t channel = 0; channel < Config::SERVO_COUNT; ++channel) {
        if (static_cast<uint8_t>(command[channel + 1]) > 180) {
          Serial.println("Binary hand command out of range");
          return;
        }
      }
      for (uint8_t channel = 0; channel < Config::SERVO_COUNT; ++channel) {
        const uint8_t angle = static_cast<uint8_t>(command[channel + 1]);
        setServoTarget(channel, angle);
      }
      return;
    }

    int channel = -1;
    int angle = -1;

    if (sscanf(command.c_str(), "S,%d,%d", &channel, &angle) != 2) {
      Serial.printf("Invalid command: %s\n", command.c_str());
      return;
    }

    if (channel < 0 || channel >= Config::SERVO_COUNT ||
        angle < 0 || angle > 180) {
      Serial.printf("Out of range: channel=%d angle=%d\n", channel, angle);
      return;
    }

    setServoTarget(static_cast<uint8_t>(channel), angle);
    Serial.printf("Servo %d target -> %d degrees\n", channel, angle);
  }
};

class ServerCallbacks final : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* server) override {
    Serial.println("BLE client connected");
  }

  void onDisconnect(NimBLEServer* server) override {
    Serial.println("BLE client disconnected; advertising restarted");
    NimBLEDevice::startAdvertising();
  }
};

void setupBle() {
  NimBLEDevice::init(Config::BLE_DEVICE_NAME);

  NimBLEServer* server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  NimBLEService* service = server->createService(Config::BLE_SERVICE_UUID);
  NimBLECharacteristic* commandCharacteristic = service->createCharacteristic(
      Config::BLE_CHARACTERISTIC_UUID,
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);

  commandCharacteristic->setCallbacks(new ServoCommandCallbacks());
  service->start();

  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();

  // BLE 4.x 每個廣播封包最多 31 bytes。完整名稱與 128-bit UUID
  // 若由函式庫自動塞入同一封包，Windows 有時只會收到「未命名裝置」。
  // 因此主廣播固定放名稱，scan response 固定放 Service UUID。
  NimBLEAdvertisementData advertisementData;
  advertisementData.setFlags(0x06);  // General discoverable + BR/EDR not supported
  advertisementData.setName(Config::BLE_DEVICE_NAME);

  NimBLEAdvertisementData scanResponseData;
  scanResponseData.setCompleteServices(NimBLEUUID(Config::BLE_SERVICE_UUID));

  advertising->setAdvertisementData(advertisementData);
  advertising->setScanResponseData(scanResponseData);
  const bool advertisingStarted = advertising->start();

  Serial.printf("BLE address: %s\n", NimBLEDevice::getAddress().toString().c_str());
  Serial.printf("BLE advertising started: %s\n", advertisingStarted ? "yes" : "NO");
}

void setup() {
  Serial.begin(115200);
  delay(300);

  Wire.begin(Config::SDA_PIN, Config::SCL_PIN);
  pwm.begin();
  pwm.setPWMFreq(Config::SERVO_FREQUENCY_HZ);
  delay(200);
  loadServoCalibration();
  restoreServoState();

  // 安全設計：開機不主動轉動馬達。
  // 僅讀回 PCA9685 已有輸出；收到有效 BLE 指令後才寫入新角度。
  setupBle();

  Serial.println();
  Serial.println("Kova-Hand firmware ready");
  Serial.println("BLE device name: Kova-Hand");
  Serial.println("Waiting for commands...");
}

void loop() {
  updateServos();

  static uint32_t lastStatusMs = 0;
  if (millis() - lastStatusMs >= 2000) {
    lastStatusMs = millis();
    Serial.printf(
        "heartbeat | advertising=%s\n",
        NimBLEDevice::getAdvertising()->isAdvertising() ? "yes" : "no");
  }
  delay(2);
}
