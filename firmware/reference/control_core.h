#pragma once

#include <cmath>
#include <cstdint>

// 硬件无关的交互核心；尚未接入触摸采样、传感器驱动和蓝牙发送。
// 触摸检测/按键去抖由采样层完成。latest_imu_sequence 必须是传感器队列
// 当前尾部序号；重新允许体感时，从此序号之后的样本开始。
namespace GunMouse {

struct Report {
  bool connected;
  uint8_t buttons;  // 位0左键、位1右键、位2中键。
  float x;
  float y;
};

class ControlCore {
 public:
  void setInputs(bool connected, bool touched, bool imu_ready,
                 uint8_t physical_buttons, uint64_t latest_imu_sequence) {
    if (connected && !connected_) neutral_pending_ = true;
    if (!connected) {
      clearAllMotion();
      neutral_pending_ = false;
    }
    const bool new_gate = connected && touched && imu_ready;
    if (!new_gate || new_gate != imu_gate_) {
      gyro_x_ = gyro_y_ = 0;
      if (latest_imu_sequence > last_imu_sequence_) {
        last_imu_sequence_ = latest_imu_sequence;
      }
    }
    connected_ = connected;
    imu_gate_ = new_gate;
    buttons_ = physical_buttons & 0x07;
  }

  void offerImu(uint64_t sequence, float x, float y) {
    if (sequence <= last_imu_sequence_) return;
    last_imu_sequence_ = sequence;
    if (imu_gate_ && std::isfinite(x) && std::isfinite(y)) {
      gyro_x_ += x;
      gyro_y_ += y;
    }
  }

  void offerJoystick(float x, float y) {
    // 摇杆移动不由触摸或惯性传感器状态控制。
    if (connected_ && std::isfinite(x) && std::isfinite(y)) {
      joy_x_ += x;
      joy_y_ += y;
    }
  }

  Report takeReport() {
    if (!connected_) {
      clearAllMotion();
      return {false, 0, 0, 0};
    }
    if (neutral_pending_) {
      neutral_pending_ = false;
      clearAllMotion();
      return {true, 0, 0, 0};  // 每次连接先发全释放，清除前连接状态。
    }
    Report result{true, buttons_, joy_x_ + gyro_x_, joy_y_ + gyro_y_};
    clearAllMotion();
    return result;
  }

 private:
  void clearAllMotion() { joy_x_ = joy_y_ = gyro_x_ = gyro_y_ = 0; }
  bool connected_ = false;
  bool imu_gate_ = false;
  bool neutral_pending_ = false;
  uint8_t buttons_ = 0;
  uint64_t last_imu_sequence_ = 0;
  float gyro_x_ = 0;
  float gyro_y_ = 0;
  float joy_x_ = 0;
  float joy_y_ = 0;
};

// IO2 必须用校准后的模拟电压判断；这些门限是首轮实现初值。
// 这只解决数字高电平裕量，不解决关机时外部输入的电气隔离。
class UsbDetector {
 public:
  bool updateMillivolts(float millivolts) {
    if (!std::isfinite(millivolts)) { present_ = false; return false; }
    if (millivolts >= 1500) present_ = true;
    else if (millivolts <= 1200) present_ = false;
    return present_;
  }
 private:
  bool present_ = false;
};

}  // namespace GunMouse
