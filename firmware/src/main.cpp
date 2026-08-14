#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <NimBLEDevice.h>

// ============================================================
// Kova Hand：ESP32-C3 + PCA9685 + BLE 六路舵機控制器
// 單路指令：S,通道,角度\n，例如 S,0,90
// 四指同步指令：H,馬達0,馬達1,馬達2,馬達3\n，例如 H,0,45,90,180
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
constexpr uint8_t SERVO_START_ANGLE_DEG = 90;

// PCA9685 的 12-bit pulse 數值。
// 不同舵機可能需要校正；若舵機撞到機械極限，請縮小此範圍。
constexpr uint16_t SERVO_MIN_PULSE = 150;
constexpr uint16_t SERVO_MAX_PULSE = 600;

// 必須與 desktop-app/config.py 完全一致。
constexpr char BLE_DEVICE_NAME[] = "Kova-Hand";
constexpr char BLE_SERVICE_UUID[] = "19b10000-e8f2-537e-4f6c-d104768a1214";
constexpr char BLE_CHARACTERISTIC_UUID[] = "19b10001-e8f2-537e-4f6c-d104768a1214";

}  // namespace Config

Adafruit_PWMServoDriver pwm(Config::PCA9685_ADDRESS);
int currentAngles[Config::SERVO_COUNT] = {};
int targetAngles[Config::SERVO_COUNT] = {};
bool servoEnabled[Config::SERVO_COUNT] = {};

void writeServoAngle(uint8_t channel, int angle) {
  if (channel >= Config::SERVO_COUNT) {
    return;
  }

  angle = constrain(angle, 0, 180);
  const uint16_t pulse = map(
      angle,
      0,
      180,
      Config::SERVO_MIN_PULSE,
      Config::SERVO_MAX_PULSE);

  pwm.setPWM(channel, 0, pulse);
}

void setServoTarget(uint8_t channel, int angle) {
  if (channel >= Config::SERVO_COUNT) {
    return;
  }

  angle = constrain(angle, 0, 180);
  targetAngles[channel] = angle;

  // 第一次命令也從中位漸進移動，避免四指同時瞬間跳角度的電流尖峰。
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
  void onWrite(NimBLECharacteristic* characteristic) override {
    const std::string command = characteristic->getValue();

    int handAngles[4] = {};
    if (sscanf(
            command.c_str(),
            "H,%d,%d,%d,%d",
            &handAngles[0],
            &handAngles[1],
            &handAngles[2],
            &handAngles[3]) == 4) {
      for (uint8_t channel = 0; channel < 4; ++channel) {
        if (handAngles[channel] < 0 || handAngles[channel] > 180) {
          Serial.println("Hand command out of range");
          return;
        }
      }
      for (uint8_t channel = 0; channel < 4; ++channel) {
        setServoTarget(channel, handAngles[channel]);
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
      NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);

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

  // 安全設計：開機不主動轉動馬達。
  // 只有收到桌面程式的第一筆有效 BLE 指令後才輸出該通道。
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
