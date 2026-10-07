# TENSTAR 常见 ESP32-S3 SuperMini 的电源与引脚核对

本方案指定 **ESP32-S3FH4R2、PCB 23.5×18 mm、两侧各9孔、背面 B+/B− 与 BOOST** 的常见板型。FH4R2 为4 MB Flash、2 MB PSRAM。不同厂商把不同电路称为 SuperMini，采购须核对实物和背面焊盘；本文没有把 C3 图或 XIAO 的电源路径套用到 S3。

## 引脚

USB在上、元件面朝自己：

|位置，从上到下|左排|右排|
|---|---|---|
|1|TX / GPIO43|5V|
|2|RX / GPIO44|GND|
|3|GPIO1|3V3 OUT|
|4|GPIO2|GPIO13|
|5|GPIO3|GPIO12|
|6|GPIO4|GPIO11|
|7|GPIO5|GPIO10|
|8|GPIO6|GPIO9|
|9|GPIO7|GPIO8|

原卖家图 `tenstar-s3-pin-dim.png` 和 NOLOGO 原理图两侧 Header9 一致。USB D−/D+ 使用19/20，RGB和普通LED共用48；背面测试焊盘不是手焊载板必须使用的引脚。GPIO0为BOOT，3/45/46是启动配置脚，本方案避用。**GPIO3还接有板上100k/100k的VBUS分压**，不得当作完全空闲IO使用。

## 实际原理图与可用边界

NOLOGO公开同型图：`nologo-s3-schematic.png`，2024-10-08，主芯片标ESP32-S3FH4R2、充电TP4054、稳压ME6217C33M5G。该图与TENSTAR照片的引脚、背面B+/B−/BOOST、LED和元件布局相符；没有取得TENSTAR独立受控版本的原理图，**同名不同批次仍须按下列通断测量验收**。

电源连接为：

```
保护电池正极 ── BAT/B+ ── BAT60B肖特基 ── VBUS共同母线 ── ME6217 3.3V LDO
                         USB-C 5V/排针5V ──┘
                 VBUS ── TP4054充电 ── BAT/B+
保护电池负极 ── B−/GND
```

有正常5V USB时，电池二极管反偏，系统负载从USB共同母线取电；充电器BAT端的终止判断可与系统负载分开。这是一个简单二极管供电切换，不是XIAO的MOS电源路径，也不是额外升压。

电池供电时，**5V排针及USB-C VBUS会升到电池电压减二极管压降**，不是稳定5V，也不是0V。图中没有USB输入反向隔离。因此不得承诺电池开着时插入任意关机电脑/未供电USB口都没有回馈。本版不拆SMT、不剪开发板电路：

- 接PC刷机前，把串联B+的机械电池开关置OFF，再插USB；拔USB后再把电池开关置ON。
- 充电用已通电的USB墙充/稳定5V电源，电池开关置ON才能充电；可在该外电源有效时运行。
- 断开或关闭外部USB电源前先关闭电池开关，避免把电池电压送回未供电USB端。
- 开关OFF不会切断USB供电；USB插着时板仍运行。要完全断电须同时拔掉USB。机械开关OFF也切断充电。

没有发现用于断开BAT→VBUS二极管的可逆跳线。**BOOST只改变充电电流，不能充当电池切断或USB隔离。** 给更改开发板的建议之前须明确具体版本焊点；本方案不根据照片猜测割线或拆二极管。

## 充电、低电压与监测

- 默认BOOST不焊，卖家标100mA；保持此默认，不需要用户贴SMT。卖家标短接可提高到300mA且只用于≥500mAh电池。原图10k与可选5.6k并联，不同TP4054供应商公式/热调节有所差别，不能把300mA当精密保证。
- 只用单节3.7V、满充4.2V的**带过充/过放/过流保护的成品锂电包**。TP4054本身不提供电池放电保护，开发板图里没有DW01+双MOS保护电路。
- ME6217是3.3V LDO，经电池肖特基后输入会下降，不能像buck-boost一样用完低压电池。固件先取3.6V电池低压阈值和30秒去抖，在实际BLE峰值下测3V3≥3.0V再调整；软件睡眠不能替代电池保护。
- VBUS需要**ADC**测量而不是GPIO43数字判断，因为电池模式5V脚也有约3.3～4V。载板用ADC1 GPIO10和100k/100k分压，先以4.5V进入/4.3V退出外电状态；ADC误差、低压USB条件需实测校准。
- VBAT通过另一条100k/100k分压从开关后BAT_SW/B+独立读取，不能把共同VBUS减固定压降冒充电池电压。电池开关ON时该节点代表电池；OFF但USB插着时，它是空载充电器BAT输出，可能约4.2V，不能据此判断电池电量。分压接在开关后是为了断电时不从未断开的电池经ADC回灌MCU。
- TP4054 CHRG仅接板上BAT LED，没有接到MCU。固件可报告“外部USB电源存在”和测得电池电压；不能仅据此报告正在充电或充满。

## 到货验收

不接电池、USB和其他外设，用万用表先核对：5V脚与USB-C VBUS直通；B−与GND直通；B+到5V脚为单向二极管；GPIO3到VBUS/GND各约100k（断电电阻读值受其他电路影响）。如与图不同，停止套用本供电说明，保存板正反面照片并检查该版本原图。

接受限电流的5V USB供电，确认3V3；再接保护电池确认B+/B−极性，测电池模式5V脚随电池下降。USB有效时测电池充电电流、端电压和充电终止，BOOST保持未焊。必须检查电池开关OFF能否完全切断B+电流，线束焊点绝缘及机械拉力。

## 来源与文件

- [TENSTAR原卖家针脚/尺寸图](https://ae01.alicdn.com/kf/S7225c36c88804f2fa342ccd5d9098e3aW.png)，本地 `tenstar-s3-pin-dim.png`。图正文混入C3的RISC-V/160MHz文字，本文只使用S3芯片实物、针脚和尺寸标注。
- [NOLOGO产品原页](https://www.nologo.tech/product/esp32/esp32s3/esp32s3supermini/esp32S3SuperMini.html)，本地 `nologo-supermini.html`。页面正文同样存在C3复制错误，不采用其CPU文字。
- [NOLOGO公开S3原理图](https://www.nologo.tech/assets/img/esp32/esp32s3supermini/1.png)，本地 `nologo-s3-schematic.png`。电路结论由实际图核对。
- [TP4054厂家数据手册，LCSC现有PDF](https://datasheet.lcsc.com/datasheet/pdf/0b076ddf91114449998aff7a9f06b7d9.pdf?productCode=C32574)，本地 `TP4054-TopPower-datasheet.pdf`，仅芯片功能证据；实板可能替代供应商。
- [NZN实物商品页](https://www.nznelectronics.co.nz/products/esp32-s3-supermini-dev-board)，本地同目录卖家数据手册与照片，作为同板型交叉核对。
- 机械尺寸/排针/USB突出和未测项另见 `mechanical-evidence.md`。
