#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>

namespace GunMouse {

struct RuntimeStatus {
  uint32_t window_ms = 0, loop_max_us = 0, imu_gap_max_us = 0;
  uint32_t imu_samples = 0, imu_errors = 0, reports = 0, rejected = 0;
  uint32_t link_us = 0;
  int notify_error = 0;
};

struct ButtonStatus {
  bool raw_left = false;
  uint8_t observed = 0, accepted = 0;
  uint16_t presses = 0, releases = 0, accepted_presses = 0, accepted_releases = 0;
  uint16_t queued = 0, overflows = 0;
};

// 扩展回报独占一个只读蓝牙特征，避免把原升级状态拼到512字节以上。
struct DeviceStatus {
  bool joy_enabled = false, joy_ready = false;
  int raw_x = 0, raw_y = 0, center_x = 2048, center_y = 2048;
  float joy_speed = 1200, sensitivity = 64;
  uint32_t center_revision = 0, command_sequence = 0;
  uint32_t uptime_ms = 0;
  uint8_t reset_reason = 0;
  bool middle = false, imu_ready = false;
  bool imu_always = false;
  int node_mv = -1;  // 开关后的电池连接点采样；不是充电判据。
  const char* command = "";  // 主循环认可的命令名称，不含用户原始文本。
  RuntimeStatus runtime;
  ButtonStatus buttons;
};

inline bool formatDeviceStatus(const DeviceStatus& s, char* out, size_t capacity) {
  if (!capacity) return false;
  // 现有载板没有充电状态反馈线，charge=-1始终表示未知；不能按电压编造充电/充满。
  const int length = std::snprintf(out, capacity,
      "{\"project\":\"gunmouse\",\"schema\":1,\"joy\":{\"enabled\":%u,\"ready\":%u,"
      "\"raw\":[%d,%d],\"center\":[%d,%d],\"speed\":%.2f,\"rev\":%lu,\"middle\":%u},"
      "\"power\":{\"mv\":%d,\"charge\":-1},\"sens\":%.2f,\"imu_ready\":%u,\"seq\":%lu,\"cmd\":\"%s\","
      "\"perf\":{\"ms\":%lu,\"loop_us\":%lu,\"gap_us\":%lu,\"imu\":%lu,\"i2c\":%lu,\"sent\":%lu,\"fail\":%lu,"
      "\"link_us\":%lu,\"err\":%d},"
      "\"btn\":[%u,%u,%u,%u,%u,%u,%u,%u,%u],\"boot\":[%lu,%u],\"always\":%u}",
      (unsigned)s.joy_enabled, (unsigned)s.joy_ready, s.raw_x, s.raw_y, s.center_x, s.center_y,
      s.joy_speed, (unsigned long)s.center_revision, (unsigned)s.middle, s.node_mv,
      s.sensitivity, (unsigned)s.imu_ready, (unsigned long)s.command_sequence, s.command,
      (unsigned long)s.runtime.window_ms, (unsigned long)s.runtime.loop_max_us,
      (unsigned long)s.runtime.imu_gap_max_us, (unsigned long)s.runtime.imu_samples,
      (unsigned long)s.runtime.imu_errors, (unsigned long)s.runtime.reports,
      (unsigned long)s.runtime.rejected, (unsigned long)s.runtime.link_us, s.runtime.notify_error,
      (unsigned)s.buttons.raw_left, (unsigned)s.buttons.observed,
      (unsigned)s.buttons.presses, (unsigned)s.buttons.releases,
      (unsigned)s.buttons.accepted_presses, (unsigned)s.buttons.accepted_releases,
      (unsigned)s.buttons.queued, (unsigned)s.buttons.overflows, (unsigned)s.buttons.accepted,
      (unsigned long)s.uptime_ms, (unsigned)s.reset_reason, (unsigned)s.imu_always);
  if (length < 0 || (size_t)length >= capacity) { out[0] = 0; return false; }
  return true;
}

}  // namespace GunMouse
