# TENSTAR 常见 ESP32-S3 SuperMini：安装接口证据

核对日期：2026-10-07。目标是正面两排各 9 孔、背面 B+/B− 大焊盘、GPIO48 RGB LED、底部陶瓷天线的 ESP32-S3FH4R2 板。未收到用户实板，本文件记录公开资料能确认的部分以及 CAD 暂定包络。

## 尺寸与证据等级

| 项目 | 值 | 证据 / 使用边界 |
| --- | --- | --- |
| PCB 长 × 宽 | 23.50 × 18.00 mm | TENSTAR 原卖家尺寸图和 Nologo 尺寸图一致；尺寸箭头量 PCB，不包含 USB 壳前伸。 |
| 两列孔数 | 各 9 个 | 原卖家引脚图和实物图一致。 |
| 同列首末孔中心距 | 20.32 mm | Nologo 机械图明确标注。 |
| 同列孔距 | 2.54 mm | 20.32 / 8 = 2.54；可作为排针规则网格。 |
| 两列孔中心距 | 暂定 15.24 mm | 社区 KiCad 封装 x=±7.62；ESPboards 对比文章同值。一手尺寸图没有标注，须量用户实板。 |
| 首孔到 USB 一端 PCB 边缘 | 暂定 1.59 mm | 社区封装以 PCB 中心为原点，长 23.5、首孔 y=-10.16 得 1.59；须实测。 |
| USB 壳向 PCB 前方突出 | 照片估算约 2.1 mm；CAD 保守预留 2.5 mm | Nologo 机械渲染与卖家实物图可见前伸，没有尺寸标注。2.5 是设计预留，不能写成厂家尺寸。 |
| PCB 厚 | CAD 暂定 1.6 mm | 未找到该 TENSTAR 批次可靠侧视标注，须实测。 |
| PCB 顶面到最高元件 | CAD 暂定 3.5 mm | 最高件预计 USB 壳；没有该版可靠高度尺寸。须量 USB 壳、BOOT/RESET、天线和焊点。 |
| PCB 底面下方焊点/线缆占位 | 当前 CAD 预留 2.0 mm | 对应冻结配置的 `back_wire_allowance`，不是厂家尺寸；背面 B+/B− 引线、绝缘及弯折一起计入，到货焊好后实测。 |

## 物理引脚顺序

以下观察方向固定为 **元件正面朝观察者、USB-C 在上、陶瓷天线在下**。两列从上向下读。

| 行 | 左列 | 右列 |
| --- | --- | --- |
| 1 | TX / GPIO43 | 5V |
| 2 | RX / GPIO44 | GND |
| 3 | GPIO1 | 3V3 (OUT) |
| 4 | GPIO2 | GPIO13 |
| 5 | GPIO3 | GPIO12 |
| 6 | GPIO4 | GPIO11 |
| 7 | GPIO5 | GPIO10 |
| 8 | GPIO6 | GPIO9 |
| 9 | GPIO7 | GPIO8 |

这个顺序由 TENSTAR 彩色引脚图、Nologo 原图、NZN 卖家实物图共同支持。TX/RX 对应 GPIO43/44 由 ESP32-S3 UART0 定义及 NZN 引脚表交叉确认。原卖家上方的 CPU、SRAM、GPIO 数量文字混用了 C3 参数，应以板上 ESP32-S3FH4R2 标记和具体引脚图为准。

GPIO48 接板载 RGB 和蓝色 LED，背面额外 GPIO 是细焊盘，不作为本轮 2.54 mm 排针接口。B+/B− 位于背面靠 USB 一端；从背面看左侧是 B+、右侧是 B−，翻板时注意镜像，接线前核对丝印和导通。背面还有 BOOST 焊桥，默认保持开路。

## 手焊与机械固定建议

