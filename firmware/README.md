# SuperMini 固件

本轮源码已取消低电自动休眠和外部供电识别，保留电压估算电量，并支持保存摇杆停用状态。编译环境统一为本机已安装的官方3.3.12核心，已完成整套库的编译和最终链接，并通过47项电脑逻辑检查。`bin/` 与 `build-manifest.json` 随本次完整构建更新；实物上传和运行情况单独记录，电脑检查不代表整机验收。

适配 **TENSTAR 两侧各 9 针、芯片标记 ESP32-S3FH4R2 的 ESP32-S3 SuperMini**：4MB Flash、2MB QSPI PSRAM；不要按某些商品文案的 8MB 或按 ESP32-C3 SuperMini 烧录。惯性模块为 GY-601N1 / LSM6DSV16X，3.3V 供电，I2C 地址 0x6A。IMU 中断脚不接，固件轮询。

触摸只控制体感移动，机械扳机/右键/摇杆按下分别为左/右/中键；摇杆不依赖触摸。松开触摸立即清除尚未发送的体感位移，断线不积累动作，重新连接且主机启用报告订阅后首帧全释放。按已认证的绑定客户端保存真实 CCCD 订阅；加密重连可以恢复该客户端的订阅，新配对不自动开订阅。GATT 拒绝通知时保留按键和位移队列重试；通知被栈接收不等于主机应用层确认。没有 Wi-Fi 功能。USB 原生 CDC 只用于烧录和串口设置，固件的鼠标行为不会因 USB 插拔暂停。

## 引脚来源

`../pcb/carrier-config.json` 是载板与固件共同来源。运行 `python generate_board_pins.py` 生成 `gun_mouse_supermini/board_pins.h`，头文件记录整个配置的 SHA256，禁止手改。运行 `python generate_board_pins.py --check` 检查配置是否过期。

| 信号 | GPIO | 用途 |
| --- | ---: | --- |
| JOY_X / JOY_Y | 1 / 2 | ADC1，摇杆轴 |
| JOY_SW | 4 | 低电平有效，中键 |
| SDA / SCL | 5 / 6 | I2C，400kHz |
| TOUCH | 7 | ESP32-S3 原生触摸，触摸时计数上升 |
| TRIG | 8 | 低电平有效，左键 |
| VBAT_ADC | 9 | BAT_SW 经 100kΩ / 100kΩ + 100nF，电池隔离开关之后 |
| VBUS_DET | 10 | 保留旧引脚名称以兼容生成器；本版不连接、不采样 |
| BTN_R | 12 | 低电平有效，右键 |

GPIO3/45/46 启动配置脚不占用。19/20 是开发板内部原生 USB，载板不接。TX43/RX44 保留，本固件 `Serial` 使用原生 USB CDC。

## 电源行为及边界

本版取消外部供电识别和低电自动休眠，不再采样 GPIO10，也没有低电深睡、扳机唤醒或十分钟定时复查。插拔USB仍不暂停或恢复鼠标。

GPIO9 保留电池开关后的 **BAT_SW / SuperMini B+ 节点** 电压读取，电池电压约4秒平滑，蓝牙电量每分钟最多更新一次。只有电池开关打开时，该节点才代表电池端电压；电池开关关闭且USB供电时，空载充电器可能把它拉到约4.2伏，不能把读数当作电池已充满。

电量百分比只是电压估算。软件不再识别外部供电或充电状态，因此充电时不会暂停电量更新，估值可能偏高；串口状态也明确标注这个限制。电池仍需使用原定带保护板的单节锂电池。

右键和摇杆按键使用开发板内部上拉，保留原有按键消抖；扳机仍保留板外导线及外部上拉、滤波。鼠标按键、摇杆和触摸控制方式不变。固件不能改变开发板电源路径或USB回馈，这些仍按载板电源说明处理。

## 可复现编译

