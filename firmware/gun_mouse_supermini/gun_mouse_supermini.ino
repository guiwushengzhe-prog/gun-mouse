// 30g 开放骨架 / SuperMini 插件载板实验固件。
//
// 交互规则（docs/固件接口与交互契约-V1.md）：
// - 触摸扳机只决定是否允许体感移动；机械扳机=左键，右键、摇杆按下=中键、摇杆移动都与触摸无关。
// - 松开触摸立即丢弃未发送的体感位移；重新触摸从新样本开始，不补发离开期间的积压。
// - 惯性芯片未就绪只停体感，不影响按键和摇杆；断线不累计，重连首帧全释放。
// - 插拔 USB 不暂停、不恢复鼠标；仅按电池节点电压估算电量，不识别外部供电或充电状态。
//
// 硬件：TENSTAR 两侧 9 针 ESP32-S3 SuperMini，ESP32-S3FH4R2（4MB Flash / 2MB QSPI PSRAM）。
// 使用 native USB CDC；USB 19/20 不接载板，GPIO3/45/46 启动配置脚不用。
// board_pins.h 由 carrier-config.json 自动生成，禁止手工改引脚。

#include <Arduino.h>
#include <Preferences.h>
#include <Wire.h>
#include <atomic>
#include <esp_system.h>

#if !ARDUINO_USB_CDC_ON_BOOT || !ARDUINO_USB_MODE
#error "Use native USB hardware CDC: CDCOnBoot=cdc,USBMode=hwcdc"
#endif

#include <BLEDevice.h>
#include <BLEHIDDevice.h>
#include <BLESecurity.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#if defined(CONFIG_NIMBLE_ENABLED)
#include <services/gatt/ble_svc_gatt.h>
#endif

#include "board_pins.h"
#include "control_core.h"
#include "imu_logic.h"
#include "input_logic.h"
#include "direction_calibration.h"
#include "ble_maintenance.h"
#include "device_status.h"

using namespace GunMouse;

namespace Fw {
constexpr char kVersion[] = "枪型飞鼠 固件3.2.5-启动原因回报";
constexpr char kBleName[] = "GunMouse SuperMini";
#if defined(CONFIG_NIMBLE_ENABLED)
constexpr char kBleStack[] = "轻量";
#elif defined(CONFIG_BLUEDROID_ENABLED)
constexpr char kBleStack[] = "传统";
#else
#error "需要启用受支持的蓝牙实现"
#endif
constexpr uint8_t kImuAddr = 0x6A;  // SA0 接地
constexpr uint32_t kI2cHz = 400000;
constexpr uint32_t kReportMinUs = 7500;
constexpr uint32_t kTouchPeriodUs = 2000;
constexpr uint32_t kJoyPeriodUs = 4000;
constexpr float kJoyDeadzone = 0.10f;
constexpr int kJoyCenterMin = 1200;
constexpr int kJoyCenterMax = 2900;
constexpr uint32_t kImuRetryMs = 2000;
constexpr uint32_t kImuNoDataUs = 250000;
constexpr uint32_t kPowerPeriodMs = 200;
constexpr uint32_t kConnectSettleMs = 400;        // 连接后等主机开始接收再发首帧
}  // namespace Fw

// ============================================================ 设置（保存在开发板非易失存储）
struct StoredSettings {
  uint32_t magic = 0x474D4131;  // "GMA1"
  float counts_per_deg = 64.0f;
  uint8_t invert_x = 0, invert_y = 0;
  float joy_speed = 1200.0f;     // 摇杆推满时每秒计数
  uint8_t joy_swap = 0, joy_invert_x = 0, joy_invert_y = 0;
  int16_t joy_min_x = 300, joy_max_x = 3800, joy_min_y = 300, joy_max_y = 3800;
  float touch_press = 0.020f, touch_release = 0.012f;
};

Preferences prefs;
StoredSettings settings;

void saveSettings() {
  prefs.putBytes("s", &settings, sizeof(settings));
}

void loadSettings() {
  StoredSettings s;
  if (prefs.getBytesLength("s") == sizeof(s) && prefs.getBytes("s", &s, sizeof(s)) == sizeof(s) &&
      s.magic == StoredSettings{}.magic) {
    settings = s;
  }
}

// ============================================================ 全局状态
ControlCore core;
ReportSender sender;
GyroPipeline gyro;
HorizontalCalibration horizontalCalibration;
BleMaintenance maintenance;
float horizontalCoupling = 0;
uint8_t horizontalCalibrationState = 0;  // 0未开始、1采集中、2成功、3动作不充分。
uint32_t horizontalCalibrationStartedMs = 0;
uint32_t lastDiagnosticMs = 0;
TouchDetector touch;
Debouncer trigDebounce, rightDebounce, middleDebounce;
JoystickAxisCal joyCalX, joyCalY;

bool imuInitialized = false;
uint32_t imuRetryMs = 0;
uint32_t imuLastGoodUs = 0;
uint64_t imuSequence = 0;

bool joystickEnabled = true;
bool joyAvailable = false;
int joyRawX = 0, joyRawY = 0;
float joyOutX = 0, joyOutY = 0;
uint32_t lastJoyUs = 0;
uint32_t joyCenterRevision = 0;
uint32_t commandSequence = 0;
char lastAcceptedCommand[16] = {};
uint32_t lastDetailsMs = 0, lastPublishedSequence = UINT32_MAX;
RuntimeStatus runtimeCurrent, runtimeLast;
uint32_t runtimeStartedMs = 0, lastLoopUs = 0;
esp_reset_reason_t startupReason = ESP_RST_UNKNOWN;

uint32_t lastTouchUs = 0;
uint32_t touchReadUs = 0;
uint8_t buttonMask = 0;
bool rawLeft = false;
uint8_t acceptedButtons = 0;
uint16_t leftPresses = 0, leftReleases = 0, acceptedLeftPresses = 0, acceptedLeftReleases = 0;

