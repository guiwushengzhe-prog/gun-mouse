# PCB 模块装配预览

当前以 `carrier-config.json` 和 `gun-mouse-supermini-carrier.kicad_pcb` 中的实际孔位为准：SuperMini 两排各9针和 GY-601N1 左8右6针直接焊载板，两个模块都在板正面，板间留3毫米。SuperMini 两排中心距暂按 **15.24毫米**，这是用户同意的暂定值，不是实测确认。

摇杆采用用户现有的 **HW-504、34×26毫米、五针间距2.54毫米** 模块，保留现有弯针，按实物照片垂直插进载板；模块板面与载板垂直，摇杆轴沿整机 **−X**，模块向载板背面伸出。五孔从整机Z高到低依次为：GND、3V3、VRX、VRY、SW。删除原Alps裸摇杆的16孔，不改变控制引脚或操作逻辑。

电源开关为用户购买的 **SS12D10 G5**，相邻脚距4.7毫米，使用1.8毫米圆孔、3毫米焊盘；保留原电阻电容数量和宽间隔。背面B+/B−仍各用一根短线接载板。SuperMini天线中央区域在载板两面禁止覆铜、走线和过孔。

**目前只完成结构孔位板，用于查看组装模型；新的布局尚未重新布线。旧制造压缩包、嘉立创工程、检测报告及下方上轮记录均未重新导出，不能用于本轮打板。** 用户先确认装配结构，再继续布线和正式制造导出。

## 上轮制造与焊线记录（未随本次结构更新，不能用于本轮下单）

本文件对应第二代配置 `carrier-config.json`（`supermini-tht-carrier-v2`），板上丝印为 `S3 THT CARRIER v2`，文件校验值见 [制造清单](fabrication-manifest.json)。控制器为 TENSTAR 常见 ESP32-S3 SuperMini，参考特征为 ESP32-S3FH4R2、23.5×18mm、两侧各9孔、背面 B+/B−/BOOST；惯性模块为 GY-601N1 / LSM6DSV16X。**实际采购板必须核对型号、针脚和电源路径，不能只凭 SuperMini 名称套用。**

## 制板文件和规格

- 制造文件：[Gerber ZIP](gun-mouse-supermini-carrier-Gerber.zip)；原生编辑文件：[KiCad PCB](gun-mouse-supermini-carrier.kicad_pcb)。使用 ZIP 内板框、铜层、阻焊、丝印及钻孔文件完整制板，不从截图重画。
- 嘉立创工程：[原生工程](jlceda/gun-mouse-supermini-carrier.eprj2)；对应的嘉立创导出包为 [JLC Gerber ZIP](gun-mouse-supermini-carrier-JLC-Gerber.zip)。以制造清单中列入校验的文件为准，不把第一代的孔数和审查结果沿用到第二代。
- 三维预览：[OBJ 模型](3d/gun-mouse-gen2.obj)与[材质文件](3d/gun-mouse-gen2.mtl)须放在同一目录。由当前 KiCad 工程导出，单位为毫米，包含裸板、孔洞、铜层、阻焊和丝印；不含摇杆、开发板等器件外形。
- 板材采用常规 FR-4，外接矩形 **52×82mm**，一侧带缺口；以 `Edge.Cuts` 的真实轮廓为准，不能做成实心矩形。板厚 **1.6mm、2层、1oz铜**。
- 主板不做工厂 SMT。摇杆、右键微动、电阻、电容和导线在本板手焊；SuperMini 与 GY-601N1 购买现成模块，不在本载板上复制它们的贴片电路。
- 安装孔 H1–H4 为 Ø2.4mm 非金属化孔；摇杆定位孔同样为非金属化孔。器件/焊线通孔按钻孔文件做金属化，D2FC 的长圆孔也按原制造文件加工，不能擅自换成更小圆孔。
- M2 安装孔中心采用整机 X/Z 坐标：H1=(-12,36)、H2=(-56,36)、**H3=(-51,-4)**、H4=(-27,-27)。坐标与 KiCad 图的屏幕坐标不同：`Kx=-X-3，Ky=45-Z`，单位均为毫米。

