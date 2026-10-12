# PCB 制造与手焊接线说明

本文件对应冻结配置 `carrier-config.json`，SHA256 为 `730ba00d1d0590381b81cf3021c8e8dff3583758a3b714f3035dd419f2aa9f00`。控制器为 TENSTAR 常见 ESP32-S3 SuperMini，参考特征为 ESP32-S3FH4R2、23.5×18mm、两侧各9孔、背面 B+/B−/BOOST；惯性模块为 GY-601N1 / LSM6DSV16X。**实际采购板必须核对型号、针脚和电源路径，不能只凭 SuperMini 名称套用。**

## 制板文件和规格

- 制造文件：[Gerber ZIP](gun-mouse-supermini-carrier-Gerber.zip)；原生编辑文件：[KiCad PCB](gun-mouse-supermini-carrier.kicad_pcb)。使用 ZIP 内板框、铜层、阻焊、丝印及钻孔文件完整制板，不从截图重画。
- 嘉立创下单版：[JLC Gerber ZIP](gun-mouse-supermini-carrier-JLC-Gerber.zip)。做法是用嘉立创EDA专业版 v4.1.66 导入上面的 KiCad PCB，再原生导出（工程见 [jlceda/](jlceda/gun-mouse-supermini-carrier.eprj2)），两份 ZIP 二选一上传。逐层比对结果：铜层、阻焊、板框和 90 个钻孔（含 3 个 D2FC 长圆孔）与 KiCad 版一致；6 个非金属化孔在铜层多了与孔径等大的铜盘，钻孔后会被完全钻掉。丝印只改了字号：EDA 默认字体同字号显示偏小，因此统一放大，实际字高约 0.86 mm，原版为 0.8 mm，位置不变。EDA 规则检查报出的覆铜间距 0.2505 mm（小于 10 mil）和过孔孔径 0.3 mm 两类问题，是导入规则换算造成的，几何以 KiCad DRC 为准。
- 板材采用常规 FR-4，外接矩形 **52×82mm**，一侧带缺口；以 `Edge.Cuts` 的真实轮廓为准，不能做成实心矩形。板厚 **1.6mm、2层、1oz铜**。
- 主板不做工厂 SMT。摇杆、右键微动、电阻、电容和导线在本板手焊；SuperMini 与 GY-601N1 购买现成模块，不在本载板上复制它们的贴片电路。
- 安装孔 H1–H4 为 Ø2.4mm 非金属化孔；摇杆定位孔同样为非金属化孔。器件/焊线通孔按钻孔文件做金属化，D2FC 的长圆孔也按原制造文件加工，不能擅自换成更小圆孔。
- M2 安装孔中心采用整机 X/Z 坐标：H1=(-12,36)、H2=(-56,36)、**H3=(-51,-4)**、H4=(-27,-27)。坐标与 KiCad 图的屏幕坐标不同：`Kx=-X-3，Ky=45-Z`，单位均为毫米。

物料见 [BOM.csv](BOM.csv)，接线机器表见 [wiring.csv](wiring.csv)，逐焊盘网络见 [circuit-netlist.json](circuit-netlist.json)，装配位置见 [carrier-assembly-map.svg](carrier-assembly-map.svg)。生成器检查见 [electrical-report.json](electrical-report.json)；本次独立核对及实板边界见 [electrical-independent-review.md](electrical-independent-review.md)。

## 采购尺寸与装前试配

|元件|数量/阻值|必须满足的尺寸|
|---|---|---|
|轴向 THT 电阻|8枚：3.3kΩ×3、510Ω×1、100kΩ×4|本体长≤6.4mm、直径≤2.6mm；弯脚后的孔中心距7.62mm。100k分压建议选1%电阻。|
|THT 陶瓷电容|7枚，全部100nF，即0.1µF|脚距2.54mm；本体宽≤6mm、厚≤2mm、焊后安装高度≤7mm。无极性。|
|裸摇杆|Alps RKJXV1224005×1|直接插件，不采用带模块板的 DZYJ 摇杆。核对全部电气脚、固定脚、定位柱与孔位。|
|右键微动|Omron D2FC-F-7N(20M)×1|直接插件，脚距5.08mm；核对 COM、NO 与 dummy固定脚。|
|扳机微动|Omron SS-01GL13 焊片版×1|固定在独立打印支架，COM/NO两线到载板；不要买带 `-2` 的 PCB针脚版来代替支架指定版本。|

采购电容时同时检查厚度，不采用仅宽度和标称容量相同的更厚器件。模块拆掉会干涉结构的高排针后直接焊细绝缘线；不使用杜邦插头或高排母。焊线端子组的孔距只用于本载板焊接，**不是模块排针封装，不要按它猜模块插针间距，也不要强行直插模块。**

焊接前用 KiCad 以 **1:1** 打印板框、孔位及器件位置，或按实际尺寸打印装配图；关闭“适应页面”缩放。先量 H1/H2 孔中心距应为44mm，再用电阻脚距7.62mm、D2FC相邻脚距5.08mm交叉检查比例。把实物放到纸图上，再在未焊光板上轻放核对引脚/定位柱。装配 SVG 用作位置和编号参考；未经标尺确认不能把显示器上的尺寸当实物尺寸。