需要 Python 3.9+、[Arduino CLI](https://arduino.github.io/arduino-cli/latest/installation/) 和用于纯逻辑检查的 `g++`。官方 ESP32 Arduino 核心锁定为 **3.3.12**，所有 Arduino 库来自该核心，不需要第三方鼠标/IMU库。固件已适配该版本的 BLE 连接参数与 GAP 回调接口。

在仓库根目录运行（Linux、macOS、Windows PowerShell 均使用同一个 Python 脚本）：

```sh
python firmware/build_supermini_firmware.py --install-core
```

如果 Arduino CLI 不在 PATH，用 `--cli /path/to/arduino-cli` 或 Windows `--cli C:/Tools/arduino-cli.exe`。脚本默认在系统临时目录的英文路径建立独立 `data/downloads/user` 和缓存；可用 `--work-dir`、`--arduino-home` 改到自选路径。已有隔离 Arduino CLI 配置时用 `--config-file /path/to/arduino-cli.yaml`。代理环境用 `--proxy http://proxy-address:port`。不设置任何机器特定路径，不覆盖系统 HOME。

没有 g++ 时可以使用 `--skip-host-tests` 编译，交付清单会明确记录逻辑检查被跳过。本次交付的逻辑检查已执行。只检查逻辑：

```sh
python firmware/build_supermini_firmware.py --host-only
```

烧录参数在 `build-config.json`：ESP32S3 Dev Module，4MB Flash，2MB **QSPI** PSRAM，No OTA 2MB App，160MHz，USB Mode Hardware CDC and JTAG，USB CDC On Boot Enabled。启用原生 CDC 的编译约束会避免误把串口配置成物理 UART。

成功编译后输出 `bin/` 下应用、引导、分区表和合并镜像，`build-manifest.json` 记录配置/源码/镜像 SHA256。合并镜像烧录地址为 **0x0**，只适用于上述 4MB Flash 板型。

## 首次烧录与验收

1. 首次烧录先断开电池，连接 SuperMini 自身 USB-C 数据线。在 Arduino IDE 按上面的参数选择板型并打开 `gun_mouse_supermini/gun_mouse_supermini.ino`，或用 Arduino CLI 编译后上传。若未枚举，按住 BOOT 再按 RESET，松开 BOOT 进入 ROM 下载模式；端口以实际枚举为准。

   手动进入下载模式后，原生串口的普通自动复位可能仍停留在下载模式。上传校验通过但没有程序回复时，可按复位键或使用烧录工具的 `--after watchdog-reset` 完成整机复位，再读取状态；参见[乐鑫官方排障说明](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/troubleshooting.html#leaving-download-mode-in-usb-serial-jtag-mode)。

2. 串口 115200 输入 `status`，确认摇杆中心、传感器 ID/校准和 BAT_SW 节点读数。电池开关关闭且USB供电时，B+可能读到空载充电器电压，不能把它当电池电量。静置约3秒完成体感校准，`cal`可重做。
3. 蓝牙搜索 **GunMouse SuperMini**。不触摸时晃动不会移动，但三键和摇杆仍可操作；触摸后体感移动，松开不会补发积压。重连后检查没有按键卡住。
4. 摇杆暂时拆除时，输入 `joy 0` 停用两路轴输入及中键，设置自动保存，重新上电仍保持停用。装回后让摇杆回中，输入 `joy 1` 恢复并取中；`jcenter` 重新取摇杆中位，`jdir` 按串口提示推向光标右、上方向，`jsave` 保存端点。原有参数重置命令不会改变这个独立保存的摇杆安装状态。装壳后用 `status` 看触摸读数，`tp <百分比>` / `tr <百分比>` 调整阈值，`sens <计数/度>` 调灵敏度。
5. 实板验证单电池、USB供电、插拔过渡、低电压无线峰值下的3.3伏电压、估算电量以及触摸抗误触。本次编译和电脑逻辑测试不代替这些实物检查。

Arduino CLI 上传示例（先用脚本完成编译；端口替换成实际 `/dev/ttyACM0` 或 `COM5`）：

```sh
arduino-cli upload --fqbn esp32:esp32:esp32s3:FlashSize=4M,PartitionScheme=no_ota,FlashMode=qio,PSRAM=enabled,CDCOnBoot=cdc,USBMode=hwcdc,UploadSpeed=921600,CPUFreq=160 --port COM5 --input-dir firmware/bin firmware/gun_mouse_supermini
```

若编译使用独立工具链，上传同样加 `--config-file` 指向脚本生成的配置，否则命令可能找不到 ESP32 核心。
