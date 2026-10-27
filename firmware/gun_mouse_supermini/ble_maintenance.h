#pragma once

#include <Arduino.h>
#include <BLEServer.h>
#include <BLECharacteristic.h>
#include <Update.h>
#include <esp_app_desc.h>
#include <esp_ota_ops.h>
#include <freertos/queue.h>
#include <atomic>
#include <cctype>
#include <cstring>
#include "punch_ble.h"

namespace GunMouse {

// 蓝牙回调只入队；校准和闪存写入统一在主循环执行。
class BleMaintenance {
 public:
  static constexpr char kService[] = "a38b0001-62da-4c13-9f07-908d8b921571";
  static constexpr char kControl[] = "a38b0002-62da-4c13-9f07-908d8b921571";
  static constexpr char kData[] = "a38b0003-62da-4c13-9f07-908d8b921571";
  static constexpr char kStatus[] = "a38b0004-62da-4c13-9f07-908d8b921571";
  static constexpr char kDetails[] = "a38b0005-62da-4c13-9f07-908d8b921571";
  enum Phase : uint8_t { Idle, Receiving, Complete, Failed };

  void begin(BLEServer* server, std::atomic<bool>* authenticated, PunchBle& punch) {
    authenticated_ = authenticated;
    // 当前官方核心的格式化接口只保留9个字符；直接读取描述中的完整32字节。
    const volatile uint8_t* digest = esp_app_get_description()->app_elf_sha256;
    constexpr char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < 32; ++i) {
      const uint8_t byte = digest[i];
      elf_sha256_[i * 2] = hex[byte >> 4];
      elf_sha256_[i * 2 + 1] = hex[byte & 15];
    }
    elf_sha256_[64] = 0;
    queue_ = xQueueCreate(12, sizeof(Packet));
    BLEService* service = server->createService(kService);
    const uint32_t write = BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_ENC;
    auto control = service->createCharacteristic(kControl, write);
    auto data = service->createCharacteristic(kData, write);
    auto status = service->createCharacteristic(kStatus,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_READ_ENC);
    auto details = service->createCharacteristic(kDetails,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_READ_ENC);
#if defined(CONFIG_BLUEDROID_ENABLED)
    control->setAccessPermissions(ESP_GATT_PERM_WRITE_ENCRYPTED);
    data->setAccessPermissions(ESP_GATT_PERM_WRITE_ENCRYPTED);
    status->setAccessPermissions(ESP_GATT_PERM_READ_ENCRYPTED);
    details->setAccessPermissions(ESP_GATT_PERM_READ_ENCRYPTED);
#endif
    control->setCallbacks(new Callbacks(*this, false));
    data->setCallbacks(new Callbacks(*this, true));
    status->setCallbacks(new Callbacks(*this, false));
    details->setCallbacks(new Callbacks(*this, false, true));
    punch.begin(service, authenticated);
    service->start();
  }

  bool active() const { return phase_.load() == Receiving; }
  void setDiagnostic(const char* text) {
    portENTER_CRITICAL(&mux_);
    snprintf(diagnostic_, sizeof(diagnostic_), "%s", text);
    portEXIT_CRITICAL(&mux_);
  }

  void setDetails(const char* text) {
    portENTER_CRITICAL(&mux_);
    snprintf(details_, sizeof(details_), "%s", text);
    portEXIT_CRITICAL(&mux_);
  }