float vbatMv = NAN;
uint32_t lastPowerMs = 0;
uint8_t lastBatteryLevel = 255;
uint32_t lastBatteryReportMs = 0;

bool logEnabled = false;
uint32_t lastLogMs = 0;

// ============================================================ 蓝牙鼠标（沿用旧固件在 Windows 实测可用的无报告号 3 字节格式）
BLEServer* bleServer = nullptr;
BLEHIDDevice* hid = nullptr;
BLECharacteristic* mouseInput = nullptr;
BLE2902* mouseCccd = nullptr;
std::atomic<bool> bleConnected{false};
std::atomic<bool> mouseSubscribed{false};
std::atomic<bool> mouseNotifyAccepted{false};
std::atomic<int> mouseNotifyError{0};
std::atomic<bool> bleAuthenticated{false};
std::atomic<bool> pairingExchangedKeys{false};
std::atomic<bool> pendingSubscriptionSave{false};
std::atomic<bool> subscriptionWrittenThisConnection{false};
std::atomic<uint32_t> subscriptionWriteCount{0};
std::atomic<int> bleAuthMode{-1};
std::atomic<int> bleAuthReason{-1};
std::atomic<bool> serviceSchemaNotified{false};
portMUX_TYPE authenticatedPeerMux = portMUX_INITIALIZER_UNLOCKED;
char subscriptionKey[14] = {};
std::atomic<uint32_t> bleRevision{0};
std::atomic<uint32_t> bleIntervalUs{7500};
uint32_t seenRevision = 0;
uint32_t connectedSinceMs = 0;
uint8_t resyncStage = 0;
bool linkWasReady = false;
uint32_t linkReadyAtMs = 0;

const uint8_t kMouseDescriptor[] = {
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01,  // 通用桌面 / 鼠标 / 应用集合
    0x09, 0x01, 0xA1, 0x00,              // 指针 / 物理集合
    0x05, 0x09, 0x19, 0x01, 0x29, 0x03,  // 按键 1-3
    0x15, 0x00, 0x25, 0x01, 0x95, 0x03, 0x75, 0x01, 0x81, 0x02,
    0x95, 0x01, 0x75, 0x05, 0x81, 0x03,  // 5 位填充
    0x05, 0x01, 0x09, 0x30, 0x09, 0x31,  // X / Y 相对移动
    0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x02, 0x81, 0x06,
    0xC0, 0xC0};

class ServerCallbacks : public BLEServerCallbacks {
 public:
  void onConnect(BLEServer*) override {
    bleConnected = true;
    bleAuthenticated = false;
    pairingExchangedKeys = false;
    pendingSubscriptionSave = false;
    subscriptionWrittenThisConnection = false;
    subscriptionWriteCount = 0;
    mouseSubscribed = false;
    bleAuthMode = bleAuthReason = -1;
    bleRevision.fetch_add(1);
  }
  void onDisconnect(BLEServer*) override {
    bleConnected = false;
    bleAuthenticated = false;
    mouseSubscribed = false;
    if (mouseCccd) mouseCccd->setNotifications(false);
    bleRevision.fetch_add(1);
    bleIntervalUs = 7500;
    BLEDevice::startAdvertising();
  }
#if defined(CONFIG_BLUEDROID_ENABLED)
  void onConnect(BLEServer* server, esp_ble_gatts_cb_param_t* param) override {
    server->updateConnParams(param->connect.remote_bda, 6, 6, 0, 400);  // Arduino ESP32 3.3.2 API；请求 7.5ms
  }
#elif defined(CONFIG_NIMBLE_ENABLED)
  void onConnect(BLEServer* server, ble_gap_conn_desc* desc) override {
    bleIntervalUs = (uint32_t)desc->conn_itvl * 1250UL;
    server->updateConnParams(desc->conn_handle, 6, 6, 0, 400);
  }
  void onConnParamsUpdate(uint16_t, uint16_t interval, uint16_t, uint16_t, uint8_t status) override {
    if (status == 0 && interval >= 6) bleIntervalUs = (uint32_t)interval * 1250UL;
  }
#endif
};

class MouseSubscriptionCallbacks : public BLEDescriptorCallbacks {
 public:
  void onWrite(BLEDescriptor* descriptor) override {
    const bool subscribed = static_cast<BLE2902*>(descriptor)->getNotifications();
    subscriptionWrittenThisConnection = true;
    subscriptionWriteCount.fetch_add(1);
    if (mouseSubscribed.exchange(subscribed) != subscribed) bleRevision.fetch_add(1);
    pendingSubscriptionSave = true;
  }
};

class MouseReportCallbacks : public BLECharacteristicCallbacks {
 public:
  void onStatus(BLECharacteristic*, Status status, uint32_t code) override {
    // ESP32 core 3.3.2 的 notify() 在调用栈内报告是否被 GATT 接收；不是主机应用层确认。
    mouseNotifyAccepted = status == SUCCESS_NOTIFY;
    mouseNotifyError = status == SUCCESS_NOTIFY ? 0 : (code ? (int)code : -(int)status - 1);
  }
#if defined(CONFIG_NIMBLE_ENABLED)
  void onSubscribe(BLECharacteristic*, ble_gap_conn_desc* desc, uint16_t value) override {
    const bool subscribed = (value & 1) != 0;
    subscriptionWrittenThisConnection = true;
    subscriptionWriteCount.fetch_add(1);
    if (mouseSubscribed.exchange(subscribed) != subscribed) bleRevision.fetch_add(1);
    bleIntervalUs = (uint32_t)desc->conn_itvl * 1250UL;
  }
#endif
};

#if defined(CONFIG_NIMBLE_ENABLED)
class MouseSecurityCallbacks : public BLESecurityCallbacks {
 public:
  bool onSecurityRequest() override { return true; }
  void onAuthenticationComplete(ble_gap_conn_desc* desc, int status) override {
    bleAuthMode = desc ? ((desc->sec_state.bonded ? 1 : 0) | (desc->sec_state.authenticated ? 4 : 0)) : -1;
    bleAuthReason = status;
    bleAuthenticated = status == 0 && desc && desc->sec_state.encrypted && desc->sec_state.bonded;
    if (desc) bleIntervalUs = (uint32_t)desc->conn_itvl * 1250UL;
    if (bleAuthenticated && !serviceSchemaNotified.exchange(true)) ble_svc_gatt_changed(1, 0xffff);
  }
};
#endif

