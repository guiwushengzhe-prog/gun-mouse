#pragma once

// 由 generate_board_pins.py 从正式主板配置生成，禁止手工改引脚。
// 排针编号依据厂家 YD-ESP32-S3 电路图 V1.4。
// 配置SHA256: 7fe80e1e2e066cec1c183877b920eb5e2993332164d19e1b66ddfe4d19ce390b
namespace GunMouse {
namespace Pins {
constexpr int BTN_R = 15;
constexpr int IMU_INT1 = 10;
constexpr int IMU_INT2 = 11;
constexpr int JOY_SW = 6;
constexpr int JOY_X = 4;
constexpr int JOY_Y = 5;
constexpr int SCL = 9;
constexpr int SDA = 8;
constexpr int TOUCH = 14;
constexpr int TRIG = 16;
constexpr int USB_DN = 19;
constexpr int USB_DP = 20;
constexpr int VBAT_ADC = 1;
constexpr int VBUS_DET = 2;
// VBUS_DET使用模拟采样；触摸S3读数触摸时上升。
}  // namespace Pins
}  // namespace GunMouse