物料见 [BOM.csv](BOM.csv)，接线表见 [wiring.csv](wiring.csv)，逐焊盘网络见 [circuit-netlist.json](circuit-netlist.json)，实际尺寸孔位图见 [1:1装配图](carrier-assembly-map-1to1.pdf)。文件检查结果见 [electrical-report.json](electrical-report.json)，实物验收范围见本文末尾。

第二代保持板框、四个安装孔及摇杆真实轴心不变。**SW1 改为从 PCB 背面安装，杆朝整机 −Y、打印模型 −Z，供右手拇指在后侧操作。**全部16孔围绕 KiCad 轴心 `(30,22)` 毫米左右镜像，封装标记也翻至背面；保留各端子网络，相关网络重新布线。C_RAIL 本体和两孔向整机 -X 移动0.6毫米，给 H4 螺母让位。电源开关改为直接焊在 J_SWITCH 的三脚直插开关，电池两线直接焊到 J_BAT。

## 采购尺寸与装前试配

|元件|数量/阻值|必须满足的尺寸|
|---|---|---|
|轴向 THT 电阻|8枚：3.3kΩ×3、510Ω×1、100kΩ×4|本体长≤6.4mm、直径≤2.6mm；弯脚后的孔中心距7.62mm。100k分压建议选1%电阻。|
|THT 陶瓷电容|7枚，全部100nF，即0.1µF|脚距2.54mm；本体宽≤6mm、厚≤2mm、焊后安装高度≤7mm。无极性。|
|裸摇杆|Alps RKJXV1224005×1|直接插件，不采用带模块板的 DZYJ 摇杆。核对全部电气脚、固定脚、定位柱与孔位。|
|右键微动|Omron D2FC-F-7N(20M)×1|直接插件，脚距5.08mm；核对 COM、NO 与 dummy固定脚。|
|扳机微动|复用手头的 Omron SS-01GL×1|公共端和常开端通过两根软线接 J_TRIG；使用原生金属摆杆，不新增槽，也不要求更换为 GLD。|
|板载电源开关|品赞 G-Switch SS-12D01-G030×1，嘉立创编号 C5446804|直插三脚，相邻脚距2.5毫米，本体8.8×3.9×3.5毫米、拨柄3毫米；直接焊 J_SWITCH。不要仅凭外观买成孔距不同的型号。|

采购电容时同时检查厚度，不采用仅宽度和标称容量相同的更厚器件。模块拆掉会干涉结构的高排针后直接焊细绝缘线；不使用杜邦插头或高排母。焊线端子组的孔距只用于本载板焊接，**不是模块排针封装，不要按它猜模块插针间距，也不要强行直插模块。**

焊接前按 **1:1** 打印 [装配孔位图](carrier-assembly-map-1to1.pdf)，关闭“适应页面”缩放。先量 H1/H2 孔中心距应为44mm，再用电阻脚距7.62mm、D2FC相邻脚距5.08mm交叉检查比例。孔位图为板顶面俯视，**SW1 必须从板背面套入，顶面焊接，逐一核对16孔；当前只完成文件核对，尚未完成你手头摇杆的实物试插。**在未焊光板上再次轻放核对引脚/定位柱，不能靠压弯器件强行装入。

## 主板插件与无极性元件

除 SW1 外，元件安装在配置顶面，即整机 +Y 方向的一面；SW1 单独安装在背面（整机 −Y）。按装配图的器件编号，不按文字朝向猜孔。先装低矮电阻，再装电容，试配摇杆和右键微动后焊接。电阻、电容应贴合其指定的外形空间，不能立焊后增加高度。

第二代已把 **C_RAIL 的本体与两孔一起向 -X 移动0.6mm**，不再要求沿用第一代引脚偏折的装配办法；安装高度仍不超过7mm。开关 J_SWITCH 由板顶面插入三脚，背面焊接并剪短引脚，不需要额外开关支架。