#if defined(CONFIG_BLUEDROID_ENABLED)
void onGapEvent(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t* param) {
  if (event == ESP_GAP_BLE_UPDATE_CONN_PARAMS_EVT && param->update_conn_params.status == ESP_BT_STATUS_SUCCESS &&
      param->update_conn_params.conn_int >= 6) {
    bleIntervalUs = (uint32_t)param->update_conn_params.conn_int * 1250UL;
  }
  if (event == ESP_GAP_BLE_KEY_EVT) pairingExchangedKeys = true;
  if (event == ESP_GAP_BLE_AUTH_CMPL_EVT) {
    const auto& auth = param->ble_security.auth_cmpl;
    bleAuthMode = auth.auth_mode;
    bleAuthReason = auth.success ? 0 : auth.fail_reason;
    const bool bonded = auth.success && (auth.auth_mode & ESP_LE_AUTH_BOND);
    if (bonded) {
      char key[sizeof(subscriptionKey)];
      snprintf(key, sizeof(key), "c%02x%02x%02x%02x%02x%02x", auth.bd_addr[0], auth.bd_addr[1],
               auth.bd_addr[2], auth.bd_addr[3], auth.bd_addr[4], auth.bd_addr[5]);
      // GAP/CCCD 回调由同一个 BLE 事件任务串行调用；在认证完成时恢复，后续主机写入始终优先。
      // 此处只读已初始化的 NVS；Preferences 的底层 nvs_get 使用 SDK 的 NVS 锁。
      // 主机可能在认证完成前已写入订阅；保留本次连接的真实写入。
      // 新核心也会先恢复描述符，不能再用旧的应用存储值覆盖它。
      const bool subscribed = subscriptionWrittenThisConnection.load()
                                  ? mouseSubscribed.load()
                                  : (!pairingExchangedKeys.load() &&
                                     ((mouseCccd && mouseCccd->getNotifications()) || prefs.getBool(key, false)));
      if (mouseCccd) mouseCccd->setNotifications(subscribed);
      if (mouseSubscribed.exchange(subscribed) != subscribed) bleRevision.fetch_add(1);
      portENTER_CRITICAL(&authenticatedPeerMux);
      memcpy(subscriptionKey, key, sizeof(subscriptionKey));
      portEXIT_CRITICAL(&authenticatedPeerMux);
    }
    bleAuthenticated = bonded;
  }
}
#endif

// 主机新写入的真实 CCCD 只在主循环持久化，避免在 BLE 事件任务进行 Flash 写入。
void serviceSubscriptionState() {
  if (!bleConnected || !bleAuthenticated || !mouseCccd) return;
  if (pendingSubscriptionSave.exchange(false)) {
    char key[sizeof(subscriptionKey)];
    portENTER_CRITICAL(&authenticatedPeerMux);
    memcpy(key, subscriptionKey, sizeof(key));
    portEXIT_CRITICAL(&authenticatedPeerMux);
    if (key[0]) prefs.putBool(key, mouseSubscribed.load());
  }
}

void initBle() {
  BLEDevice::init(Fw::kBleName);
  BLEDevice::setMTU(247);
#if defined(CONFIG_BLUEDROID_ENABLED)
  BLEDevice::setCustomGapHandler(onGapEvent);  // 保留实际连接间隔跟踪，不把请求值当作主机已接受值
#endif
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new ServerCallbacks());
  hid = new BLEHIDDevice(bleServer);
  hid->manufacturer()->setValue("GunMouse");
  hid->pnp(0x02, 0x303A, 0x4002, 0x0100);
  hid->hidInfo(0x00, 0x02);
  mouseInput = hid->inputReport(0);
  mouseInput->setCallbacks(new MouseReportCallbacks());
  mouseCccd = static_cast<BLE2902*>(mouseInput->getDescriptorByUUID((uint16_t)0x2902));
  if (mouseCccd) mouseCccd->setCallbacks(new MouseSubscriptionCallbacks());
  hid->reportMap((uint8_t*)kMouseDescriptor, sizeof(kMouseDescriptor));
  // 保持原鼠标服务的注册顺序和句柄，再把管理服务追加到后面。
  hid->deviceInfo()->start();
  hid->hidService()->start();
  hid->batteryService()->start();
  maintenance.begin(bleServer, &bleAuthenticated);
  bleServer->start();
  BLESecurity* security = new BLESecurity();
  security->setAuthenticationMode(ESP_LE_AUTH_BOND);
  security->setCapability(ESP_IO_CAP_NONE);
#if defined(CONFIG_NIMBLE_ENABLED)
  BLEDevice::setSecurityCallbacks(new MouseSecurityCallbacks());
#endif
  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->setAppearance(HID_MOUSE);
  adv->addServiceUUID(hid->hidService()->getUUID());
  adv->setScanResponse(true);
  adv->setMinPreferred(0x06);
  adv->setMaxPreferred(0x06);
  BLEDevice::startAdvertising();
}

