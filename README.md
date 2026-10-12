# 枪型飞鼠

ESP32-S3 SuperMini + 手焊载板 + 打印外壳（EVT-1 轻壳）的体感蓝牙鼠标：扳机是左键、右键微动是右键、摇杆按下是中键；手指摸着扳机上的铜箔时，晃动机身移动光标。

仓库只保留最终版：

| 目录 | 内容 |
|---|---|
| [pcb/](pcb/README.md) | 载板（丝印 `S3 THT CARRIER v1`，52×82 mm，2 层，全直插手焊）：Gerber、KiCad 与嘉立创工程、BOM、焊线表、1:1 装配图、焊接说明 |
| [shell/](shell/README.md) | EVT-1 外壳 7 个打印件（STL / STEP）、要买的东西、装配顺序、扳机校准、充电 |
| [firmware/](firmware/README.md) | SuperMini 固件源码、编译好的镜像（合并镜像烧到 0x0）、烧录与串口调试 |

## 下单

- PCB：把 `pcb/gun-mouse-supermini-carrier-JLC-Gerber.zip` 上传嘉立创（或用 KiCad 导出的 `pcb/gun-mouse-supermini-carrier-Gerber.zip`，二选一）。FR-4、1.6 mm、2 层、1 oz，只做裸板，不要 SMT。
- 外壳：`shell/stl/` 下 7 个 STL。
- 元件：板上元件见 [pcb/BOM.csv](pcb/BOM.csv)，模块、开关、电池、螺丝等见 [外壳说明的采购清单](shell/README.md#要买的东西)。

## 做的顺序

1. 焊载板上的电阻、电容、右键和摇杆，再焊模块飞线：[pcb/README.md](pcb/README.md)
2. 不接电池，只插 SuperMini 的 USB 烧固件、用串口检查：[firmware/README.md](firmware/README.md)
3. 装壳、调扳机、贴触摸铜箔、充电：[shell/README.md](shell/README.md)

## 旧版本

经济型主板、PCB 与外壳 V1、EVT-A、30 g 开放骨架、概念图以及各种生成脚本已从当前目录删除。需要时从提交 `e2848bd` 或更早的历史里取，例如：

```sh
git checkout e2848bd -- experiments/evt1-light-shell
```