|编号|数值与连接|
|---|---|
|R_JOY / R_RIGHT / R_TRIG|各3.3kΩ，分别从3V3上拉 JOY_SW / BTN_R / TRIG。|
|R_TOUCH|510Ω，TOUCH_ELECTRODE串联到TOUCH；不是上拉电阻。|
|R_BAT_H / R_BAT_L|各100kΩ，BAT_SW→VBAT_ADC→GND。|
|R_RAIL_H / R_RAIL_L|各100kΩ，VBUS_SHARED→VBUS_DET→GND。|
|C_JOY_X / C_JOY_Y|各100nF，对应JOY_X / JOY_Y到GND。|
|C_JOY_SW / C_RIGHT / C_TRIG|各100nF，对应JOY_SW / BTN_R / TRIG到GND。|
|C_BAT / C_RAIL|各100nF，对应VBAT_ADC / VBUS_DET到GND。|

Alps 库脚网络为：1=GND、2=JOY_X、3=3V3；4=3V3、5=JOY_Y、6=GND；7–10=GND；a/c=JOY_SW、b/d=GND。D2FC库1脚=COM/GND、2脚=NO/BTN_R、3脚空网。**D2FC第三脚在原厂资料中为 dummy无功能固定脚，并非NC；只焊到它自己的独立空网焊盘，不接任何电路。** 外置SS开关则有实际NC端，但本版不用NC。

焊完后剪所有背面引脚和裸露线尾，使它们伸出 PCB 底面 **不超过1mm**；检查剪脚后焊点仍牢固且相邻焊点不桥连。背面不能留长针脚顶住电池、结构夹帽或握持部位。先断开电池和USB再焊接、剪脚或测通断。

## 焊线端子逐脚连接

下表的脚号是**载板该端子组的孔号**，不是模块厂家排针编号。以模块实物的3V3/GND/GPIO/B+/B−/5V标识及已经核对的针脚图逐一连接；载板和模块之间均采用独立焊线。

|载板端子/脚|网络|连接到外部实物|
|---|---|---|
|J_MCU / 1|3V3|SuperMini **3V3输出**；供载板摇杆、按钮上拉与GY模块，不能接5V。|
|J_MCU / 2|GND|SuperMini GND。|
|J_MCU / 3|JOY_X|SuperMini GPIO1。|
|J_MCU / 4|JOY_Y|SuperMini GPIO2。|
|J_MCU / 5|JOY_SW|SuperMini GPIO4。|
|J_MCU / 6|BTN_R|SuperMini GPIO12。|
|J_MCU / 7|TRIG|SuperMini GPIO8。|
|J_MCU / 8|SDA|SuperMini GPIO5。|
|J_MCU / 9|SCL|SuperMini GPIO6。|
|J_MCU / 10|TOUCH|SuperMini GPIO7，原生电容触摸。|
|J_MCU / 11|VBAT_ADC|SuperMini GPIO9，开关后的BAT_SW节点二分之一电压。|
|J_MCU / 12|VBUS_DET|SuperMini GPIO10，共享5V/VBUS轨二分之一电压，模拟采样。|
|J_GY / 1|3V3|GY-601N1 **H2/1 VCC**。|
|J_GY / 2|GND|GY-601N1 **H2/2 GND**。|
|J_GY / 3|SCL|GY-601N1 **H2/3 SCL**。|
|J_GY / 4|SDA|GY-601N1 **H2/4 SDA**。|
|J_TRIG / 1|GND|手头 SS-01GL 的公共端。|
|J_TRIG / 2|TRIG|同一 SS-01GL 的常开端；常闭端悬空。|
|J_TOUCH / 1|TOUCH_ELECTRODE|金属摆杆上的铜箔电极；铜箔与摆杆之间、铜箔与手指之间各一层薄绝缘胶带，载板已串联510Ω。|
|J_TOUCH / 2|GND|可选触摸线屏蔽端；无屏蔽线时留空，**不能接同一铜箔**。|
|J_BAT / 1|BAT_RAW|带保护的1S锂电池正极。|
|J_BAT / 2|GND|电池负极。|
|J_SWITCH / 1|BAT_RAW|板载电源开关的一个外侧脚；不用外接导线。|
|J_SWITCH / 2|BAT_SW|板载电源开关的中间公共脚；与1脚通断控制电池正极。|
|J_SWITCH / 3|空网|另一个外侧脚；只焊到独立焊盘固定，不接任何网络。|
|J_MODULE_BAT / 1|BAT_SW|SuperMini**专属 B+电池焊盘**，不能改接5V脚。|
|J_MODULE_BAT / 2|GND|SuperMini专属 B−电池焊盘/GND。|
|J_MODULE_RAIL / 1|VBUS_SHARED|SuperMini标注5V的共享轨焊点，**只取电压检测线**；不是另接电池或外部电源的入口。|

