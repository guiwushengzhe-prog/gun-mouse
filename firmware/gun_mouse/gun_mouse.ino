// 枪型飞鼠正式板（PCB-Shell-V1 / EVT-A）固件
//
// 交互规则（docs/固件接口与交互契约-V1.md）：
// - 触摸扳机只决定是否允许体感移动；机械扳机=左键，右键、摇杆按下=中键、摇杆移动都与触摸无关。
// - 松开触摸立即丢弃未发送的体感位移；重新触摸从新样本开始，不补发离开期间的积压。
// - 惯性芯片未就绪只停体感，不影响按键和摇杆；断线不累计，重连首帧全释放。
// - 插拔 USB 不暂停、不恢复鼠标；USB 检测只用于状态显示与电量判断。
//
// 硬件：YD-ESP32-S3 N16R8 开发板插在主板上，由主板 3.3V 供电；引脚由 board_pins.h 给出。

#include <Arduino.h>
#include <Preferences.h>
#include <Wire.h>
#include <atomic>
#include <esp_sleep.h>

#include <BLEDevice.h>
#include <BLEHIDDevice.h>
#include <BLESecurity.h>
#include <BLEServer.h>
#include <BLEUtils.h>

#include "board_pins.h"
#include "control_core.h"
#include "imu_logic.h"
#include "input_logic.h"

using namespace GunMouse;

namespace Fw {
constexpr char kVersion[] = "EVT-A 固件 1";
constexpr char kBleName[] = "GunMouse EVT-A";
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
constexpr float kLowBatteryMv = 3300.0f;          // 低于此值且未插 USB 持续 30 秒，进入深睡保护电池
constexpr uint32_t kLowBatteryHoldMs = 30000;
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
TouchDetector touch;
UsbDetector usbDetector;
Debouncer trigDebounce, rightDebounce, middleDebounce;
JoystickAxisCal joyCalX, joyCalY;

bool imuInitialized = false;
uint32_t imuRetryMs = 0;
uint32_t imuLastGoodUs = 0;
uint64_t imuSequence = 0;

bool joyAvailable = false;
int joyRawX = 0, joyRawY = 0;
float joyOutX = 0, joyOutY = 0;
uint32_t lastJoyUs = 0;

uint32_t lastTouchUs = 0;
uint32_t touchReadUs = 0;
uint8_t buttonMask = 0;

float vbatMv = NAN;
float vbusMv = NAN;
bool usbPresent = false;
uint32_t lowBatterySinceMs = 0;
uint32_t lastPowerMs = 0;
uint8_t lastBatteryLevel = 255;
uint32_t lastBatteryReportMs = 0;

bool logEnabled = false;
uint32_t lastLogMs = 0;

// ============================================================ 蓝牙鼠标（沿用旧固件在 Windows 实测可用的无报告号 3 字节格式）
BLEServer* bleServer = nullptr;
BLEHIDDevice* hid = nullptr;
BLECharacteristic* mouseInput = nullptr;
std::atomic<bool> bleConnected{false};
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
    bleRevision.fetch_add(1);
  }
  void onDisconnect(BLEServer*) override {
    bleConnected = false;
    bleRevision.fetch_add(1);
    bleIntervalUs = 7500;
    BLEDevice::startAdvertising();
  }
#if defined(CONFIG_BLUEDROID_ENABLED)
  void onConnect(BLEServer* server, esp_ble_gatts_cb_param_t* param) override {
    server->requestConnParams(param->connect.remote_bda, 6, 6, 0, 400);  // 请求 7.5ms 连接间隔
  }
  void onConnParamsUpdate(esp_bd_addr_t, uint16_t interval, uint16_t, uint16_t, esp_bt_status_t status) override {
    if (status == ESP_BT_STATUS_SUCCESS && interval >= 6) bleIntervalUs = (uint32_t)interval * 1250UL;
  }
#endif
};

void initBle() {
  BLEDevice::init(Fw::kBleName);
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new ServerCallbacks());
  hid = new BLEHIDDevice(bleServer);
  hid->manufacturer()->setValue("GunMouse");
  hid->pnp(0x02, 0x303A, 0x4002, 0x0100);
  hid->hidInfo(0x00, 0x02);
  mouseInput = hid->inputReport(0);
  hid->reportMap((uint8_t*)kMouseDescriptor, sizeof(kMouseDescriptor));
  hid->startServices();
  BLESecurity* security = new BLESecurity();
  security->setAuthenticationMode(ESP_LE_AUTH_BOND);
  security->setCapability(ESP_IO_CAP_NONE);
  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->setAppearance(HID_MOUSE);
  adv->addServiceUUID(hid->hidService()->getUUID());
  adv->setScanResponse(true);
  adv->setMinPreferred(0x06);
  adv->setMaxPreferred(0x06);
  BLEDevice::startAdvertising();
}

