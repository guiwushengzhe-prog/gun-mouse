#pragma once

#include <cmath>
#include <cstdint>

#include "control_core.h"

// 采样层与发送层的纯逻辑，不依赖 Arduino，可在电脑上编译检查。
namespace GunMouse {

inline float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
inline int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

// 按下立即生效；松开需稳定 release_us（与旧固件一致，按键优先响应）。
class Debouncer {
 public:
  explicit Debouncer(uint32_t release_us = 3000) : release_us_(release_us) {}
  bool update(bool raw_pressed, uint32_t now_us) {
    if (raw_pressed) {
      pressed_ = true;
      release_pending_ = false;
    } else if (pressed_) {
      if (!release_pending_) {
        release_pending_ = true;
        release_start_us_ = now_us;
      } else if ((uint32_t)(now_us - release_start_us_) >= release_us_) {
        pressed_ = false;
        release_pending_ = false;
      }
    }
    return pressed_;
  }
  bool pressed() const { return pressed_; }

 private:
  uint32_t release_us_;
  bool pressed_ = false;
  bool release_pending_ = false;
  uint32_t release_start_us_ = 0;
};

// 按键状态变化队列：两次发送之间的完整点击不会被吞掉；断线时整体丢弃。
class ButtonQueue {
 public:
  static constexpr int kCapacity = 16;
  void reset(uint8_t last_observed) { head_ = count_ = 0; last_ = last_observed; }
  void observe(uint8_t mask) {
    if (mask == last_) return;
    last_ = mask;
    if (count_ == kCapacity) {  // 满时合并到最后一项，最终状态仍正确。
      items_[(head_ + count_ - 1) % kCapacity] = mask;
      return;
    }
    items_[(head_ + count_) % kCapacity] = mask;
    ++count_;
  }
  // 连接初期主机可能尚未开始接收通知；重发一次当前状态，不改变去重基准。
  void resend() {
    if (count_ < kCapacity) {
      items_[(head_ + count_) % kCapacity] = last_;
      ++count_;
    }
  }
  bool empty() const { return count_ == 0; }
  uint8_t front() const { return items_[head_]; }
  void pop() {
    if (!count_) return;
    head_ = (head_ + 1) % kCapacity;
    --count_;
  }
  int size() const { return count_; }

 private:
  uint8_t items_[kCapacity] = {};
  int head_ = 0;
  int count_ = 0;
  uint8_t last_ = 0;
};

// 一路位移：保留小数余量；积压限幅，避免恢复后突然冲出一大段。
class MotionChannel {
 public:
  explicit MotionChannel(float backlog_limit = 127.49f) : limit_(backlog_limit) {}
  void add(float dx, float dy) {
    if (!std::isfinite(dx) || !std::isfinite(dy)) return;
    x_ = clampf(x_ + dx, -limit_, limit_);
    y_ = clampf(y_ + dy, -limit_, limit_);
  }
  void peek(int& ox, int& oy, int min_x, int max_x, int min_y, int max_y) const {
    ox = clampi((int)std::lround(x_), min_x, max_x);
    oy = clampi((int)std::lround(y_), min_y, max_y);
  }
  void consume(int dx, int dy) { x_ -= dx; y_ -= dy; }
  void clear() { x_ = y_ = 0; }
  float x() const { return x_; }
  float y() const { return y_; }

 private:
  float limit_;
  float x_ = 0;
  float y_ = 0;
};

struct HidReport {
  uint8_t buttons;
  int8_t dx;
  int8_t dy;
};

// 发送层：每轮吸收交互核心的结果；按连接间隔发位移，按键变化尽快逐个发送。
// 用法：prepare() 得到报告；真正发出后调用 commit()。
class ReportSender {
 public:
  static constexpr uint32_t kNotifyGapUs = 2500;

  void absorb(const Report& r) {
    if (!r.connected) {
      disconnect();
      return;
    }
    if (!connected_) {
      connected_ = true;
      ever_sent_ = false;
    }
    if (r.neutral) {
      neutral_pending_ = true;
      queue_.reset(0);
      gyro_.clear();
      joy_.clear();
      last_sent_buttons_ = 0;
      return;
    }
    if (r.imu_gate) gyro_.add(r.gyro_x, r.gyro_y);
    else gyro_.clear();  // 完全离开触摸：立即丢弃未发送的体感位移和小数。
    joy_.add(r.joy_x, r.joy_y);
    queue_.observe(r.buttons);
  }

  void clearJoystick() { joy_.clear(); }  // 摇杆回中：只清摇杆自己的余量。
  void resendButtons() {
    if (connected_ && !neutral_pending_) queue_.resend();
  }