  void service(bool authenticated, void (*command)(const char*)) {
    if (overflow_.exchange(false)) fail(1);
    if (active() && (!authenticated || (uint32_t)(millis() - last_data_ms_) > 30000)) fail(2);
    Packet packet;
    for (int i = 0; i < 4 && queue_ && xQueueReceive(queue_, &packet, 0) == pdTRUE; ++i) {
      if (!authenticated) { fail(3); continue; }
      if (packet.data) {
        if (!active() || packet.length <= 4) { fail(4); continue; }
        const uint8_t* p = packet.bytes;
        const uint32_t offset = (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
                                ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
        const uint32_t size = packet.length - 4;
        if (offset != received_.load() || size > total_.load() - received_.load()) { fail(5); continue; }
        if (Update.write(packet.bytes + 4, size) != size) { fail(6); continue; }
        received_.fetch_add(size);
        last_data_ms_ = millis();
      } else {
        const char* text = (const char*)packet.bytes;
        if (strncmp(text, "BEGIN ", 6) == 0) {
          if (active()) { fail(7); continue; }
          unsigned long bytes = 0;
          char digest[65] = {}, extra = 0;
          const auto partition = esp_ota_get_next_update_partition(nullptr);
          bool valid = sscanf(text, "BEGIN %lu %64s %c", &bytes, digest, &extra) == 2 && strlen(digest) == 64;
          for (char c : digest) if (c && !std::isxdigit((unsigned char)c)) valid = false;
          if (!valid || !partition || bytes < 128 || bytes > partition->size) { fail(8); continue; }
          if (!Update.begin(bytes, U_FLASH)) { fail(9); continue; }
          if (!Update.setSHA256(digest)) { Update.abort(); fail(10); continue; }
          received_ = 0;
          total_ = bytes;
          error_ = 0;
          phase_ = Receiving;
          last_data_ms_ = millis();
          Serial.printf("[无线升级] 开始接收%lu字节，目标分区%s\n", bytes, partition->label);
        } else if (strcmp(text, "END") == 0) {
          if (!active() || received_.load() != total_.load()) { fail(11); continue; }
          if (!Update.end()) { fail(12); continue; }
          phase_ = Complete;
          reboot_ms_ = millis() + 1500;
          Serial.println("[无线升级] 完整校验通过，即将从新分区启动");
        } else if (strcmp(text, "ABORT") == 0) {
          if (active()) Update.abort();
          phase_ = Idle;
          error_ = 0;
          received_ = total_ = 0;
          xQueueReset(queue_);
        } else if (strncmp(text, "CMD ", 4) == 0 && !active() && phase_.load() != Complete) {
          command(text + 4);
        } else {
          fail(13);
        }
      }
    }
    if (reboot_ms_ && (int32_t)(millis() - reboot_ms_) >= 0) ESP.restart();
  }

 private:
  struct Packet { bool data; uint16_t length; uint8_t bytes[245]; };
  class Callbacks : public BLECharacteristicCallbacks {
   public:
    Callbacks(BleMaintenance& owner, bool data, bool details = false)
        : owner_(owner), data_(data), details_(details) {}
    void onWrite(BLECharacteristic* characteristic) override { owner_.enqueue(characteristic, data_); }
    void onRead(BLECharacteristic* characteristic) override {
      if (details_) owner_.readDetails(characteristic);
      else owner_.read(characteristic);
    }
   private:
    BleMaintenance& owner_;
    bool data_;
    bool details_;
  };

  void enqueue(BLECharacteristic* characteristic, bool data) {
    if (!authenticated_ || !authenticated_->load()) return;
    const String value = characteristic->getValue();
    if (!queue_ || value.length() == 0 || value.length() > 244) { overflow_ = true; return; }
    Packet packet;
    packet.data = data;
    packet.length = value.length();
    memcpy(packet.bytes, value.c_str(), packet.length);
    packet.bytes[packet.length] = 0;
    if (xQueueSend(queue_, &packet, 0) != pdTRUE) overflow_ = true;
  }

  void read(BLECharacteristic* characteristic) {
    if (!authenticated_ || !authenticated_->load()) {
      characteristic->setValue("{\"error\":\"authentication\"}");
      return;
    }
    char diagnostic[sizeof(diagnostic_)];
    portENTER_CRITICAL(&mux_);
    memcpy(diagnostic, diagnostic_, sizeof(diagnostic));
    portEXIT_CRITICAL(&mux_);
    char text[512];
    const auto running = esp_ota_get_running_partition();
    snprintf(text, sizeof(text),
             "{\"project\":\"gunmouse\",\"slot\":\"%s\",\"ota\":%u,\"received\":%lu,"
             "\"total\":%lu,\"error\":%u,\"elf\":\"%s\",\"diag\":%s}",
             running ? running->label : "?", (unsigned)phase_.load(),
             (unsigned long)received_.load(), (unsigned long)total_.load(),
             (unsigned)error_.load(), elf_sha256_, diagnostic);
    characteristic->setValue(text);
  }

  void readDetails(BLECharacteristic* characteristic) {
    if (!authenticated_ || !authenticated_->load()) {
      characteristic->setValue("{\"error\":\"authentication\"}");
      return;
    }
    char text[sizeof(details_)];
    portENTER_CRITICAL(&mux_);
    memcpy(text, details_, sizeof(text));
    portEXIT_CRITICAL(&mux_);
    characteristic->setValue(text);
  }

  void fail(uint8_t error) {
    if (active()) Update.abort();
    error_ = error;
    phase_ = Failed;
    if (queue_) xQueueReset(queue_);
    Serial.printf("[无线升级] 已停止，错误码%u，当前程序分区保留\n", (unsigned)error);
  }

  QueueHandle_t queue_ = nullptr;
  std::atomic<bool>* authenticated_ = nullptr;
  std::atomic<bool> overflow_{false};
  std::atomic<uint8_t> phase_{Idle}, error_{0};
  std::atomic<uint32_t> received_{0}, total_{0};
  uint32_t last_data_ms_ = 0, reboot_ms_ = 0;
  portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
  char diagnostic_[300] = "{}";
  char details_[512] = "{}";
  char elf_sha256_[65] = {};
};

}  // namespace GunMouse
