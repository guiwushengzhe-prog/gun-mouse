// 电脑上检查固件纯逻辑：g++ -std=c++17 -O1 -I../gun_mouse test_firmware_logic.cpp
// 只验证逻辑，不代替实物上的传感器、触摸与蓝牙测试。
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>

#include "control_core.h"
#include "imu_logic.h"
#include "input_logic.h"
#include "direction_calibration.h"
#include "device_status.h"

using namespace GunMouse;

static int checks = 0;
#define CHECK(cond)                                                    \
  do {                                                                 \
    ++checks;                                                          \
    if (!(cond)) {                                                     \
      std::printf("失败 %s:%d  %s\n", __FILE__, __LINE__, #cond);    \
      return 1;                                                        \
    }                                                                  \
  } while (0)

struct Rig {
  ControlCore core;
  ReportSender sender;
  uint64_t seq = 0;
  std::vector<HidReport> sent;
  uint32_t now = 0;
  void step(bool connected, bool touched, uint8_t buttons, float gx = 0, float gy = 0, float jx = 0, float jy = 0,
            bool imu_ready = true, uint32_t dt = 1000) {
    now += dt;
    ++seq;
    core.setInputs(connected, touched, imu_ready, buttons, seq);
    core.offerImu(seq, gx, gy);
    if (jx || jy) core.offerJoystick(jx, jy);
    sender.absorb(core.takeReport());
    HidReport r;
    if (sender.prepare(now, 7500, r)) {
      sent.push_back(r);
      sender.commit(now);
    }
  }
};

int testSender() {
  Rig rig;
  rig.step(true, false, 0);
  CHECK(rig.sent.size() == 1 && rig.sent[0].buttons == 0 && rig.sent[0].dx == 0);  // 连接首帧全释放
  // 两次发送之间的完整点击：按下、松开都要发出，按顺序。
  rig.step(true, false, 1, 0, 0, 0, 0, true, 100);
  rig.step(true, false, 0, 0, 0, 0, 0, true, 100);
  for (int i = 0; i < 20; ++i) rig.step(true, false, 0);
  std::vector<uint8_t> masks;
  for (size_t i = 1; i < rig.sent.size(); ++i) masks.push_back(rig.sent[i].buttons);
  CHECK(masks.size() >= 2 && masks[0] == 1 && masks[1] == 0);
  // 小数余量：每样本 0.3 计数，约 1 秒后总和接近 300 且不丢失。
  rig.sent.clear();
  int total = 0;
  for (int i = 0; i < 1000; ++i) rig.step(true, true, 0, 0.3f, 0);
  for (auto& r : rig.sent) total += r.dx;
  // 首个触摸样本按规则丢弃；已发出的整数加上尚未到期的余量应等于其余 999 个样本之和。
  CHECK(std::fabs(total + rig.sender.gyro().x() - 999 * 0.3f) < 0.01f && total > 290);
  // 松开触摸立即丢弃体感余量，摇杆不受影响。
  for (int i = 0; i < 3; ++i) rig.step(true, true, 0, 50, 0, 0, 0, true, 1000);
  rig.sent.clear();
  rig.step(true, false, 0, 0, 0, 2.0f, 0, true, 1000);  // 松开触摸的同一轮还有摇杆位移
  for (int i = 0; i < 10; ++i) rig.step(true, false, 0);
  total = 0;
  for (auto& r : rig.sent) total += r.dx;
  CHECK(total == 2 && std::fabs(rig.sender.gyro().x()) < 1e-6);  // 未发出的体感全部丢弃，只剩摇杆
  // 单份报告不超过 ±127，积压限幅。
  rig.sent.clear();
  for (int i = 0; i < 10; ++i) rig.step(true, true, 0, 500, -500, 0, 0, true, 1000);
  for (auto& r : rig.sent) CHECK(r.dx <= 127 && r.dy >= -127);
  // 断线：不累计、清队列；重连首帧全释放，随后报告当前按键。
  rig.step(false, true, 7);
  rig.step(false, true, 7, 100, 100, 100, 100);
  rig.sent.clear();
  rig.step(true, true, 4, 0, 0, 0, 0, true, 10000);
  for (int i = 0; i < 10; ++i) rig.step(true, true, 4);
  CHECK(rig.sent.size() >= 2 && rig.sent[0].buttons == 0 && rig.sent[0].dx == 0 && rig.sent[1].buttons == 4);
  // 惯性芯片未就绪：体感停，按键和摇杆照常。
  rig.sent.clear();
  for (int i = 0; i < 10; ++i) rig.step(true, true, 2, 50, 0, 1.0f, 0, false, 1000);
  total = 0;
  for (auto& r : rig.sent) total += r.dx;
  CHECK(std::fabs(total + rig.sender.joystick().x() - 10) < 1e-4 && std::fabs(rig.sender.gyro().x()) < 1e-6);
  CHECK(!rig.sent.empty() && rig.sent.back().buttons == 2);
  // 体感与摇杆刚好互抵也会提交，不留残余。
  rig.sent.clear();
  ReportSender s2;
  ControlCore c2;
  c2.setInputs(true, true, true, 0, 1);
  s2.absorb(c2.takeReport());
  HidReport r;
  CHECK(s2.prepare(0, 7500, r));
  s2.commit(0);
  c2.setInputs(true, true, true, 0, 1);
  c2.offerImu(2, 5, 0);
  c2.offerJoystick(-5, 0);
  s2.absorb(c2.takeReport());
  CHECK(s2.prepare(8000, 7500, r) && r.dx == 0);
  s2.commit(8000);
  CHECK(std::fabs(s2.gyro().x()) < 1e-6 && std::fabs(s2.joystick().x()) < 1e-6);
  return 0;
}

int testDebounce() {
  Debouncer d(3000);
  CHECK(d.update(true, 0));          // 按下立即
  CHECK(d.update(false, 100));       // 松开抖动期间仍按下
  CHECK(d.update(true, 200));
  CHECK(d.update(false, 1000));
  CHECK(d.update(false, 3500));
  CHECK(!d.update(false, 4100));     // 稳定 3ms 后松开
  return 0;
}

int testRejectedSend() {
  ControlCore core;
  ReportSender sender;
  HidReport report;
  core.setInputs(true, false, true, 0, 1);
  sender.absorb(core.takeReport());
  CHECK(sender.prepare(10000, 7500, report) && report.buttons == 0);
  // 底层拒绝发送：不调用 commit。首次中立帧必须留给下一次成功发送。
  CHECK(sender.prepare(13000, 7500, report) && report.buttons == 0 && report.dx == 0);
  sender.commit(13000);
  core.setInputs(true, false, true, 1, 2);
  sender.absorb(core.takeReport());
  core.setInputs(true, false, true, 0, 3);
  core.offerJoystick(4, 0);
  sender.absorb(core.takeReport());
  CHECK(sender.prepare(21000, 7500, report) && report.buttons == 1 && report.dx == 4);
  const int queuedBeforeRetry = sender.queued();
  CHECK(sender.prepare(24000, 7500, report) && report.buttons == 1 && report.dx == 4);
  CHECK(sender.queued() == queuedBeforeRetry && sender.joystick().x() == 4);
  sender.commit(24000);
  CHECK(sender.prepare(27000, 7500, report) && report.buttons == 0 && report.dx == 0);
  sender.commit(27000);
  CHECK(sender.queued() == 0 && sender.joystick().x() == 0);
  return 0;
}

int testTouch() {
  TouchDetector t;
  t.begin(0);
  uint32_t now = 0;
  for (int i = 0; i < 250; ++i) { now += 2000; t.update(30000 + (i % 3) * 20, now); }
  CHECK(t.ready() && std::fabs(t.baseline() - 30020) < 30);
  for (int i = 0; i < 5; ++i) { now += 2000; t.update(30200, now); }
  CHECK(!t.touched());  // 0.6% 不算触摸
  for (int i = 0; i < 4; ++i) { now += 2000; t.update(31500, now); }
  CHECK(t.touched());   // 5% 稳定 3ms 以上
  now += 2000;
  CHECK(!t.update(30100, now));  // 松开立即生效
  // 开机时手指正好在扳机上：基线偏高，松开后读数长期偏低，应自动重建。
  TouchDetector t2;
  t2.begin(0);
  now = 0;
  for (int i = 0; i < 250; ++i) { now += 2000; t2.update(32000, now); }
  for (int i = 0; i < 1000; ++i) { now += 2000; t2.update(30000, now); }
  CHECK(std::fabs(t2.baseline() - 30000) < 200);
  for (int i = 0; i < 4; ++i) { now += 2000; t2.update(31500, now); }
  CHECK(t2.touched());
  return 0;
}

int testJoystick() {
  JoystickAxisCal c{2000, 300, 3800};
  CHECK(std::fabs(c.normalize(2000)) < 1e-6);
  CHECK(std::fabs(c.normalize(3800) - 1) < 1e-6 && std::fabs(c.normalize(300) + 1) < 1e-6);
  CHECK(std::fabs(c.normalize(1150) + 0.5f) < 1e-3);  // 两半行程分别归一化
  c.observe(4000);
  CHECK(c.max == 4000);
  float x, y;
  CHECK(!shapeJoystick(0.05f, 0.05f, 0.1f, x, y) && x == 0);
  CHECK(shapeJoystick(1.0f, 0, 0.1f, x, y) && std::fabs(x - 1) < 1e-5);
  return 0;
}

int testTouchStartupAndGrip() {
  TouchDetector t;
  t.begin(0);
  uint32_t now = 0;
  for (int i = 0; i < 250; ++i) {
    now += 2000;
    t.update(i < 5 ? 2000000 : 30000 + i % 3 * 5, now);
  }
  CHECK(t.ready() && std::fabs(t.baseline() - 30005) < 15 && t.noise() < 20);
  for (int i = 0; i < 4; ++i) { now += 2000; t.update(33000, now); }
  CHECK(t.touched());  // 首秒即可识别，启动大读数不再污染数十秒。
  now += 2000;
  CHECK(!t.update(30000, now));
  now += 2000;
  t.update(2000000, now);
  now += 2000;
  CHECK(!t.update(30000, now));  // 单个毛刺不算触摸。

  // 使用本轮正常握持未触摸与真实触摸的实测范围，验证8%/5%设置及松开。
  TouchDetector held;
  auto settings = held.settings();
  settings.press_ratio = .08f;
  settings.release_ratio = .05f;
  held.setSettings(settings);
  held.begin(0);
  now = 0;
  for (int i = 0; i < 250; ++i) { now += 2000; held.update(31881, now); }
  bool falseTouch = false;
  for (int i = 0; i < 1000; ++i) {
    now += 2000;
    falseTouch |= held.update(32788 + i % 181, now);
  }
  CHECK(!falseTouch);
  for (int i = 0; i < 20; ++i) { now += 2000; held.update(42107 + i * 50, now); }
  CHECK(held.touched());
  now += 2000;
  CHECK(!held.update(32968, now));
  return 0;
}

int testTouchInterruptedSampling() {
  TouchDetector t;
  auto settings = t.settings();
  settings.press_ratio = .08f;
  settings.release_ratio = .05f;
  t.setSettings(settings);
  t.begin(0);
  uint32_t now = 0;
  for (int i = 0; i < 250; ++i) { now += 2000; t.update(33000, now); }
  now += 2000;
  CHECK(!t.update(39000, now));
  now += 100000;
  CHECK(!t.update(39000, now));  // 没有采样的100毫秒不能充当稳定触摸。
  for (int i = 0; i < 3; ++i) { now += 2000; t.update(39000, now); }
  CHECK(t.touched());
  now += 100000;
  CHECK(!t.update(39000, now));  // 已触摸时中断，也要从新样本重新确认。
  for (int i = 0; i < 3; ++i) { now += 2000; t.update(39000, now); }
  CHECK(t.touched());
  now += 2000;
  CHECK(!t.update(0, now));
  now += 2000;
  CHECK(!t.update(39000, now));
  for (int i = 0; i < 3; ++i) { now += 2000; t.update(39000, now); }
  CHECK(t.touched());

  // 开机握住后松开：重建基线也必须有连续低读数，不能跨越采样中断。
  TouchDetector released;
  released.setSettings(settings);
  released.begin(0);
  now = 0;
  for (int i = 0; i < 250; ++i) { now += 2000; released.update(43000, now); }
  for (int i = 0; i < 50; ++i) { now += 2000; released.update(33000, now); }
  now += 1500000;
  released.update(33000, now);
  CHECK(released.baseline() > 42000);
  for (int i = 0; i < 800; ++i) { now += 2000; released.update(33000, now); }
  CHECK(std::fabs(released.baseline() - 33000) < 100);

  TouchDetector startup;
  startup.begin(0);
  now = 0;
  for (int i = 0; i < 100; ++i) { now += 2000; startup.update(43000, now); }
  now += 1000000;
  startup.update(33000, now);
  CHECK(!startup.ready());
  for (int i = 0; i < 205; ++i) { now += 2000; startup.update(33000, now); }
  CHECK(startup.ready() && std::fabs(startup.baseline() - 33000) < 1);
  return 0;
}

int testHorizontalCalibration() {
  for (float slope : {-.57735f, 0.0f, .57735f}) {
    HorizontalCalibration c;
    c.begin();
    for (int i = 0; i < 240; ++i) {
      const float x = i < 120 ? 30 : -30;
      c.observe(x, slope * x + (i % 2 ? .1f : -.1f), .002f);
    }
    float result = 99;
    CHECK(c.finish(result) && std::fabs(result - slope) < .001f);
  }
  HorizontalCalibration oneWay;
  for (int i = 0; i < 240; ++i) oneWay.observe(30, 15, .002f);
  float result = 99;
  CHECK(!oneWay.finish(result) && result == 99);
  HorizontalCalibration vertical;
  for (int i = 0; i < 240; ++i) vertical.observe(0, 30, .002f);
  CHECK(!vertical.finish(result));
  HorizontalCalibration inconsistent;
  for (int i = 0; i < 240; ++i) inconsistent.observe(i < 120 ? 30 : -30, i % 2 ? 100 : -100, .002f);
  CHECK(!inconsistent.finish(result));

  GyroPipeline g;
  auto settings = g.settings();
  settings.horizontal_coupling = .57735f;
  g.setSettings(settings);
  g.startCalibration();
  uint32_t now = 0;
  float dx, dy, sx = 0, sy = 0;
  for (int i = 0; i < 2880; ++i) { now += 1042; g.process({0, 0, 0, 1, 0, 0}, now, dx, dy); }
  for (int i = 0; i < 32; ++i) {
    now += 1042;
    g.process({-30, 0, -30 * .57735f, 1, 0, 0}, now, dx, dy);
    sx += dx; sy += dy;
  }
  CHECK(sx > 50 && std::fabs(sy) < .15f);
  g.startCalibration();
  for (int i = 0; i < 2880; ++i) { now += 1042; g.process({0, 0, 0, 1, 0, 0}, now, dx, dy); }
  sx = sy = 0;
  for (int i = 0; i < 32; ++i) {
    now += 1042;
    g.process({0, 0, 20, 1, 0, 0}, now, dx, dy);
    sx += dx; sy += dy;
  }
  CHECK(std::fabs(sx) < .01f && sy < -35);  // 纯上下动作保留。
  return 0;
}

int testGyro() {
  GyroPipeline g;
  g.startCalibration();
  uint32_t t = 0;
  float dx, dy;
  // 竖握静置：重力沿芯片 +X（整机竖直向上），陀螺仪有固定零偏。
  for (int i = 0; i < 2880; ++i) { t += 1042; g.process({0.5f, -0.3f, 0.2f, 1, 0, 0}, t, dx, dy); }
  CHECK(g.calibrated() && std::fabs(g.bias().x - 0.5f) < 1e-3 && g.up().x > 0.99f);
  // 向右转（绕竖直方向负转 30°/s，即芯片 -X）：鼠标向右。
  float sx = 0, sy = 0;
  for (int i = 0; i < 960; ++i) { t += 1042; g.process({0.5f - 30, -0.3f, 0.2f, 1, 0, 0}, t, dx, dy); sx += dx; sy += dy; }
  CHECK(sx > 64 * 30 * 0.9f && std::fabs(sy) < 5);
  // 芯片Z负转：按本轮要求相对旧版镜像，dy由负变正。
  sx = sy = 0;
  for (int i = 0; i < 960; ++i) { t += 1042; g.process({0.5f, -0.3f, 0.2f - 20, 1, 0, 0}, t, dx, dy); sx += dx; sy += dy; }
  CHECK(sy > 64 * 20 * 0.9f && std::fabs(sx) < 5);
  // 时间停顿不放大位移。
  t += 500000;
  g.process({0.5f - 30, -0.3f, 0.2f, 1, 0, 0}, t, dx, dy);
  CHECK(std::fabs(dx) < 64 * 30 * 0.011f);
  // 校准期间晃动会重新计数。
  GyroPipeline g2;
  g2.startCalibration();
  t = 0;
  for (int i = 0; i < 2000; ++i) { t += 1042; g2.process({0, 0, 0, 1, 0, 0}, t, dx, dy); }
  t += 1042;
  g2.process({20, 0, 0, 1, 0, 0}, t, dx, dy);
  for (int i = 0; i < 1000; ++i) { t += 1042; g2.process({0, 0, 0, 1, 0, 0}, t, dx, dy); }
  CHECK(!g2.calibrated());
  return 0;
}

int testGyroPose() {
  const float rad = 3.14159265f / 180.0f;
  auto calibrate = [](GyroPipeline& g, const Vec3& up, uint32_t& t) {
    g.startCalibration();
    float dx, dy;
    for (int i = 0; i < GyroPipeline::kCalibrationSamples; ++i) {
      t += 1042;
      g.process({0, 0, 0, up.x, up.y, up.z}, t, dx, dy);
    }
  };
  // 同一个水平右转动作，在不同侧倾角度下不应串入上下或丢失水平速度。
  // 53度附近覆盖旧版 xy=0.6 的突然切轴位置；90度覆盖芯片Z朝上的姿态。
  for (float angle : {0.0f, 30.0f, 53.0f, 53.3f, 60.0f, 90.0f, 120.0f, 180.0f, -90.0f}) {
    const Vec3 up{std::cos(angle * rad), 0, std::sin(angle * rad)};
    GyroPipeline g;
    uint32_t t = 0;
    calibrate(g, up, t);
    CHECK(g.calibrated());
    float sx = 0, sy = 0, dx, dy;
    for (int i = 0; i < 64; ++i) {
      t += 1042;
      g.process({-30 * up.x, -30 * up.y, -30 * up.z, up.x, up.y, up.z}, t, dx, dy);
      sx += dx; sy += dy;
    }
    CHECK(sx > 64 * 30 * 0.060f && std::fabs(sy) < 0.5f);

    // 上下沿随握姿改变的水平轴，且按本轮要求相对旧版镜像。
    GyroPipeline pitch;
    t = 0;
    calibrate(pitch, up, t);
    const Vec3 left{-up.z, 0, up.x};
    sx = sy = 0;
    for (int i = 1; i <= 64; ++i) {
      t += 1042;
      const float tilt = 20 * i * .001042f * rad;
      const Vec3 a{up.x * std::cos(tilt), -std::sin(tilt), up.z * std::cos(tilt)};
      pitch.process({20 * left.x, 20 * left.y, 20 * left.z, a.x, a.y, a.z}, t, dx, dy);
      sx += dx; sy += dy;
    }
    CHECK(sy < -64 * 20 * 0.060f && std::fabs(sx) < 0.5f);
  }
  // 快速侧倾90度时，重力方向必须跟上；有额外线性加速度时也要保留陀螺仪预测。
  for (float accelMagnitude : {1.0f, 1.3f}) {
    GyroPipeline g;
    uint32_t t = 0;
    calibrate(g, {1, 0, 0}, t);
    float sx = 0, sy = 0, dx, dy;
    for (int i = 1; i <= 960; ++i) {
      t += 1042;
      const float roll = 90 * i * .001042f * rad;
      g.process({0, 90, 0, accelMagnitude * std::cos(roll), 0,
                 accelMagnitude * std::sin(roll)}, t, dx, dy);
      sx += dx; sy += dy;
    }
    CHECK(g.up().z > .999f && std::fabs(g.up().x) < .005f);
    CHECK(std::fabs(sx) < .01f && std::fabs(sy) < .01f);
    sx = sy = 0;
    const Vec3 up = g.up();
    for (int i = 0; i < 64; ++i) {
      t += 1042;
      g.process({-30 * up.x, -30 * up.y, -30 * up.z, up.x, up.y, up.z}, t, dx, dy);
      sx += dx; sy += dy;
    }
    CHECK(sx > 64 * 30 * 0.060f && std::fabs(sy) < .5f);
  }
  // 指向轴接近竖直时，水平俯仰轴无法唯一确定，输出应平滑减弱且保持有限。
  GyroPipeline vertical;
  uint32_t t = 0;
  calibrate(vertical, {0, 1, 0}, t);
  float dx, dy;
  t += 1042;
  vertical.process({0, -30, 0, 0, 1, 0}, t, dx, dy);
  CHECK(std::isfinite(dx) && std::isfinite(dy) && dx > 0 && std::fabs(dy) < .001f);
  return 0;
}

int testGyroInterruptedSampling() {
  GyroPipeline g;
  g.startCalibration();
  uint32_t now = 0;
  float dx, dy;
  for (int i = 0; i < 2880; ++i) { now += 1042; g.process({0, 0, 0, 1, 0, 0}, now, dx, dy); }
  for (int i = 0; i < 40; ++i) { now += 1042; g.process({-30, 0, 0, 1, 0, 0}, now, dx, dy); }
  CHECK(dx > 1);
  now += 100000;
  CHECK(!g.process({0, 0, 0, 1, 0, 0}, now, dx, dy) && dx == 0 && dy == 0);
  float total = 0;
  for (int i = 0; i < 20; ++i) {
    now += 1042;
    g.process({0, 0, 0, 1, 0, 0}, now, dx, dy);
    total += std::fabs(dx) + std::fabs(dy);
  }
  CHECK(total == 0);  // 中断前低通余量不应在恢复后移动光标。
  now += 100000;
  g.process({0, 0, 0, 0, 0, 1}, now, dx, dy);
  CHECK(g.up().z > .999f);
  now += 1042;
  g.process({0, 0, -30, 0, 0, 1}, now, dx, dy);
  CHECK(dx > .5f && std::fabs(dy) < .001f);
  return 0;
}

int testBatteryUsb() {
  CHECK(batteryPercentFromMillivolts(4200) == 100 && batteryPercentFromMillivolts(3200) == 0);
  CHECK(batteryPercentFromMillivolts(3850) > 45 && batteryPercentFromMillivolts(3850) < 62);
  External5vDetector u;
  CHECK(!u.updateMillivolts(4000));  // 充满电池经二极管供电时不能误报 USB
  CHECK(!u.updateMillivolts(4500) && u.updateMillivolts(4501));
  CHECK(u.updateMillivolts(4400) && u.updateMillivolts(4300) && !u.updateMillivolts(4299));
  CHECK(!u.updateMillivolts(NAN));
  return 0;
}

int testDeviceStatus() {
  DeviceStatus state;
  char buffer[512];
  CHECK(formatDeviceStatus(state, buffer, sizeof(buffer)));
  CHECK(std::strstr(buffer, "\"enabled\":0,\"ready\":0") != nullptr);
  CHECK(std::strstr(buffer, "\"mv\":-1,\"charge\":-1") != nullptr);
  state.joy_enabled = state.joy_ready = true;
  state.raw_x = 4095; state.raw_y = 0;
  state.center_x = 1999; state.center_y = 2111;
  state.joy_speed = 19999; state.sensitivity = 999;
  state.center_revision = state.command_sequence = UINT32_MAX;
  state.command = "jcenter";
  state.runtime = {UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX,
                   UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX};
  for (int mv : {3300, 4100, 5070}) {
    state.node_mv = mv;
    CHECK(formatDeviceStatus(state, buffer, sizeof(buffer)));
    CHECK(std::strlen(buffer) < 512);
    CHECK(std::strstr(buffer, "\"charge\":-1") != nullptr); // 电压高也不能伪称充电或充满。
  }
  CHECK(std::strstr(buffer, "\"raw\":[4095,0],\"center\":[1999,2111]") != nullptr);
  CHECK(std::strstr(buffer, "\"rev\":4294967295") != nullptr);
  CHECK(std::strstr(buffer, "\"gap_us\":4294967295") != nullptr);
  CHECK(std::strstr(buffer, "\"i2c\":4294967295") != nullptr);
  char small[24];
  CHECK(!formatDeviceStatus(state, small, sizeof(small)) && small[0] == 0);
  return 0;
}

int main() {
  if (testSender() || testRejectedSend() || testDebounce() || testTouch() || testTouchStartupAndGrip() || testTouchInterruptedSampling() ||
      testJoystick() || testHorizontalCalibration() || testGyroPose() || testGyro() || testGyroInterruptedSampling() || testBatteryUsb() || testDeviceStatus()) return 1;
  std::printf("固件逻辑检查通过：%d 项（按键事件不丢、余量、触摸门控、断线重连、摇杆、陀螺仪方向与校准、电量）\n", checks);
  return 0;
}