- 选未焊排针的开发板；本版采用独立骨架板边支撑、前角止挡和可拆压框固定 SuperMini，与载板之间直接焊柔性绝缘线。不装两排公排针、母排针或杜邦插头，也不将模块直插或直焊到主载板。
- 先在机外焊好背面 B+/B− 引线以及当前接线表指定的 GPIO、电源检测线，核对极性并绝缘。背面焊包、热缩和线束转弯不得超过当前 2.0 mm 包络；不够时重新处理焊包和走线，不能靠压框挤紧线束。具体节点与电池开关顺序以当前载板接线、电源说明为准。
- 开发板从骨架 +X 侧装入，落在板边支撑上，再用压框、前角止挡和两颗 M2×10 杯头内六角螺钉保持。该模块必须先于主载板安装，拆装路径见 `../../assembly.md`；载板采用自己的 M2 固定点。模块 GPIO 孔约 1 mm，不作为 M2 安装孔，螺钉不穿过模块。
- USB 插拔力由模块板边止挡、骨架支撑及接口开口承担，不能靠电气焊线拉住模块。背面焊盘与未使用 GPIO 避免接触支撑或裸导体；保留 BOOT/RESET、USB 插头及焊线的操作空间。
- 陶瓷天线在远离 USB 的短边，安装时让该边靠载板和外壳开放边，附近避免电池、金属件和线束密集贴靠。具体射频间距需要实物 BLE 握持测试，当前公开图没有该组装板的合格天线净空规范。
- 模块在本版可通过拆压框取出；改用排针插座会改变固定和堆叠高度，须另外核验安装包络，不属于当前交付方式。

## 保存的来源

1. TENSTAR 原卖家彩页（已查看真 S3 板图）：<https://ae01.alicdn.com/kf/S7225c36c88804f2fa342ccd5d9098e3aW.png>；本地 `tenstar-original-pinout-dimensions.png`。
2. Nologo 尺寸图：<https://wiki.nologo.tech/assets/img/esp32/esp32s3supermini/dimension.jpg>；本地 `nologo-dimension.jpg`，明确 23.50 / 18.00 / 20.32 mm。
3. Nologo 引脚图：<https://wiki.nologo.tech/assets/img/esp32/esp32s3supermini/esp32s3foot1.jpg>；本地 `nologo-front-back-pinouts.jpg`。
4. NZN 卖家页面：<https://www.nznelectronics.co.nz/products/esp32-s3-supermini-dev-board>；其尺寸图、斜视实物图和 2026 年资料保存在 `nzn-dimensions.png`、`nzn-angled.png`、`nzn-seller-datasheet-v3.pdf`。资料有供应批次说明，不作为 TENSTAR 电源电路的唯一依据。
5. 社区封装发布帖：<https://www.reddit.com/r/esp32/comments/1r6h63m/i_made_a_esp32s3supermini_footprint/>；公开文件 <https://drive.google.com/file/d/1Ia2y5KgLuTCjiLleW4krdE9uNQLiYWtD/view>，本地 `community-ESP32-S3-SuperMini.kicad_mod`。文件有 GPIO13 y=-2.50 mm 的 0.04 mm 网格笔误，**不能原样用于生产**。新载板应独立使用正确 2.54 mm 网格。
6. ESPboards 对比文章：<https://www.espboards.dev/blog/esp32-super-mini-comparison/>，提供 2.54 mm 孔距和 15.24 mm 行距的二手交叉资料。
7. Nologo 论坛公开 STEP 讨论：<https://chat.nologo.tech/d/113>。旧链接和新 `/ESP32-S3-Supermini/STEP/` 链接均已尝试，资料服务器返回 HTTP 503；没有取得 STEP，不能宣称完成厂家 3D 尺寸核验。

制造前至少量：PCB 长宽厚、两排中心距、首孔偏移、孔径、USB 前伸和壳高、焊好背面引线与绝缘后的最高点、板边止挡/压框接触与插入路径、USB 插头外壳和按钮操作空间。