## 主板插件与无极性元件

元件安装在配置顶面，即整机 +Y 方向的一面；按装配图的器件编号，不按文字朝向猜孔。先装低矮电阻，再装电容，试配摇杆和右键微动后焊接。电阻、电容应贴合其指定的外形空间，不能立焊后增加高度。

**C_RAIL 焊前将引脚成形，使陶瓷本体向 -X（远离 H4 螺母）偏移至少 0.3mm**，焊盘位置保持不变，安装高度仍不超过 7mm；装入 H4 螺母后检查两者有可见空隙，不靠拧紧螺母挤开电容。H4 树脂夹帽已经局部让位，但螺母仍需要这条本体偏移条件。

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
|J_TRIG / 1|GND|SS-01GL13 COM公共端。|
|J_TRIG / 2|TRIG|SS-01GL13 NO常开端；NC悬空。|
|J_TOUCH / 1|TOUCH_ELECTRODE|扳机绝缘盖下的铜箔电极；载板已串联510Ω。|
|J_TOUCH / 2|GND|可选触摸线屏蔽端；无屏蔽线时留空，**不能接同一铜箔**。|
|J_BAT / 1|BAT_RAW|带保护的1S锂电池正极。|
|J_BAT / 2|GND|电池负极。|
|J_SWITCH / 1|BAT_RAW|外置SPST的一个开关端。|
|J_SWITCH / 2|BAT_SW|同一SPST的另一个开关端；两个端子间只通过开关通断。|
|J_MODULE_BAT / 1|BAT_SW|SuperMini**专属 B+电池焊盘**，不能改接5V脚。|
|J_MODULE_BAT / 2|GND|SuperMini专属 B−电池焊盘/GND。|
|J_MODULE_RAIL / 1|VBUS_SHARED|SuperMini标注5V的共享轨焊点，**只取电压检测线**；不是另接电池或外部电源的入口。|

GY使用芯片接口，PS保持默认悬空；SA0/CS由模块原电路配置，载板无需再焊上拉。不要把SDA/SCL误接到模块另一侧 MCU接口的DT/RC；INT1/INT2不接，固件轮询。GPIO3/43/44和原生USB GPIO19/20无需接载板。触摸线尽量短并固定，远离电源和按钮线束，铜箔由绝缘盖覆盖；TOUCH不另加上拉、下拉或100nF电容。

## 电池开关、USB与充电使用

本版接线为：保护电池正极→BAT_RAW→外置SPST→BAT_SW→SuperMini B+。负极共地；ADC检测取开关后的BAT_SW。使用满充4.2V的带过充/过放/过流保护的1S锂电包，电池实际外皮、保护板与线头尺寸另按[外壳说明](../shell/README.md)试放。BOOST 默认开放，默认约100mA来自同型参考资料；是否短接 BOOST 提高充电电流，按[外壳说明的充电一节](../shell/README.md#充电)实测电流和温度后决定，并核对实际板的充电芯片及电池允许值。

参考SuperMini把B+经肖特基二极管送到USB/5V共享轨，板上没有USB输入反向隔离。按以下操作：

1. 接电脑烧录前将电池开关置OFF，再插USB；拔USB后再置ON。
2. 电池ON时充电用**已通电**的USB墙充/稳定5V电源；关闭或断开这个外部电源前先将电池开关置OFF，避免电池给未供电USB端回馈。
3. 电池开关OFF同时断开充电和放电；USB插着时整机仍可能运行。完全断电需要OFF并拔USB。这个开关不改变固件的触摸/鼠标交互规则。

5V脚在电池运行时也可能有约电池电压减二极管压降，因此GPIO10读的是共享轨模拟电压，用4.5V/4.3V迟滞初值推断外部5V，不能用数字高低判断USB，更不能用它判断正在充电或充满。电池OFF+USB供电时，BAT_SW/B+可能被空载充电器拉到约4.2V；此时不是电池真实电压。操作限制和固件深睡不能代替硬件反向隔离或电池保护。

## 手焊后检查与首件验证

先在断电状态查焊接桥连、线号和极性，用万用表核对3V3/GND、B−/GND、5V/USB VBUS以及B+到共享轨的二极管方向；实际采购模块若与参考电路不同，先重新核对该版本，不能通电试错。逐个测右键和扳机的COM/NO：释放断开、动作导通；检查D2FC dummy脚仍为空网。检查SPST置OFF确实隔离电池正极，焊线有绝缘和应力固定。

按 [固件说明](../firmware/README.md) 先断电池、经SuperMini自身USB烧录，再验证3V3、两组分压、摇杆两轴及中键、右键、扳机、GY芯片读取和触摸许可。电池ON运行及充电分别按上述供电条件操作；首件检查实际充电电流、终止、低电BLE峰值下3V3、USB切换和触摸误触。不能把编译或电脑逻辑测试当作这些实测已经通过。

制造检查以 [DRC报告](drc-report.json) 和 [构建报告](build-report.json) 对应的实际PCB校验值为准。此包没有KiCad原理图；DRC不等同于原理图ERC，也不能因为 `schematic_parity` 为空就宣称原理图/PCB网表一致性检查通过。网络定义与实际焊盘的核对范围见独立电气报告。