bool sendReport(const HidReport& r) {
  if (!bleConnected || !mouseSubscribed || mouseInput == nullptr) return false;
  static uint32_t lastAttemptUs = 0;
  static bool lastRejected = false;
  const uint32_t nowUs = micros();
  // 受阻后给链路至少一个连接事件排空缓冲；按键仍保留在发送队列中。
  const uint32_t attemptGap = lastRejected
                                 ? std::max(ReportSender::kNotifyGapUs, bleIntervalUs.load())
                                 : ReportSender::kNotifyGapUs;
  if (lastAttemptUs && (uint32_t)(nowUs - lastAttemptUs) < attemptGap) return false;
  lastAttemptUs = nowUs;
  uint8_t data[3] = {r.buttons, (uint8_t)r.dx, (uint8_t)r.dy};
  mouseInput->setValue(data, sizeof(data));
  mouseNotifyAccepted = false;
  mouseNotifyError = 0;
  mouseInput->notify();
  const bool accepted = mouseNotifyAccepted.load();
  lastRejected = !accepted;
  if (accepted) {
    ++runtimeCurrent.reports;
    if ((r.buttons ^ acceptedButtons) & 1) {
      if (r.buttons & 1) ++acceptedLeftPresses;
      else ++acceptedLeftReleases;
    }
    acceptedButtons = r.buttons;
  }
  else {
    ++runtimeCurrent.rejected;
    runtimeCurrent.notify_error = mouseNotifyError.load();
  }
  return accepted;  // GATT 拒绝时不提交，保留点击/释放队列和位移待重试
}

uint32_t reportPeriodUs() {
  const uint32_t p = bleIntervalUs.load() / 2;
  return p < Fw::kReportMinUs ? Fw::kReportMinUs : p;
}

// ============================================================ LSM6DSV16X（寄存器设置沿用旧固件实测值）
constexpr uint8_t REG_WHO_AM_I = 0x0F, REG_CTRL1 = 0x10, REG_CTRL2 = 0x11, REG_CTRL3 = 0x12;
constexpr uint8_t REG_CTRL6 = 0x15, REG_CTRL7 = 0x16, REG_CTRL8 = 0x17, REG_STATUS = 0x1E, REG_OUTX_L_G = 0x22;
constexpr float kGyroScale = 0.00875f;  // ±250°/s
constexpr float kAccScale = 0.000122f;  // ±4g

bool writeReg(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(Fw::kImuAddr);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission(true) == 0;
}

bool readRegs(uint8_t reg, uint8_t* buf, size_t len) {
  Wire.beginTransmission(Fw::kImuAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(Fw::kImuAddr, (uint8_t)len) != len) return false;
  for (size_t i = 0; i < len; ++i) buf[i] = Wire.read();
  return true;
}

bool initImu() {
  uint8_t id = 0;
  if (!readRegs(REG_WHO_AM_I, &id, 1) || id != 0x70) return false;
  if (!writeReg(REG_CTRL3, 0x01)) return false;  // 软件复位
  for (int i = 0; i < 100; ++i) {
    delay(1);
    uint8_t c3 = 1;
    if (readRegs(REG_CTRL3, &c3, 1) && (c3 & 0x01) == 0) break;
  }
  const uint8_t setup[][2] = {{REG_CTRL3, 0x44},   // 数据块更新 + 地址自增
                              {REG_CTRL8, 0x01},   // 加速度 ±4g
                              {REG_CTRL1, 0x07},   // 加速度 240Hz（只用于静止与竖直方向判断）
                              {REG_CTRL6, 0x01},   // 陀螺仪 ±250°/s
                              {REG_CTRL7, 0x00},   // 不加额外低通，减少延迟
                              {REG_CTRL2, 0x09}};  // 陀螺仪 960Hz
  for (auto& r : setup) {
    if (!writeReg(r[0], r[1])) return false;
  }
  delay(100);
  uint8_t c1 = 0, c2 = 0, c6 = 0, c8 = 0;
  readRegs(REG_CTRL1, &c1, 1);
  readRegs(REG_CTRL2, &c2, 1);
  readRegs(REG_CTRL6, &c6, 1);
  readRegs(REG_CTRL8, &c8, 1);
  return c1 == 0x07 && c2 == 0x09 && c6 == 0x01 && c8 == 0x01;
}

// 每轮最多读一个新样本；无论是否触摸都持续读取，触摸关闭时由交互核心丢弃。
bool serviceImu(uint32_t nowUs, float& dx, float& dy) {
  dx = dy = 0;
  if (!imuInitialized) {
    if ((uint32_t)(millis() - imuRetryMs) >= Fw::kImuRetryMs) {
      imuRetryMs = millis();
      imuInitialized = initImu();
      if (imuInitialized) {
        gyro.startCalibration();
        imuLastGoodUs = micros();
        Serial.println("[传感器] 已初始化，请放稳约 3 秒完成零偏校准（按键和摇杆照常可用）");
      }
    }
    return false;
  }
  uint8_t status = 0;
  uint8_t d[12];
  const bool statusRead = readRegs(REG_STATUS, &status, 1);
  const bool dataReady = statusRead && (status & 0x02);
  const bool sampleRead = dataReady && readRegs(REG_OUTX_L_G, d, sizeof(d));
  if (!statusRead || (dataReady && !sampleRead)) ++runtimeCurrent.imu_errors;
  if (!sampleRead) {
    if ((uint32_t)(nowUs - imuLastGoodUs) > Fw::kImuNoDataUs) {
      imuInitialized = false;
      imuRetryMs = millis();
      Serial.println("[传感器] 250ms 无数据，自动重新初始化与校准");
    }
    return false;
  }
  const uint32_t sampleUs = micros();
  const uint32_t sampleGap = sampleUs - imuLastGoodUs;
  if (sampleGap > runtimeCurrent.imu_gap_max_us) runtimeCurrent.imu_gap_max_us = sampleGap;
  ++runtimeCurrent.imu_samples;
  imuLastGoodUs = sampleUs;
  auto v = [&](int i) { return (int16_t)((uint16_t)d[i + 1] << 8 | d[i]); };
  const ImuSample s{v(0) * kGyroScale, v(2) * kGyroScale, v(4) * kGyroScale,
                    v(6) * kAccScale,  v(8) * kAccScale,  v(10) * kAccScale};
  ++imuSequence;
  const bool wasCalibrated = gyro.calibrated();
  const bool produced = gyro.process(s, sampleUs, dx, dy);
  if (produced && horizontalCalibrationState == 1) {
    const Vec3 r = gyro.uncorrectedRates();
    horizontalCalibration.observe(r.x, r.y, 1.0f / GyroPipeline::kOdrHz);
  }
  if (!wasCalibrated && gyro.calibrated()) {
    const Vec3 b = gyro.bias(), n = gyro.noise(), u = gyro.up();
    Serial.printf("[校准] 零偏 %+.4f %+.4f %+.4f °/s，噪声 %.4f %.4f %.4f，竖直方向(芯片) %+.2f %+.2f %+.2f\n",
                  b.x, b.y, b.z, n.x, n.y, n.z, u.x, u.y, u.z);
  }
  return produced;
}

