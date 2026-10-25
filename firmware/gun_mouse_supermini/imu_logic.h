#pragma once

#include <cmath>
#include <cstdint>

// 陀螺仪处理链（纯逻辑，可在电脑上检查）：开机静置零偏校准 → 静止时追踪温漂 → 低通 →
// 轴映射 → 极小死区 → 按时间积分成鼠标计数。参数沿用旧固件在同型号芯片上实测过的值。
//
// 装配映射沿用原版竖握时的关系：芯片 +X 向上、+Z 为俯仰轴，+Y 为指向轴。
// 左右取绕重力竖直方向的角速度；上下取竖直方向与指向轴叉乘得到的水平轴，补偿侧倾握持。
// 重力方向由陀螺仪预测并用加速度缓慢校正，不再在侧倾时切回固定轴。
// 上下按2026-10-25实物反馈相对旧版镜像；设置中的反向开关仍可叠加。
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
inline Vec3 cross3(const Vec3& a, const Vec3& b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}

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
    trackUp(g, a, dt);

    const float yaw = dot3(g, up_);
    // up × 指向轴(0,1,0)。接近指向竖直时平滑减弱，避免归一化零向量或突然翻向。
    const Vec3 pitch_axis{-up_.z, 0, up_.x};
    const float length = norm3(pitch_axis);
    const float pitch = dot3(g, pitch_axis) / (length > .15f ? length : .15f);
    const float alpha = dt / (1.0f / (2.0f * 3.14159265f * kLowpassHz) + dt);
    lp_x_ += alpha * (-yaw - lp_x_);   // 向右转 = 绕竖直轴负方向 = 鼠标 +X
    lp_y_ += alpha * (-pitch - lp_y_);  // 相对旧版上下镜像
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

  void trackUp(const Vec3& g, const Vec3& a, float dt) {
    // 世界竖直在芯片坐标中随芯片反向转动：du/dt = up × 角速度。
    // 即使加速度含明显平移分量而被拒绝，仍持续进行陀螺仪预测。
    const Vec3 change = cross3(up_, g);
    const float step = dt * (3.14159265f / 180.0f);
    const Vec3 predicted{up_.x + change.x * step, up_.y + change.y * step, up_.z + change.z * step};
    const float predicted_mag = norm3(predicted);
    if (predicted_mag > 1e-3f) {
      up_ = {predicted.x / predicted_mag, predicted.y / predicted_mag, predicted.z / predicted_mag};
    }
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
  int still_count_ = 0;
  float lp_x_ = 0, lp_y_ = 0;
  bool has_last_ = false;
  uint32_t last_us_ = 0;
};

}  // namespace GunMouse