  bool prepare(uint32_t now_us, uint32_t period_us, HidReport& out) {
    has_pending_ = false;
    if (!connected_) return false;
    if (ever_sent_ && (uint32_t)(now_us - last_notify_us_) < kNotifyGapUs) return false;
    if (neutral_pending_) {
      out = {0, 0, 0};
      pending_ = {true, false, false, 0, 0, 0, 0, 0};
      has_pending_ = true;
      return true;
    }
    const bool buttons_due = !queue_.empty();
    const bool motion_due = !ever_sent_ || (uint32_t)(now_us - last_report_us_) >= period_us;
    if (!buttons_due && !motion_due) return false;
    int gx = 0, gy = 0, jx = 0, jy = 0;
    if (motion_due) {
      gyro_.peek(gx, gy, -127, 127, -127, 127);
      joy_.peek(jx, jy, -127 - gx, 127 - gx, -127 - gy, 127 - gy);
    }
    // 两路恰好互抵时也提交，避免已抵消的位移以后单独冒出。
    if (!buttons_due && gx == 0 && gy == 0 && jx == 0 && jy == 0) return false;
    const uint8_t buttons = buttons_due ? queue_.front() : last_sent_buttons_;
    out = {buttons, (int8_t)(gx + jx), (int8_t)(gy + jy)};
    pending_ = {false, buttons_due, motion_due, buttons, gx, gy, jx, jy};
    has_pending_ = true;
    return true;
  }

  void commit(uint32_t now_us) {
    if (!has_pending_) return;
    has_pending_ = false;
    if (pending_.neutral) {
      neutral_pending_ = false;
      last_sent_buttons_ = 0;
    } else {
      if (pending_.buttons_due) queue_.pop();
      last_sent_buttons_ = pending_.buttons;
      if (pending_.motion_due) {
        gyro_.consume(pending_.gx, pending_.gy);
        joy_.consume(pending_.jx, pending_.jy);
        last_report_us_ = now_us;
      }
    }
    last_notify_us_ = now_us;
    ever_sent_ = true;
  }

  void disconnect() {
    connected_ = false;
    neutral_pending_ = false;
    has_pending_ = false;
    queue_.reset(0);  // 断线后不重放旧连接的按键队列。
    gyro_.clear();
    joy_.clear();
    last_sent_buttons_ = 0;
  }

  bool connected() const { return connected_; }
  int queued() const { return queue_.size(); }
  const MotionChannel& gyro() const { return gyro_; }
  const MotionChannel& joystick() const { return joy_; }

 private:
  struct Pending {
    bool neutral;
    bool buttons_due;
    bool motion_due;
    uint8_t buttons;
    int gx, gy, jx, jy;
  };
  ButtonQueue queue_;
  MotionChannel gyro_;
  MotionChannel joy_;
  Pending pending_{};
  bool has_pending_ = false;
  bool connected_ = false;
  bool neutral_pending_ = false;
  bool ever_sent_ = false;
  uint8_t last_sent_buttons_ = 0;
  uint32_t last_report_us_ = 0;
  uint32_t last_notify_us_ = 0;
};

// ESP32-S3 触摸读数在手指接触时上升。基线在未触摸时缓慢跟踪；
// 门限取“相对基线比例”和“噪声倍数”中较大者；松开立即生效，按下需稳定 press_confirm_us。
class TouchDetector {
 public:
  struct Settings {
    float press_ratio = 0.020f;    // 首轮初值，整机装壳后按实测调整。
    float release_ratio = 0.012f;
    float noise_sigmas = 8.0f;
    uint32_t press_confirm_us = 3000;
    float baseline_tau_s = 6.0f;
    uint32_t startup_us = 400000;
    uint32_t rebaseline_us = 1500000;  // 读数长期低于基线（开机时正好在摸）后重建。
  };

  void begin(uint32_t now_us) {
    start_us_ = now_us;
    started_ = false;
    sum_ = sum_sq_ = 0;
    count_ = 0;
    touched_ = candidate_ = false;
    below_ = false;
  }
  void setSettings(const Settings& s) { s_ = s; }
  const Settings& settings() const { return s_; }