// ============================================================ 摇杆
int readAdcAvg(int pin, int n) {
  int sum = 0;
  for (int i = 0; i < n; ++i) sum += analogRead(pin);
  return sum / n;
}

void calibrateJoystickCenter() {
  ++joyCenterRevision;
  lastJoyUs = 0;
  joyOutX = joyOutY = 0;
  sender.clearJoystick();
  if (!joystickEnabled) {
    joyAvailable = false;
    joyRawX = joyRawY = 0;
    Serial.println("[摇杆] 已停用，装回后输入 joy 1 恢复");
    return;
  }
  const int cx = readAdcAvg(Pins::JOY_X, 32);
  const int cy = readAdcAvg(Pins::JOY_Y, 32);
  joyRawX = cx;
  joyRawY = cy;
  joyAvailable = cx >= Fw::kJoyCenterMin && cx <= Fw::kJoyCenterMax && cy >= Fw::kJoyCenterMin &&
                 cy <= Fw::kJoyCenterMax;
  joyCalX = {cx, settings.joy_min_x, settings.joy_max_x};
  joyCalY = {cy, settings.joy_min_y, settings.joy_max_y};
  Serial.printf("[摇杆] 中心 X=%d Y=%d %s\n", cx, cy, joyAvailable ? "正常" : "偏离中位，暂停摇杆（输入 jcenter 重新取中）");
}

// 返回本轮摇杆位移（计数）；回中时清摇杆余量。
bool serviceJoystick(uint32_t nowUs, float& mx, float& my) {
  mx = my = 0;
  if (!joyAvailable) return false;
  if (lastJoyUs == 0) { lastJoyUs = nowUs; return false; }
  const uint32_t elapsed = nowUs - lastJoyUs;
  if (elapsed < Fw::kJoyPeriodUs) return false;
  lastJoyUs = nowUs;
  joyRawX = readAdcAvg(Pins::JOY_X, 2);
  joyRawY = readAdcAvg(Pins::JOY_Y, 2);
  joyCalX.observe(joyRawX);
  joyCalY.observe(joyRawY);
  float x = joyCalX.normalize(joyRawX);
  float y = joyCalY.normalize(joyRawY);
  if (settings.joy_swap) { const float t = x; x = y; y = t; }
  if (settings.joy_invert_x) x = -x;
  if (settings.joy_invert_y) y = -y;
  if (!shapeJoystick(x, y, Fw::kJoyDeadzone, joyOutX, joyOutY)) {
    sender.clearJoystick();
    return false;
  }
  if (elapsed > 50000UL) return false;  // 长停顿后不补发
  const float dt = elapsed * 1e-6f;
  mx = joyOutX * settings.joy_speed * dt;
  my = joyOutY * settings.joy_speed * dt;
  return true;
}

// ============================================================ 触摸与按键
void serviceTouch(uint32_t nowUs) {
  if ((uint32_t)(nowUs - lastTouchUs) < Fw::kTouchPeriodUs) return;
  lastTouchUs = nowUs;
  const uint32_t t0 = micros();
  const uint32_t raw = touchRead(Pins::TOUCH);
  touchReadUs = micros() - t0;
  touch.update(raw, micros());
}

void serviceButtons(uint32_t nowUs) {
  uint8_t mask = 0;
  rawLeft = digitalRead(Pins::TRIG) == LOW;
  if (trigDebounce.update(rawLeft, nowUs)) mask |= 0x01;   // 机械扳机 = 左键
  if (rightDebounce.update(digitalRead(Pins::BTN_R) == LOW, nowUs)) mask |= 0x02; // 右键
  if (middleDebounce.update(joystickEnabled && digitalRead(Pins::JOY_SW) == LOW, nowUs)) mask |= 0x04; // 摇杆按下 = 中键
  if ((mask ^ buttonMask) & 1) {
    if (mask & 1) ++leftPresses;
    else ++leftReleases;
  }
  buttonMask = mask;
}

// ============================================================ 电源
void servicePower() {
  const uint32_t nowMs = millis();
  if ((uint32_t)(nowMs - lastPowerMs) < Fw::kPowerPeriodMs) return;
  lastPowerMs = nowMs;
  const float vbat = analogReadMilliVolts(Pins::VBAT_ADC) * 2.0f;
  vbatMv = std::isnan(vbatMv) ? vbat : vbatMv + 0.05f * (vbat - vbatMv);  // 约 4 秒平滑
  // 无外部供电反馈：每分钟最多更新一次估算电量，充电或电池开关关闭时可能偏高。
  if (hid && ((uint32_t)(nowMs - lastBatteryReportMs) >= 60000 || lastBatteryLevel == 255)) {
    const uint8_t level = batteryPercentFromMillivolts(vbatMv);
    lastBatteryReportMs = nowMs;
    if (level != lastBatteryLevel) {
      lastBatteryLevel = level;
      hid->setBatteryLevel(level);
    }
  }
}

// ============================================================ 串口命令（SuperMini 自身 Type-C 原生 USB）
void applySettings() {
  GyroPipeline::Settings gs;
  gs.counts_per_deg = settings.counts_per_deg;
  gs.invert_x = settings.invert_x;
  gs.invert_y = settings.invert_y;
  gs.horizontal_coupling = horizontalCoupling;
  gyro.setSettings(gs);
  TouchDetector::Settings ts = touch.settings();
  ts.press_ratio = settings.touch_press;
  ts.release_ratio = settings.touch_release;
  touch.setSettings(ts);
}

