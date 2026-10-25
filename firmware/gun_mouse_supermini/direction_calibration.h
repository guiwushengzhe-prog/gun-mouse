#pragma once

#include <cmath>
#include <cstdint>

namespace GunMouse {

// 用用户实际左右往返动作估计串入的上下量，只校正横向串轴，不旋转已经合适的纵向轴。
class HorizontalCalibration {
 public:
  void begin() { *this = HorizontalCalibration{}; }
  void observe(float x, float y, float dt) {
    if (!std::isfinite(x) || !std::isfinite(y) || dt <= 0 || dt > .02f || std::fabs(x) < 2) return;
    xx_ += x * x * dt;
    xy_ += x * y * dt;
    yy_ += y * y * dt;
    if (x > 0) positive_ += x * dt;
    else negative_ -= x * dt;
    ++samples_;
  }
  bool finish(float& coupling) const {
    if (samples_ < 40 || positive_ < 3 || negative_ < 3 || xx_ < 20) return false;
    const float fit = (float)(xy_ / xx_);
    const double residual = yy_ - xy_ * xy_ / xx_;
    if (!std::isfinite(fit) || std::fabs(fit) > 2 || residual > .12 * (xx_ + yy_)) return false;
    coupling = fit;
    return true;
  }

 private:
  double xx_ = 0, xy_ = 0, yy_ = 0;
  float positive_ = 0, negative_ = 0;
  uint32_t samples_ = 0;
};

}  // namespace GunMouse
