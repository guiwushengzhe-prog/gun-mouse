#pragma once
#include <cmath>
#include <cstdint>

namespace GunMouse {

// 复用惯性样本。先静稳解锁，再确认持续发力；冷却且再次静稳后才能重触发。
class PunchDetector {
 public:
  void configure(bool enabled, uint16_t strength_mg, uint16_t cooldown_ms) {
    enabled_ = enabled; threshold_ = strength_mg / 1000.0f;
    cooldown_us_ = (uint32_t)cooldown_ms * 1000u;
    reset();
  }
  void reset() { armed_ = false; quiet_ = high_ = have_last_ = false; cooling_ = false; }
  bool observe(uint32_t now, float rate, float acceleration, bool ready) {
    const uint32_t gap = now - last_;
    if (!enabled_ || !ready || !std::isfinite(rate) || !std::isfinite(acceleration)) {
      reset(); return false;
    }
    if (have_last_ && gap > 20000u) { reset(); }
    last_ = now; have_last_ = true;
    const bool still = rate < 50.0f && std::fabs(acceleration - 1.0f) < .20f;
    if (!armed_) {
      if (still) {
        if (!quiet_) { quiet_ = true; quiet_at_ = now; }
        if ((uint32_t)(now - quiet_at_) >= 150000u &&
            (!cooling_ || (uint32_t)(now - fired_at_) >= cooldown_us_)) armed_ = true;
      } else quiet_ = false;
      return false;
    }
    const bool force = acceleration >= threshold_ && rate >= 80.0f;
    if (!force) { high_ = false; return false; }
    if (!high_) { high_ = true; high_at_ = now; }
    if ((uint32_t)(now - high_at_) < 12000u) return false;
    fired_at_ = now; cooling_ = true; armed_ = false; high_ = quiet_ = false;
    return true;
  }
 private:
  bool enabled_ = false, armed_ = false, quiet_ = false, high_ = false;
  bool have_last_ = false, cooling_ = false;
  float threshold_ = 1.8f;
  uint32_t last_ = 0, quiet_at_ = 0, high_at_ = 0, fired_at_ = 0, cooldown_us_ = 500000;
};
}  // namespace GunMouse