bool sendReport(const HidReport& r) {
  if (!bleConnected || mouseInput == nullptr) return false;
  uint8_t data[3] = {r.buttons, (uint8_t)r.dx, (uint8_t)r.dy};
  mouseInput->setValue(data, sizeof(data));
  mouseInput->notify();
  return true;
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
  if (!readRegs(REG_STATUS, &status, 1) || !(status & 0x02) || !readRegs(REG_OUTX_L_G, d, sizeof(d))) {
    if ((uint32_t)(nowUs - imuLastGoodUs) > Fw::kImuNoDataUs) {
      imuInitialized = false;
      imuRetryMs = millis();
      Serial.println("[传感器] 250ms 无数据，自动重新初始化与校准");
    }
    return false;
  }
  const uint32_t sampleUs = micros();
  imuLastGoodUs = sampleUs;
  auto v = [&](int i) { return (int16_t)((uint16_t)d[i + 1] << 8 | d[i]); };
  const ImuSample s{v(0) * kGyroScale, v(2) * kGyroScale, v(4) * kGyroScale,
                    v(6) * kAccScale,  v(8) * kAccScale,  v(10) * kAccScale};
  ++imuSequence;
  const bool wasCalibrated = gyro.calibrated();
  const bool produced = gyro.process(s, sampleUs, dx, dy);
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
  const int cx = readAdcAvg(Pins::JOY_X, 32);
  const int cy = readAdcAvg(Pins::JOY_Y, 32);
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
  if (trigDebounce.update(digitalRead(Pins::TRIG) == LOW, nowUs)) mask |= 0x01;   // 机械扳机 = 左键
  if (rightDebounce.update(digitalRead(Pins::BTN_R) == LOW, nowUs)) mask |= 0x02; // 右键
  if (middleDebounce.update(digitalRead(Pins::JOY_SW) == LOW, nowUs)) mask |= 0x04; // 摇杆按下 = 中键
  buttonMask = mask;
}

// ============================================================ 电源
void servicePower() {
  const uint32_t nowMs = millis();
  if ((uint32_t)(nowMs - lastPowerMs) < Fw::kPowerPeriodMs) return;
  lastPowerMs = nowMs;
  const float vbat = analogReadMilliVolts(Pins::VBAT_ADC) * 2.0f;
  vbusMv = analogReadMilliVolts(Pins::VBUS_DET) * 2.0f;
  usbPresent = usbDetector.updateMillivolts(vbusMv / 2.0f);
  vbatMv = std::isnan(vbatMv) ? vbat : vbatMv + 0.05f * (vbat - vbatMv);  // 约 4 秒平滑
  if (!usbPresent && vbatMv < Fw::kLowBatteryMv) {
    if (!lowBatterySinceMs) lowBatterySinceMs = nowMs;
    if ((uint32_t)(nowMs - lowBatterySinceMs) >= Fw::kLowBatteryHoldMs) {
      Serial.printf("[电源] 电池 %.0f mV，进入深睡保护电池；按扳机或插 USB 后 10 分钟内唤醒检查\n", vbatMv);
      Serial.flush();
      esp_sleep_enable_ext0_wakeup((gpio_num_t)Pins::TRIG, 0);
      esp_sleep_enable_timer_wakeup(600ULL * 1000000ULL);
      esp_deep_sleep_start();
    }
  } else {
    lowBatterySinceMs = 0;
  }
  // 充电时电压偏高，不更新电量；未插 USB 时每分钟最多更新一次。
  if (hid && !usbPresent && ((uint32_t)(nowMs - lastBatteryReportMs) >= 60000 || lastBatteryLevel == 255)) {
    const uint8_t level = batteryPercentFromMillivolts(vbatMv);
    lastBatteryReportMs = nowMs;
    if (level != lastBatteryLevel) {
      lastBatteryLevel = level;
      hid->setBatteryLevel(level);
    }
  }
}

// ============================================================ 串口命令（底部 Type-C 原生 USB）
void applySettings() {
  GyroPipeline::Settings gs;
  gs.counts_per_deg = settings.counts_per_deg;
  gs.invert_x = settings.invert_x;
  gs.invert_y = settings.invert_y;
  gyro.setSettings(gs);
  TouchDetector::Settings ts = touch.settings();
  ts.press_ratio = settings.touch_press;
  ts.release_ratio = settings.touch_release;
  touch.setSettings(ts);
}