  bool update(uint32_t raw, uint32_t now_us) {
    last_raw_ = raw;
    if (raw == 0) {  // 读数失败按未触摸处理。
      touched_ = candidate_ = false;
      return false;
    }
    if (!started_) {
      sum_ += raw;
      sum_sq_ += (double)raw * raw;
      ++count_;
      if ((uint32_t)(now_us - start_us_) >= s_.startup_us && count_ >= 8) {
        baseline_ = (float)(sum_ / count_);
        const double var = sum_sq_ / count_ - (sum_ / count_) * (sum_ / count_);
        noise_ = (float)std::sqrt(var > 0 ? var : 0);
        started_ = true;
        last_us_ = now_us;
      }
      return false;
    }
    const float dt = (float)(uint32_t)(now_us - last_us_) * 1e-6f;
    last_us_ = now_us;
    const float press_offset = pressOffset();
    const float release_offset = releaseOffset();
    const float delta = (float)raw - baseline_;
    if (touched_) {
      if (delta < release_offset) touched_ = candidate_ = false;
    } else if (delta > press_offset) {
      if (!candidate_) {
        candidate_ = true;
        candidate_us_ = now_us;
      } else if ((uint32_t)(now_us - candidate_us_) >= s_.press_confirm_us) {
        touched_ = true;
      }
    } else {
      candidate_ = false;
      // 只在读数贴近基线时跟踪（温度、湿度缓慢变化）并估计噪声；大幅偏低交给下面的重建逻辑。
      if (delta < release_offset * 0.5f && delta > -release_offset) {
        const float a = clampf(dt / (s_.baseline_tau_s + dt), 0.0f, 1.0f);
        baseline_ += a * delta;
        noise_ += a * (std::fabs(delta) * 1.2533f - noise_);
      }
    }
    // 开机时手指正好放在扳机上：松开后读数会长期低于基线，此时重建基线。
    if (!touched_ && delta < -release_offset) {
      if (!below_) { below_ = true; below_us_ = now_us; }
      else if ((uint32_t)(now_us - below_us_) >= s_.rebaseline_us) {
        baseline_ = (float)raw;
        below_ = false;
      }
    } else {
      below_ = false;
    }
    return touched_;
  }

  bool ready() const { return started_; }
  bool touched() const { return touched_; }
  float baseline() const { return baseline_; }
  float noise() const { return noise_; }
  uint32_t lastRaw() const { return last_raw_; }
  float pressOffset() const {
    const float by_ratio = baseline_ * s_.press_ratio;
    const float by_noise = noise_ * s_.noise_sigmas;
    return by_ratio > by_noise ? by_ratio : by_noise;
  }
  float releaseOffset() const {
    const float scaled = pressOffset() * (s_.release_ratio / s_.press_ratio);
    return scaled;
  }

 private:
  Settings s_;
  bool started_ = false;
  bool touched_ = false;
  bool candidate_ = false;
  bool below_ = false;
  uint32_t start_us_ = 0, last_us_ = 0, candidate_us_ = 0, below_us_ = 0;
  uint32_t last_raw_ = 0;
  double sum_ = 0, sum_sq_ = 0;
  uint32_t count_ = 0;
  float baseline_ = 0;
  float noise_ = 0;
};

// 摇杆单轴：中心与两端分别归一化，两半行程各自按实际端点计算。
struct JoystickAxisCal {
  int center = 2048;
  int min = 300;   // 首轮保守端点；使用中观测到更远值会自动扩展。
  int max = 3800;

  float normalize(int raw) const {
    if (raw >= center) {
      const int span = max - center;
      return span > 0 ? clampf((float)(raw - center) / span, 0.0f, 1.0f) : 0.0f;
    }
    const int span = center - min;
    return span > 0 ? clampf((float)(raw - center) / span, -1.0f, 0.0f) : 0.0f;
  }
  void observe(int raw) {
    if (raw < min) min = raw;
    if (raw > max) max = raw;
  }
};

// 径向死区与平滑曲线（沿用旧固件已试用的手感曲线）。返回 [-1,1] 的二维输出。
inline bool shapeJoystick(float x, float y, float deadzone, float& ox, float& oy) {
  const float mag = std::sqrt(x * x + y * y);
  if (mag <= deadzone) {
    ox = oy = 0;
    return false;
  }
  const float t = clampf((mag - deadzone) / (1.0f - deadzone), 0.0f, 1.0f);
  const float shaped = t * (0.18f + 0.82f * t);
  const float factor = shaped / mag;
  ox = x * factor;
  oy = y * factor;
  return true;
}

// 锂聚合物电池静置电压粗略换算电量（仅用于蓝牙电量显示，不作保护依据）。
inline uint8_t batteryPercentFromMillivolts(float mv) {
  static const float kTable[][2] = {{3300, 0},  {3500, 5},  {3600, 10}, {3700, 25}, {3750, 35},
                                    {3800, 45}, {3900, 62}, {4000, 78}, {4100, 90}, {4180, 100}};
  if (!std::isfinite(mv) || mv <= kTable[0][0]) return 0;
  const int n = sizeof(kTable) / sizeof(kTable[0]);
  for (int i = 1; i < n; ++i) {
    if (mv <= kTable[i][0]) {
      const float f = (mv - kTable[i - 1][0]) / (kTable[i][0] - kTable[i - 1][0]);
      return (uint8_t)std::lround(kTable[i - 1][1] + f * (kTable[i][1] - kTable[i - 1][1]));
    }
  }
  return 100;
}

}  // namespace GunMouse