void printStatus() {
  const Vec3 u = gyro.up();
  Serial.printf("[启动原因] 代码=%u 运行=%lums\n", (unsigned)startupReason, (unsigned long)millis());
  Serial.printf("[状态] %s | 蓝牙=%s 报告订阅=%s 间隔=%.2fms | 陀螺仪=%s 竖直(芯片)=%+.2f %+.2f %+.2f\n", Fw::kVersion,
                bleConnected ? "已连接" : "等待连接", mouseSubscribed ? "已启用" : "等待主机", bleIntervalUs.load() / 1000.0f,
                !imuInitialized ? "未找到芯片(自动重试)" : (gyro.calibrated() ? "正常" : "等待放稳校准"), u.x, u.y,
                u.z);
  Serial.printf("[体感方向] 上下保留镜像 左右串轴校正=%+.5f（约%+.1f度） 校准状态=%u\n",
                horizontalCoupling, std::atan(horizontalCoupling) * 180.0f / 3.14159265f,
                (unsigned)horizontalCalibrationState);
  Serial.printf("[无线升级] 当前分区=%s 蓝牙升级入口已启用\n", esp_ota_get_running_partition()->label);
  Serial.printf("[蓝牙链路] 实现=%s 配对认证=%s 模式=%d 失败码=%d 主机订阅写入=%lu 描述符开关=%d\n",
                Fw::kBleStack, bleAuthenticated ? "通过" : "未通过", bleAuthMode.load(), bleAuthReason.load(),
                (unsigned long)subscriptionWriteCount.load(), mouseCccd ? (int)mouseCccd->getNotifications() : -1);
  Serial.printf("[状态] 触摸 原始=%lu 基线=%.0f 噪声=%.1f 门限=+%.0f/+%.0f 状态=%s 读一次=%luus\n",
                (unsigned long)touch.lastRaw(), touch.baseline(), touch.noise(), touch.pressOffset(),
                touch.releaseOffset(), touch.touched() ? "触摸" : "未触摸", (unsigned long)touchReadUs);
  Serial.printf("[状态] 按键 左(扳机)=%d 右=%d 中=%d | 摇杆 %s ADC=(%d,%d) 中心=(%d,%d) 端点X=[%d,%d] Y=[%d,%d] 输出=(%+.2f,%+.2f)\n",
                buttonMask & 1, (buttonMask >> 1) & 1, (buttonMask >> 2) & 1,
                !joystickEnabled ? "已停用" : (joyAvailable ? "正常" : "暂停"), joyRawX,
                joyRawY, joyCalX.center, joyCalY.center, joyCalX.min, joyCalX.max, joyCalY.min, joyCalY.max, joyOutX,
                joyOutY);
  Serial.printf("[状态] BAT_SW/B+=%.0fmV(仅BAT开关ON代表电池；电量为电压估算，充电时可能偏高) | 灵敏度=%.1f计数/度 反向X=%d Y=%d | 摇杆速度=%.0f 交换=%d 反向X=%d Y=%d\n",
                vbatMv, settings.counts_per_deg, settings.invert_x,
                settings.invert_y, settings.joy_speed, settings.joy_swap, settings.joy_invert_x, settings.joy_invert_y);
}

void printHelp() {
  Serial.println(
      "命令：status 状态 | log 开关每秒5次状态 | cal 重新校准陀螺仪 | sens <计数/度> | invx / invy 体感反向\n"
      "      joy 0/1 停用/启用摇杆及中键（自动保存） | jcenter 摇杆重新取中 | jdir 摇杆方向向导\n"
      "      jspeed <计数/秒> | jsave 保存摇杆端点\n"
      "      tp <百分比> 触摸按下门限 | tr <百分比> 触摸松开门限 | tcal 握持未触摸时重新取基线\n"
      "      hcal 正常握持左右往返6秒校准串轴 | hcross <系数> 设置横向串轴 | reset 恢复默认设置 | help");
}

void serviceHorizontalCalibration() {
  if (horizontalCalibrationState != 1 || (uint32_t)(millis() - horizontalCalibrationStartedMs) < 6000) return;
  float result = horizontalCoupling;
  if (horizontalCalibration.finish(result)) {
    horizontalCoupling = result;
    prefs.putFloat("hcross", horizontalCoupling);
    applySettings();
    horizontalCalibrationState = 2;
    Serial.printf("[左右校准] 已保存串轴系数%+.5f，上下映射保留\n", horizontalCoupling);
  } else {
    horizontalCalibrationState = 3;
    Serial.println("[左右校准] 动作不足或不是一致的左右往返，保留之前设置");
  }
}

void publishMaintenanceDiagnostic() {
  if ((uint32_t)(millis() - lastDiagnosticMs) < 50) return;
  lastDiagnosticMs = millis();
  const Vec3 up = gyro.up();
  char text[300];
  snprintf(text, sizeof(text),
           "{\"fw\":3,\"build\":\"3.2.5\",\"invx\":%u,\"invy\":%u,\"hcal\":%u,\"cross\":%.5f,\"touch\":%u,\"ready\":%u,\"raw\":%lu,"
           "\"base\":%.1f,\"noise\":%.1f,\"tp\":%.4f,\"tr\":%.4f,\"up\":[%.3f,%.3f,%.3f]}",
           (unsigned)settings.invert_x, (unsigned)settings.invert_y,
           (unsigned)horizontalCalibrationState, horizontalCoupling, (unsigned)touch.touched(),
           (unsigned)touch.ready(), (unsigned long)touch.lastRaw(), touch.baseline(), touch.noise(),
           settings.touch_press, settings.touch_release, up.x, up.y, up.z);
  maintenance.setDiagnostic(text);
}

