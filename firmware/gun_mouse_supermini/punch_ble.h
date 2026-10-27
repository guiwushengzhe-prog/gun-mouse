#pragma once
#include <BLE2902.h>
#include <BLECharacteristic.h>
#include <BLEService.h>
#include <atomic>
#include <cstring>
#include <esp_random.h>
#include "punch_logic.h"
#include "imu_logic.h"

namespace GunMouse {
class PunchBle {
 public:
  static constexpr char kEvent[] = "a38b0006-62da-4c13-9f07-908d8b921571";
  static constexpr char kConfig[] = "a38b0007-62da-4c13-9f07-908d8b921571";
  void begin(BLEService* service, std::atomic<bool>* authenticated) {
    authenticated_ = authenticated; session_ = esp_random();
    event_ = service->createCharacteristic(kEvent, BLECharacteristic::PROPERTY_NOTIFY);
    subscription_ = new BLE2902(); event_->addDescriptor(subscription_);
    auto config = service->createCharacteristic(kConfig, BLECharacteristic::PROPERTY_WRITE |
        BLECharacteristic::PROPERTY_WRITE_ENC | BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_READ_ENC);
#if defined(CONFIG_BLUEDROID_ENABLED)
    config->setAccessPermissions(ESP_GATT_PERM_WRITE_ENCRYPTED | ESP_GATT_PERM_READ_ENCRYPTED);
    subscription_->setAccessPermissions(ESP_GATT_PERM_WRITE_ENCRYPTED | ESP_GATT_PERM_READ_ENCRYPTED);
#endif
    config->setCallbacks(new ConfigCallbacks(*this));
  }
  void observe(const ImuSample& s, Vec3 bias, uint32_t sample_us, bool ready) {
    if (!allowed_ || !ready) { detector_.reset(); return; }
    if (detector_.observe(sample_us, norm3({s.gx-bias.x,s.gy-bias.y,s.gz-bias.z}),
                          norm3({s.ax,s.ay,s.az}), allowed_ && ready)) {
      ++sequence_; pending_ = true; event_at_ = millis();
      strength_ = (uint16_t)std::fmin(65535.0f, norm3({s.ax,s.ay,s.az}) * 1000.0f);
    }
  }
  // 放在原鼠标报告发送之后；只推新事件和每秒一次心跳，不重试旧事件。
  void service(bool ready) {
    const uint32_t now = millis();
    uint8_t config[8]; bool changed;
    portENTER_CRITICAL(&mux_);
    changed = changed_; changed_ = false; memcpy(config, config_, 8);
    portEXIT_CRITICAL(&mux_);
    if (changed) {
      enabled_ = config[1]; epoch_ = get16(config+6); lease_at_ = now;
      detector_.configure(enabled_, get16(config+2), get16(config+4));
      pending_ = false; heartbeat_at_ = now - 1000u;
    }
    const bool next = authenticated_->load() && subscription_->getNotifications() &&
                      enabled_ && (uint32_t)(now-lease_at_) < 15000u && ready;
    if (!next || !allowed_) { detector_.reset(); pending_ = false; }
    allowed_ = next;
    if (!authenticated_->load() || !subscription_->getNotifications()) return;
    if ((uint32_t)(now-last_sent_) < 20u) return;
    if (pending_ && (uint32_t)(now-event_at_) > 120u) pending_ = false;
    if (!pending_ && (uint32_t)(now-heartbeat_at_) < 1000u) return;
    uint8_t packet[20] = {1, (uint8_t)(pending_ ? 1 : 0)};
    put16(packet+2, (ready ? 1u : 0u) | (allowed_ ? 2u : 0u));
    put32(packet+4, session_); put32(packet+8, sequence_); put32(packet+12, now);
    put16(packet+16, pending_ ? strength_ : 0); put16(packet+18, epoch_);
    event_->setValue(packet, sizeof(packet)); event_->notify();
    pending_ = false; last_sent_ = heartbeat_at_ = now;
  }
 private:
  static uint16_t get16(const uint8_t* p) { return (uint16_t)p[0] | ((uint16_t)p[1]<<8); }
  static void put16(uint8_t* p, uint16_t v) { p[0]=v; p[1]=v>>8; }
  static void put32(uint8_t* p, uint32_t v) { for (int i=0;i<4;++i) p[i]=v>>(8*i); }
  class ConfigCallbacks : public BLECharacteristicCallbacks {
   public:
    explicit ConfigCallbacks(PunchBle& owner) : o_(owner) {}
    void onWrite(BLECharacteristic* c) override {
      if (!o_.authenticated_->load()) return;
      const String raw = c->getValue(); if (raw.length()!=8) return;
      const auto p = (const uint8_t*)raw.c_str();
      if (p[0]!=1 || p[1]>1 || get16(p+2)<1300 || get16(p+2)>3000 ||
          get16(p+4)<250 || get16(p+4)>2000) return;
      portENTER_CRITICAL(&o_.mux_);
      // 相同租约续期不清空冷却/重新解锁；只刷新存活时间。
      o_.changed_ = o_.changed_ || memcmp(o_.config_,p,8)!=0;
      memcpy(o_.config_,p,8); o_.lease_at_ = millis();
      portEXIT_CRITICAL(&o_.mux_);
    }
    void onRead(BLECharacteristic* c) override {
      if (!o_.authenticated_->load()) return;
      uint8_t value[8]; portENTER_CRITICAL(&o_.mux_); memcpy(value,o_.config_,8); portEXIT_CRITICAL(&o_.mux_);
      c->setValue(value,8);
    }
   private: PunchBle& o_;
  };
  BLECharacteristic* event_ = nullptr; BLE2902* subscription_ = nullptr;
  std::atomic<bool>* authenticated_ = nullptr;
  PunchDetector detector_;
  portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
  uint8_t config_[8] = {1,0,8,7,244,1,0,0};
  bool changed_ = false, enabled_ = false, allowed_ = false, pending_ = false;
  uint16_t epoch_ = 0, strength_ = 0;
  uint32_t session_ = 0, sequence_ = 0, event_at_ = 0, heartbeat_at_ = 0, last_sent_ = 0;
  std::atomic<uint32_t> lease_at_{0};
};
}  // namespace GunMouse
