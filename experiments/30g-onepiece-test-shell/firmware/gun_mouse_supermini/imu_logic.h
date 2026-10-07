#pragma once

#include <cmath>
#include <cstdint>

// 陀螺仪处理链（纯逻辑，可在电脑上检查）：开机静置零偏校准 → 静止时追踪温漂 → 低通 →
// 轴映射 → 极小死区 → 按时间积分成鼠标计数。参数沿用旧固件在同型号芯片上实测过的值。
//
// 轴映射：芯片贴在主板元件面，元件面朝整机 +Y（左），所以芯片 Z 轴 = 整机左向轴，绕它转动就是俯仰。
// 偏航取“绕重力竖直方向的转动”（由加速度计低通得到），不依赖芯片 X/Y 在板上的朝向，
// 侧倾握持时左右转动仍对应屏幕水平移动。
namespace GunMouse {

struct ImuSample {
  float gx, gy, gz;  // °/s，芯片坐标
  float ax, ay, az;  // g，芯片坐标
};

struct Vec3 {
  float x, y, z;
};

inline float dot3(const Vec3& a, const Vec3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline float norm3(const Vec3& a) { return std::sqrt(dot3(a, a)); }

class GyroPipeline {
 public:
  static constexpr float kOdrHz = 960.0f;
  static constexpr int kCalibrationSamples = 2880;    // 约 3 秒
  static constexpr float kCalibrationMaxStd = 0.15f;  // °/s
  static constexpr float kCalibrationMaxRate = 5.0f;  // °/s
  static constexpr uint32_t kCalibrationMaxGapUs = 20000;
  static constexpr float kStillAccelErrorG = 0.035f;
  static constexpr float kStillGyroDps = 0.10f;
  static constexpr int kStillConfirmSamples = 120;
  static constexpr float kBiasTimeConstant = 8.0f;
  static constexpr float kLowpassHz = 180.0f;
  static constexpr float kDeadzoneDps = 0.04f;
  static constexpr float kUpTimeConstant = 0.5f;

  struct Settings {
    float counts_per_deg = 64.0f;  // 首轮默认，实际速度优先在电脑/游戏里调。
    bool invert_x = false;
    bool invert_y = false;
  };

  void setSettings(const Settings& s) { s_ = s; }
  const Settings& settings() const { return s_; }

  void startCalibration() {
    calibrated_ = false;
    window_ = Window{};
    still_count_ = 0;
    lp_x_ = lp_y_ = 0;
    has_last_ = false;
  }

  bool calibrated() const { return calibrated_; }
  Vec3 bias() const { return bias_; }
  Vec3 noise() const { return noise_; }
  Vec3 up() const { return up_; }

  // 返回 true 表示本样本给出了鼠标位移（未经触摸门控）。
  bool process(const ImuSample& s, uint32_t sample_us, float& dx, float& dy) {
    dx = dy = 0;
    uint32_t gap = has_last_ ? (uint32_t)(sample_us - last_us_) : 0;
    has_last_ = true;
    last_us_ = sample_us;
    if (!calibrated_) {
      if (gap > kCalibrationMaxGapUs) window_ = Window{};
      calibrate(s);
      return false;
    }
    float dt = gap * 1e-6f;
    if (dt < 0.0003f || dt > 0.010f) dt = 1.0f / kOdrHz;  // 时间异常保护，不把停顿乘进位移。

    Vec3 g{s.gx - bias_.x, s.gy - bias_.y, s.gz - bias_.z};
    const Vec3 a{s.ax, s.ay, s.az};
    trackBiasWhenStill(g, a, dt);
    trackUp(a, dt);

    float yaw = dot3(g, yawAxis());  // 绕竖直方向的角速度
    float pitch = g.z;              // 绕整机左向轴
    const float alpha = dt / (1.0f / (2.0f * 3.14159265f * kLowpassHz) + dt);
    lp_x_ += alpha * (-yaw - lp_x_);   // 向右转 = 绕竖直轴负方向 = 鼠标 +X
    lp_y_ += alpha * (pitch - lp_y_);  // 抬头 = 绕左向轴负方向 = 鼠标 -Y（向上）
    float rx = deadzone(lp_x_);
    float ry = deadzone(lp_y_);
    if (s_.invert_x) rx = -rx;
    if (s_.invert_y) ry = -ry;
    dx = rx * dt * s_.counts_per_deg;
    dy = ry * dt * s_.counts_per_deg;
    return true;
  }

 private:
  struct Window {
    int samples = 0;
    double sum[3] = {0, 0, 0};
    double sum_sq[3] = {0, 0, 0};
    double acc[3] = {0, 0, 0};
    float first_acc[3] = {0, 0, 0};
  };

  void calibrate(const ImuSample& s) {
    const float rates[3] = {s.gx, s.gy, s.gz};
    const float acc[3] = {s.ax, s.ay, s.az};
    const float mag = std::sqrt(s.ax * s.ax + s.ay * s.ay + s.az * s.az);
    bool moving = std::fabs(mag - 1.0f) > kStillAccelErrorG;
    for (int i = 0; i < 3; ++i) {
      moving |= std::fabs(rates[i]) > kCalibrationMaxRate;
      if (window_.samples) moving |= std::fabs(acc[i] - window_.first_acc[i]) > kStillAccelErrorG;
    }
    if (moving) {
      window_ = Window{};
      return;
    }
    for (int i = 0; i < 3; ++i) {
      if (!window_.samples) window_.first_acc[i] = acc[i];
      window_.sum[i] += rates[i];
      window_.sum_sq[i] += (double)rates[i] * rates[i];
      window_.acc[i] += acc[i];
    }
    ++window_.samples;
    if ((window_.samples & 63) != 0 && window_.samples < kCalibrationSamples) return;
    double mean[3], sd[3];
    for (int i = 0; i < 3; ++i) {
      mean[i] = window_.sum[i] / window_.samples;
      const double var = window_.sum_sq[i] / window_.samples - mean[i] * mean[i];
      sd[i] = std::sqrt(var > 0 ? var : 0);
      if (sd[i] > kCalibrationMaxStd) {
        window_ = Window{};
        return;
      }
    }
    if (window_.samples < kCalibrationSamples) return;
    bias_ = {(float)mean[0], (float)mean[1], (float)mean[2]};
    noise_ = {(float)sd[0], (float)sd[1], (float)sd[2]};
    const Vec3 g{(float)(window_.acc[0] / window_.samples), (float)(window_.acc[1] / window_.samples),
                 (float)(window_.acc[2] / window_.samples)};
    setUp(g, 1.0f);
    still_count_ = 0;
    lp_x_ = lp_y_ = 0;
    calibrated_ = true;
  }

  void trackBiasWhenStill(Vec3& g, const Vec3& a, float dt) {
    const bool still = std::fabs(norm3(a) - 1.0f) < kStillAccelErrorG && norm3(g) < kStillGyroDps;
    if (!still) {
      still_count_ = 0;
      return;
    }
    if (still_count_ < kStillConfirmSamples) {
      ++still_count_;
      return;
    }
    const float alpha = dt / (kBiasTimeConstant + dt);
    bias_.x += g.x * alpha;
    bias_.y += g.y * alpha;
    bias_.z += g.z * alpha;
    g = {0, 0, 0};
  }

  void trackUp(const Vec3& a, float dt) {
    const float mag = norm3(a);
    if (std::fabs(mag - 1.0f) > 0.15f) return;  // 剧烈加减速时不更新竖直方向
    setUp(a, dt / (kUpTimeConstant + dt));
  }

  void setUp(const Vec3& a, float weight) {
    const float mag = norm3(a);
    if (mag < 0.5f) return;
    const Vec3 n{a.x / mag, a.y / mag, a.z / mag};
    up_ = {up_.x + weight * (n.x - up_.x), up_.y + weight * (n.y - up_.y), up_.z + weight * (n.z - up_.z)};
    const float m = norm3(up_);
    if (m > 1e-3f) up_ = {up_.x / m, up_.y / m, up_.z / m};
    // 记住最近一次“竖握”时的竖直方向，平放（芯片 Z 朝上下）时用它，避免偏航与俯仰混成同一轴。
    const float xy = std::sqrt(up_.x * up_.x + up_.y * up_.y);
    if (xy > 0.6f) body_up_ = {up_.x / xy, up_.y / xy, 0};
  }

  Vec3 yawAxis() const {
    const float xy = std::sqrt(up_.x * up_.x + up_.y * up_.y);
    return xy > 0.6f ? up_ : body_up_;
  }

  float deadzone(float v) const {
    const float m = std::fabs(v);
    if (m <= kDeadzoneDps) return 0;
    return v > 0 ? m - kDeadzoneDps : -(m - kDeadzoneDps);
  }

  Settings s_;
  bool calibrated_ = false;
  Window window_;
  Vec3 bias_{0, 0, 0};
  Vec3 noise_{0, 0, 0};
  Vec3 up_{1, 0, 0};
  Vec3 body_up_{1, 0, 0};
  int still_count_ = 0;
  float lp_x_ = 0, lp_y_ = 0;
  bool has_last_ = false;
  uint32_t last_us_ = 0;
};

}  // namespace GunMouse