void publishDeviceDetails() {
  const uint32_t now = millis();
  if ((uint32_t)(now - lastDetailsMs) < 200 && commandSequence == lastPublishedSequence) return;
  lastDetailsMs = now;
  lastPublishedSequence = commandSequence;
  DeviceStatus snapshot;
  snapshot.joy_enabled = joystickEnabled;
  snapshot.joy_ready = joyAvailable;
  snapshot.raw_x = joyRawX; snapshot.raw_y = joyRawY;
  snapshot.center_x = joyCalX.center; snapshot.center_y = joyCalY.center;
  snapshot.joy_speed = settings.joy_speed;
  snapshot.sensitivity = settings.counts_per_deg;
  snapshot.center_revision = joyCenterRevision;
  snapshot.middle = (buttonMask & 4) != 0;
  snapshot.imu_ready = imuInitialized && gyro.calibrated();
  snapshot.node_mv = std::isfinite(vbatMv) ? (int)std::lround(vbatMv) : -1;
  snapshot.command_sequence = commandSequence;
  snapshot.command = lastAcceptedCommand;
  snapshot.uptime_ms = millis();
  snapshot.reset_reason = (uint8_t)startupReason;
  snapshot.runtime = runtimeLast;
  snapshot.runtime.link_us = bleIntervalUs.load();
  snapshot.buttons.raw_left = rawLeft;
  snapshot.buttons.observed = buttonMask;
  snapshot.buttons.accepted = acceptedButtons;
  snapshot.buttons.presses = leftPresses; snapshot.buttons.releases = leftReleases;
  snapshot.buttons.accepted_presses = acceptedLeftPresses;
  snapshot.buttons.accepted_releases = acceptedLeftReleases;
  snapshot.buttons.queued = sender.queued();
  snapshot.buttons.overflows = sender.buttonOverflows();
  char text[512];
  if (formatDeviceStatus(snapshot, text, sizeof(text))) maintenance.setDetails(text);
  else maintenance.setDetails("{\"project\":\"gunmouse\",\"error\":\"report_overflow\"}");
}

// 摇杆方向向导：依次推向“光标向右”和“光标向上”的方向，自动确定交换与反向。
void joystickDirectionWizard() {
  if (!joystickEnabled) {
    Serial.println("[摇杆] 已停用，装回后输入 joy 1 恢复");
    return;
  }
  settings.joy_swap = settings.joy_invert_x = settings.joy_invert_y = 0;
  auto capture = [](const char* what, float& ax, float& ay) {
    Serial.printf("[摇杆] 请把摇杆推到底并保持在“%s”的方向（5 秒内）…\n", what);
    ax = ay = 0;
    const uint32_t start = millis();
    while ((uint32_t)(millis() - start) < 5000) {
      const float x = joyCalX.normalize(readAdcAvg(Pins::JOY_X, 4));
      const float y = joyCalY.normalize(readAdcAvg(Pins::JOY_Y, 4));
      if (std::fabs(x) + std::fabs(y) > std::fabs(ax) + std::fabs(ay)) { ax = x; ay = y; }
      delay(10);
    }
    return std::fabs(ax) > 0.6f || std::fabs(ay) > 0.6f;
  };
  float rx, ry, ux, uy;
  if (!capture("光标向右", rx, ry) || !capture("光标向上", ux, uy)) {
    Serial.println("[摇杆] 没有检测到足够的推动，向导取消");
    return;
  }
  const bool swap = std::fabs(ry) > std::fabs(rx);
  settings.joy_swap = swap;
  const float right = swap ? ry : rx;
  const float up = swap ? ux : uy;
  settings.joy_invert_x = right < 0;
  settings.joy_invert_y = up > 0;  // 鼠标向上为负
  saveSettings();
  Serial.printf("[摇杆] 已保存：交换=%d 反向X=%d 反向Y=%d\n", settings.joy_swap, settings.joy_invert_x,
                settings.joy_invert_y);
}

void executeCommand(const char* line) {
    char cmd[16] = {0};
    float value = NAN;
    const int n = sscanf(line, "%15s %f", cmd, &value);
    if (n < 1) return;
    const String c2(cmd);
    if (c2 == "status") printStatus();
    else if (c2 == "help") printHelp();
    else if (c2 == "log") { logEnabled = !logEnabled; Serial.printf("[日志] %s\n", logEnabled ? "开" : "关"); }
    else if (c2 == "cal") { gyro.startCalibration(); Serial.println("[校准] 请放稳约 3 秒"); }
    else if (c2 == "sens" && n == 2 && value > 0 && value < 1000) { settings.counts_per_deg = value; }
    else if (c2 == "invx") settings.invert_x ^= 1;
    else if (c2 == "invy") settings.invert_y ^= 1;
    else if (c2 == "tcal") {
      touch.begin(micros());
      Serial.println("[触摸校准] 保持正常握持但别碰触摸片，约0.4秒后基线就绪");
    }
    else if (c2 == "hcal") {
      if (!gyro.calibrated()) { Serial.println("[左右校准] 请先放稳完成陀螺仪校准"); return; }
      horizontalCalibration.begin();
      horizontalCalibrationState = 1;
      horizontalCalibrationStartedMs = millis();
      Serial.println("[左右校准] 按正常握姿水平左右来回转6秒，期间只暂停体感位移");
    }
    else if (c2 == "hcross" && n == 2 && std::isfinite(value) && std::fabs(value) <= 2) {
      horizontalCoupling = value;
      prefs.putFloat("hcross", horizontalCoupling);
    }
    else if (c2 == "joy" && n == 2 && (value == 0 || value == 1)) {
      joystickEnabled = value == 1;
      prefs.putBool("joystick", joystickEnabled);
      calibrateJoystickCenter();
    }
    else if (c2 == "jcenter") calibrateJoystickCenter();
    else if (c2 == "jdir") joystickDirectionWizard();
    else if (c2 == "jspeed" && n == 2 && value > 0 && value < 20000) settings.joy_speed = value;
    else if (c2 == "jsave") {
      settings.joy_min_x = joyCalX.min; settings.joy_max_x = joyCalX.max;
      settings.joy_min_y = joyCalY.min; settings.joy_max_y = joyCalY.max;
    }
    else if (c2 == "tp" && n == 2 && value > 0.1f && value < 50) settings.touch_press = value / 100.0f;
    else if (c2 == "tr" && n == 2 && value > 0.05f && value < 50) settings.touch_release = value / 100.0f;
    else if (c2 == "reset") {
      settings = StoredSettings{};
      horizontalCoupling = 0;
      prefs.putFloat("hcross", 0);
      Serial.println("[设置] 已恢复默认");
    }
    else { Serial.printf("[命令] 无法识别：%s（输入 help）\n", line); return; }
    if (settings.touch_release >= settings.touch_press) settings.touch_release = settings.touch_press * 0.6f;
    applySettings();
    if (c2 != "status" && c2 != "help" && c2 != "log") saveSettings();
    snprintf(lastAcceptedCommand, sizeof(lastAcceptedCommand), "%s", cmd);
    ++commandSequence;
    if (c2 != "status" && c2 != "help" && c2 != "log") printStatus();
}