void printStatus() {
  const Vec3 u = gyro.up();
  Serial.printf("[状态] %s | 蓝牙=%s 间隔=%.2fms | 陀螺仪=%s 竖直(芯片)=%+.2f %+.2f %+.2f\n", Fw::kVersion,
                bleConnected ? "已连接" : "等待连接", bleIntervalUs.load() / 1000.0f,
                !imuInitialized ? "未找到芯片(自动重试)" : (gyro.calibrated() ? "正常" : "等待放稳校准"), u.x, u.y,
                u.z);
  Serial.printf("[状态] 触摸 原始=%lu 基线=%.0f 噪声=%.1f 门限=+%.0f/+%.0f 状态=%s 读一次=%luus\n",
                (unsigned long)touch.lastRaw(), touch.baseline(), touch.noise(), touch.pressOffset(),
                touch.releaseOffset(), touch.touched() ? "触摸" : "未触摸", (unsigned long)touchReadUs);
  Serial.printf("[状态] 按键 左(扳机)=%d 右=%d 中=%d | 摇杆 %s ADC=(%d,%d) 中心=(%d,%d) 端点X=[%d,%d] Y=[%d,%d] 输出=(%+.2f,%+.2f)\n",
                buttonMask & 1, (buttonMask >> 1) & 1, (buttonMask >> 2) & 1, joyAvailable ? "正常" : "暂停", joyRawX,
                joyRawY, joyCalX.center, joyCalY.center, joyCalX.min, joyCalX.max, joyCalY.min, joyCalY.max, joyOutX,
                joyOutY);
  Serial.printf("[状态] 电池=%.0fmV USB=%s(%.0fmV) | 灵敏度=%.1f计数/度 反向X=%d Y=%d | 摇杆速度=%.0f 交换=%d 反向X=%d Y=%d\n",
                vbatMv, usbPresent ? "已插" : "未插", vbusMv, settings.counts_per_deg, settings.invert_x,
                settings.invert_y, settings.joy_speed, settings.joy_swap, settings.joy_invert_x, settings.joy_invert_y);
}

void printHelp() {
  Serial.println(
      "命令：status 状态 | log 开关每秒5次状态 | cal 重新校准陀螺仪 | sens <计数/度> | invx / invy 体感反向\n"
      "      jcenter 摇杆重新取中 | jdir 摇杆方向向导 | jspeed <计数/秒> | jsave 保存摇杆端点\n"
      "      tp <百分比> 触摸按下门限 | tr <百分比> 触摸松开门限 | reset 恢复默认设置 | help");
}

// 摇杆方向向导：依次推向“光标向右”和“光标向上”的方向，自动确定交换与反向。
void joystickDirectionWizard() {
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
    char cmd[16] = {0};
    float value = NAN;
    const int n = sscanf(line, "%15s %f", cmd, &value);
    if (n < 1) continue;
    const String c2(cmd);
    if (c2 == "status") printStatus();
    else if (c2 == "help") printHelp();
    else if (c2 == "log") { logEnabled = !logEnabled; Serial.printf("[日志] %s\n", logEnabled ? "开" : "关"); }
    else if (c2 == "cal") { gyro.startCalibration(); Serial.println("[校准] 请放稳约 3 秒"); }
    else if (c2 == "sens" && n == 2 && value > 0 && value < 1000) { settings.counts_per_deg = value; }
    else if (c2 == "invx") settings.invert_x ^= 1;
    else if (c2 == "invy") settings.invert_y ^= 1;
    else if (c2 == "jcenter") calibrateJoystickCenter();
    else if (c2 == "jdir") joystickDirectionWizard();
    else if (c2 == "jspeed" && n == 2 && value > 0 && value < 20000) settings.joy_speed = value;
    else if (c2 == "jsave") {
      settings.joy_min_x = joyCalX.min; settings.joy_max_x = joyCalX.max;
      settings.joy_min_y = joyCalY.min; settings.joy_max_y = joyCalY.max;
    }
    else if (c2 == "tp" && n == 2 && value > 0.1f && value < 50) settings.touch_press = value / 100.0f;
    else if (c2 == "tr" && n == 2 && value > 0.05f && value < 50) settings.touch_release = value / 100.0f;
    else if (c2 == "reset") { settings = StoredSettings{}; Serial.println("[设置] 已恢复默认"); }
    else { Serial.printf("[命令] 无法识别：%s（输入 help）\n", line); continue; }
    if (settings.touch_release >= settings.touch_press) settings.touch_release = settings.touch_press * 0.6f;
    applySettings();
    saveSettings();
    if (c2 != "status" && c2 != "help" && c2 != "log") printStatus();
  }
}

// ============================================================ 主流程
void setup() {
  setCpuFrequencyMhz(160);
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);  // 没接电脑时不阻塞
  pinMode(Pins::TRIG, INPUT_PULLUP);  // 板上已有外部上拉；内部上拉保证单独测开发板时不乱触发
  pinMode(Pins::BTN_R, INPUT_PULLUP);
  pinMode(Pins::JOY_SW, INPUT_PULLUP);
  analogReadResolution(12);
  prefs.begin("gunmouse", false);
  loadSettings();
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
  handleSerial();
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
  const bool linkReady = bleConnected && (uint32_t)(millis() - connectedSinceMs) >= Fw::kConnectSettleMs;
  const bool imuReady = imuInitialized && gyro.calibrated();
  core.setInputs(linkReady, touch.touched(), imuReady, buttonMask, imuSequence);
  if (imuMoved) core.offerImu(imuSequence, imuDx, imuDy);
  if (joyMoved) core.offerJoystick(joyDx, joyDy);
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
  if (logEnabled && (uint32_t)(millis() - lastLogMs) >= 200) {
    lastLogMs = millis();
    printStatus();
  }
}