GY使用芯片接口，PS保持默认悬空；SA0/CS由模块原电路配置，载板无需再焊上拉。不要把SDA/SCL误接到模块另一侧 MCU接口的DT/RC；INT1/INT2不接，固件轮询。GPIO3/43/44和原生USB GPIO19/20无需接载板。触摸线尽量短并固定，远离电源和按钮线束，铜箔由绝缘盖覆盖；TOUCH不另加上拉、下拉或100nF电容。

## 电池开关、USB与充电使用

本版接线为：保护电池正极→J_BAT 1脚/BAT_RAW→板载 J_SWITCH 1、2脚→BAT_SW→SuperMini B+；负极直接焊 J_BAT 2脚并共地。电池不需要插拔接头，也不需要组合键开关机。ADC 检测取开关后的 BAT_SW。使用满充4.2V的带过充/过放/过流保护的1S锂电包，电池实际外皮、保护板与线头尺寸按[底座说明](../shell/README.md)试放。BOOST 默认开放，默认约100mA来自同型参考资料；提高充电电流前核对实际板充电芯片、电池允许值，并实测电流及温度。

参考SuperMini把B+经肖特基二极管送到USB/5V共享轨，板上没有USB输入反向隔离。按以下操作：

1. 接电脑烧录前将电池开关置OFF，再插USB；拔USB后再置ON。
2. 电池ON时充电用**已通电**的USB墙充/稳定5V电源；关闭或断开这个外部电源前先将电池开关置OFF，避免电池给未供电USB端回馈。
3. 电池开关OFF同时断开充电和放电；USB插着时整机仍可能运行。完全断电需要OFF并拔USB。这个开关不改变固件的触摸/鼠标交互规则。

5V脚在电池运行时也可能有约电池电压减二极管压降，因此GPIO10读的是共享轨模拟电压，用4.5V/4.3V迟滞初值推断外部5V，不能用数字高低判断USB，更不能用它判断正在充电或充满。电池OFF+USB供电时，BAT_SW/B+可能被空载充电器拉到约4.2V；此时不是电池真实电压。操作限制和固件深睡不能代替硬件反向隔离或电池保护。

## 手焊后检查与首件验证

先在断电状态查焊接桥连、线号和极性，用万用表核对3V3/GND、B−/GND、5V/USB VBUS以及B+到共享轨的二极管方向；实际采购模块若与参考电路不同，先重新核对该版本，不能通电试错。逐个测右键和扳机的COM/NO：释放断开、动作导通；检查D2FC dummy脚仍为空网。检查SPST置OFF确实隔离电池正极，焊线有绝缘和应力固定。

按 [固件说明](../firmware/README.md) 先断电池、经SuperMini自身USB烧录，再验证3V3、两组分压、摇杆两轴及中键、右键、扳机、GY芯片读取和触摸许可。电池ON运行及充电分别按上述供电条件操作；首件检查实际充电电流、终止、低电BLE峰值下3V3、USB切换和触摸误触。不能把编译或电脑逻辑测试当作这些实测已经通过。

制造检查以 [DRC报告](drc-report.json) 和 [构建报告](build-report.json) 对应的实际PCB校验值为准。此包没有KiCad原理图；设计规则检查不等同于原理图电气规则检查，也不能因为 `schematic_parity` 为空就宣称原理图与电路板网表一致。实际金属化通孔与配置中的网络、孔位、孔径已逐一核对，结果见 [电气检查结果](electrical-report.json)。