void handleSerial() {
  static char line[64];
  static int len = 0;
  while (Serial.available()) {
    const char c = (char)Serial.read();
    if (c != '\n' && c != '\r') {
      if (len < (int)sizeof(line) - 1) line[len++] = c;
      continue;
    }
    if (!len) continue;
    line[len] = 0;
    len = 0;
    executeCommand(line);
  }
}

// ============================================================ 主流程
void setup() {
  startupReason = esp_reset_reason();
  setCpuFrequencyMhz(160);
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);  // 没接电脑时不阻塞
  pinMode(Pins::TRIG, INPUT_PULLUP);  // 扳机保留外部上拉；右键和摇杆按键使用内部上拉
  pinMode(Pins::BTN_R, INPUT_PULLUP);
  pinMode(Pins::JOY_SW, INPUT_PULLUP);
  analogReadResolution(12);
  analogSetPinAttenuation(Pins::JOY_X, ADC_11db);
  analogSetPinAttenuation(Pins::JOY_Y, ADC_11db);
  analogSetPinAttenuation(Pins::VBAT_ADC, ADC_11db);
  prefs.begin("gunmouse", false);
  loadSettings();
  horizontalCoupling = prefs.getFloat("hcross", 0);
  if (!std::isfinite(horizontalCoupling) || std::fabs(horizontalCoupling) > 2) horizontalCoupling = 0;
  joystickEnabled = prefs.getBool("joystick", true);
  applySettings();
  Wire.begin(Pins::SDA, Pins::SCL, Fw::kI2cHz);
  Wire.setTimeOut(5);
  delay(50);
  Serial.printf("\n[启动] %s，体感需触摸扳机才移动；插拔 USB 不影响鼠标\n", Fw::kVersion);
  calibrateJoystickCenter();
  touch.begin(micros());
  imuRetryMs = millis() - Fw::kImuRetryMs;
  initBle();
  Serial.printf("[蓝牙] 等待连接：%s\n", Fw::kBleName);
  printHelp();
}

void loop() {
  const uint32_t loopUs = micros();
  if (lastLoopUs) {
    const uint32_t gap = loopUs - lastLoopUs;
    if (gap > runtimeCurrent.loop_max_us) runtimeCurrent.loop_max_us = gap;
  }
  lastLoopUs = loopUs;
  const uint32_t runtimeMs = millis();
  if ((uint32_t)(runtimeMs - runtimeStartedMs) >= 1000) {
    runtimeCurrent.window_ms = runtimeMs - runtimeStartedMs;
    runtimeLast = runtimeCurrent;
    runtimeCurrent = RuntimeStatus{};
    runtimeStartedMs = runtimeMs;
  }
  handleSerial();
  maintenance.service(bleConnected && bleAuthenticated, executeCommand);
  serviceHorizontalCalibration();
  serviceSubscriptionState();
  const uint32_t now = micros();

  float imuDx = 0, imuDy = 0;
  const bool imuMoved = serviceImu(now, imuDx, imuDy);
  serviceTouch(now);
  serviceButtons(now);
  float joyDx = 0, joyDy = 0;
  const bool joyMoved = serviceJoystick(now, joyDx, joyDy);

  // 连接状态：回调只改标志；两轮之间若发生断开再连接，先让核心看到一次断开。
  const uint32_t revision = bleRevision.load();
  if (revision != seenRevision) {
    seenRevision = revision;
    core.setInputs(false, false, false, 0, imuSequence);
    sender.absorb(core.takeReport());
    connectedSinceMs = millis();
    resyncStage = 0;
  }
  const bool linkReady = bleConnected && bleAuthenticated && mouseSubscribed &&
                         (uint32_t)(millis() - connectedSinceMs) >= Fw::kConnectSettleMs;
  const bool imuReady = imuInitialized && gyro.calibrated();
  const bool updating = maintenance.active();
  core.setInputs(linkReady, touch.touched() && horizontalCalibrationState != 1 && !updating,
                 imuReady, updating ? 0 : buttonMask, imuSequence);
  if (imuMoved) core.offerImu(imuSequence, imuDx, imuDy);
  if (joyMoved && !updating) core.offerJoystick(joyDx, joyDy);
  sender.absorb(core.takeReport());

  // 连接就绪后 100ms、300ms 各重发一次当前按键状态，防止主机刚开始接收时漏掉。
  if (linkReady && !linkWasReady) {
    linkReadyAtMs = millis();
    resyncStage = 0;
  }
  linkWasReady = linkReady;
  if (linkReady && resyncStage < 2 && (uint32_t)(millis() - linkReadyAtMs) >= (resyncStage == 0 ? 100u : 300u)) {
    sender.resendButtons();
    ++resyncStage;
  }

  HidReport report;
  const uint32_t sendNow = micros();
  if (sender.prepare(sendNow, reportPeriodUs(), report) && sendReport(report)) sender.commit(sendNow);

  servicePower();
  publishMaintenanceDiagnostic();
  publishDeviceDetails();
  if (logEnabled && (uint32_t)(millis() - lastLogMs) >= 200) {
    lastLogMs = millis();
    printStatus();
  }
}
