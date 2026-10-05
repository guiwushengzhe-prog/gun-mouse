#include "control_core.h"
#include <cassert>
#include <iostream>
#include <limits>

int main() {
  GunMouse::ControlCore core;
  core.setInputs(true, false, true, 0, 0);
  assert(core.takeReport().buttons == 0);  // 连接首帧全释放。
  core.setInputs(true, false, true, 1, 0);
  core.offerImu(1, 100, 100);
  core.offerJoystick(3, 4);
  auto report = core.takeReport();
  assert(report.buttons == 1 && report.x == 3 && report.y == 4);
  core.setInputs(true, true, true, 1, 10);
  core.offerImu(2, 100, 100);  // 重新触摸前积压的样本应丢弃。
  core.offerImu(11, 1, 2);
  core.offerImu(11, 1, 2);  // 重复样本不再发送。
  report = core.takeReport();
  assert(report.buttons == 1 && report.x == 1 && report.y == 2);
  core.setInputs(true, true, true, 0, 11);
  core.offerImu(12, 2, 3);
  report = core.takeReport();
  assert(report.buttons == 0 && report.x == 2 && report.y == 3);
  core.offerImu(13, 9, 9);
  core.offerJoystick(5, 6);
  core.setInputs(true, false, true, 2, 13);  // 松开立即清体感缓存，保留摇杆。
  report = core.takeReport();
  assert(report.buttons == 2 && report.x == 5 && report.y == 6);
  core.setInputs(true, true, false, 4, 13);  // 传感器未就绪，中键和摇杆仍有效。
  core.offerImu(14, 10, 10);
  core.offerJoystick(1, 1);
  report = core.takeReport();
  assert(report.buttons == 4 && report.x == 1 && report.y == 1);
  core.setInputs(false, true, true, 7, 14);
  core.offerImu(15, 100, 100);
  core.offerJoystick(100, 100);
  report = core.takeReport();
  assert(!report.connected && report.buttons == 0 && report.x == 0);
  core.setInputs(true, true, true, 7, 20);
  report = core.takeReport();
  assert(report.connected && report.buttons == 0 && report.x == 0);
  core.setInputs(true, true, true, 7, 20);
  core.offerImu(21, 2, 3);
  report = core.takeReport();
  assert(report.buttons == 7 && report.x == 2 && report.y == 3);
  core.offerImu(22, std::numeric_limits<float>::quiet_NaN(), 2);
  assert(core.takeReport().x == 0);
  GunMouse::UsbDetector usb;
  assert(!usb.updateMillivolts(0));
  assert(usb.updateMillivolts(2375));  // 4.75V供电分压；不能依赖数字读高。
  assert(usb.updateMillivolts(1350));  // 门限中间保持状态。
  assert(!usb.updateMillivolts(1200));
  assert(!usb.updateMillivolts(std::numeric_limits<float>::quiet_NaN()));
  // USB检测与鼠标控制没有自动停用关系。
  core.setInputs(true, true, true, 1, 22);
  assert(usb.updateMillivolts(2500));
  core.offerImu(23, 2, 3);
  core.offerJoystick(1, 1);
  report = core.takeReport();
  assert(report.buttons == 1 && report.x == 3 && report.y == 4);
  assert(!usb.updateMillivolts(0));
  core.offerImu(24, 1, 1);
  assert(core.takeReport().x == 1);
  std::cout << "交互核心检查通过：触摸/点击独立、缓存清除、摇杆独立、重连释放、模拟USB检测不自动停用。\n";
}
