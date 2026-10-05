# 枪型飞鼠：电路板与外壳

**PCB 与外壳 V1（分支 `claude/pcb-shell-v1`）**：已生成首轮可下单的主板（含可掰下的扳机小板）和 6 个打印件。交付件、购买清单、装配顺序见 `deliverables/pcb-shell-v1/README.md`；设计决定与理由见 `docs/PCB与外壳-V1.md`；全部参数在 `config/pcb-shell-v1.json`。本版按"能买到、有原厂图"的原则把 DZYJ 摇杆模块、GY-601N1 模块和未知充电板分别换成主板直焊的 Alps 摇杆、LSM6DSV16X 芯片和板载充电稳压电路。重新生成：依次运行 `scripts/pcb_shell_v1/layout.py`、`build_pcb.py`、`build_shell.py`、`render_views.py`（命令见各脚本开头）。

以下为此前阶段的说明。

已安装并实际验证嘉立创专业版与 CadQuery 的程序联动。当前飞鼠采用 ESP32-S3 内置电容触摸连接铜箔，省掉 TTP223；普通 PS2 五针摇杆及独立机械扳机保持。外形方向已基本接受，当前重点是内部布局。正式制造尺寸尚未冻结，仓库中的矩形板和开口盒仍只是工具验证示例。

历史外观图位于 `concepts/v2`，包括两种外观方向和已取消独立检测板的触摸扳机原理图。设计输入见 `docs/V1-Concept-01-设计输入.md`，官方参数及待测尺寸见 `docs/器件参数与待实测清单.md`，可供后续建模读取的配置见 `config/v1-concept.json`。`concepts/v1` 为保留的旧握把触摸方案，不用于当前设计。

当前内部布局原型位于 `concepts/v3`，包括内部透视、分解安装和线束/触摸关系；`concepts/v2`保留旧外形及独立触摸板原理。内部配置为 `config/internal-layout-v1.json`，说明为 `docs/内部布局原型-V1.md`，可通过 `scripts/build_internal_layout.py` 重新生成概念占位参考。未知尺寸仍保留，不把图作为制造定稿。

用户提供的 ESP32-S3 与 GY-601N1 资料包已解压至 `器件资料/原始资料`，常用图纸位于 `器件资料/参考图纸`，入口见 `器件资料/README.md`。已确认 X 向前、Y 向左、Z 向上的右手坐标系；资料标注尺寸与待测三维占用分别记录。完整资料和原压缩包留在本机，常用图纸、索引、来源校验及设计记录纳入版本管理。

| 工具 | 版本 | 用途与调用路径 |
| --- | --- | --- |
| 嘉立创专业版 | 4.1.66 | 原理图、电路板、布线与设计规则接口；`E:\各种软件\嘉立创专业版4\lceda-pro.exe` |
| Miniforge | 26.7.2-0 | 管理独立运行环境；`E:\GunMouseCAD\Miniforge3` |
| CadQuery | 2.8.0 | 通过代码生成实体外壳与装配；`E:\GunMouseCAD\CadQuery\python.exe` |
| CQ-editor | 0.8.dev0，固定官方提交 | CadQuery 配套图形查看器；独立环境 `E:\GunMouseCAD\CQEditor` |
| CadQuery 环境内的 Python | 3.12.14 | 运行建模脚本，与原有 Python 分开 |

项目和版本库位于 `F:\项目\枪型飞鼠`。工作树（同一版本库的独立工作目录）统一放在项目下的`.worktrees`。本轮内部布局使用`internal-layout-v1`、分支`codex/internal-layout-v1`；此前工具安装与外观探索分别保留在`toolchain`及`concepts-v1`。

`E:\GunMouseCAD` 是永久目录联接（另一个路径入口），指向 `E:\各种软件\枪型飞鼠设计工具`。Miniforge 不接受中文安装路径，所以程序用英文入口调用，文件实际仍在原先指定的软件文件夹。按用户后续指示保留现状，不额外搬移软件。

## 长期三维查看入口

项目根目录中的 `查看板和外壳.lnk` 可双击打开实际模型。快捷方式由 `scripts/setup_preview_shortcut.ps1` 创建，不纳入版本库；查看代码、显示参数和启动配置均纳入 Git（版本控制系统）。

- 左键拖动旋转，滚轮缩放；右侧两个中文对象可分别取消勾选，隐藏板或外壳。
- 默认绿色裸板、半透明外壳，直接读取实际生成的实体文件，保持原始装配位置。
- 工具联动脚本完成模型导出并写入 `geometry-report.json` 后，窗口自动刷新；窗口关闭时，下次双击直接读取最新文件。
- `刷新模型` 可手动刷新；查看脚本保存后的变化由 CQ-editor 原生自动重载处理。
- 以后不必重新制作展示界面。模型更新仍需运行生成脚本；展示窗口本身不会代替建模、布线和验证。

嘉立创自己的板预览位于 **视图 → 3D预览**，可查看板和已经绑定模型的器件。它另有自身外壳预览，但官方资料没有说明能把外部 CadQuery 枪形外壳直接作为完整装配导入，因此完整板壳装配采用 CQ-editor 查看。依据：[嘉立创三维预览](https://prodocs.lceda.cn/cn/pcb/view-preview-3d/)、[外壳预览](https://prodocs.lceda.cn/cn/pcb/view-preview-3d-shell/)、[CadQuery 官方图形界面建议](https://cadquery.readthedocs.io/en/stable/installation.html)、[CQ-editor 显示与自动重载](https://github.com/CadQuery/CQ-editor/wiki/Usage)。

直接启动或检查显示入口：

```powershell
& 'E:\GunMouseCAD\CQEditor\pythonw.exe' 'F:\项目\枪型飞鼠\scripts\open_preview.py'
```

查看开发工作树或其他生成目录时，可传入 `--output '完整模型目录'`。当前查看脚本读取该目录的 `eda-board-export.step` 和 `outer-shell.step`；自动刷新以最后写入的几何报告为完成信号。直接在外部改实体文件时可按 `刷新模型`。

静态图可按需运行 `scripts/render_preview.py`，生成 `outputs/toolchain-demo/assembly-preview.png`，用于聊天或分享。日常旋转查看使用原生窗口。

查看器固定官方源码提交为 `fd215727b25424df9b69987ece94767b8b327f0f`，源文件保留在 `E:\GunMouseCAD\CQEditorSource`。界面依赖精确版本见 `config/cq-editor-gui-requirements.txt`。查看环境复制已验证的核心后单独补充界面依赖，原建模环境保留 Python 3.12.14、CadQuery 2.8.0 和几何内核 7.9.3.1。

## 自动联动验证

在原生 PowerShell 中执行：

```powershell
$env:PYTHONUTF8 = '1'
& 'E:\GunMouseCAD\Miniforge3\python.exe' 'F:\项目\枪型飞鼠\scripts\verify_integration.py'
```

脚本后台打开项目中的独立示例工程，用嘉立创程序接口导出裸板，交给 CadQuery 生成外壳和装配模型，检查实际孔位与碰撞，并关闭自己创建的编辑器窗口。它保留已经存在的其他编辑器窗口。全过程通过程序调用完成。

共用尺寸在 `config/toolchain-demo.json`，采用毫米、板中心底面原点。电路板接口使用密耳（千分之一英寸）且二维 Y 轴向下，生成脚本显式换算单位与轴方向。外壳直接使用同一配置，并导入嘉立创生成的真实板模型。

产物位于 `outputs/toolchain-demo`：

- `eda-board-export.step`：嘉立创导出的裸板实体三维交换文件。
- `outer-shell.step`：可供后续加工软件使用的外壳实体。
- `outer-shell.stl`：可供三维打印切片软件使用的三角网格。
- `assembly.step`：真实示例板与外壳的装配。
- `geometry-report.json`：实测尺寸、四孔、精度差和碰撞结果。

实测板的边长约 39.974680 × 23.974648 毫米，厚度约 1.600028 毫米；与配置 40 × 24 × 1.6 毫米的差异在 0.05 毫米公差内。四孔位置核对通过，板与外壳交集体积为零。报告保留导出误差，没有为通过验证而修形或移动模型。

## 直接调用设计接口

```powershell
$env:PYTHONUTF8 = '1'
& 'E:\GunMouseCAD\Miniforge3\python.exe' 'F:\项目\枪型飞鼠\scripts\eda_cli.py' -- doctor
```

`eda_cli.py` 支持 `--code-file`、`--args-file` 和 `--evidence`，从文件传递代码、参数并保存结果，避免在命令行拼接复杂源码。软件路径记录在 `config/tools.json`。

已经实测后台打开工程、执行程序接口、创建板形和孔、保存设计、检查示例板设计规则、导出实体文件与生成装配。原理图器件、导线、自动布线接口的存在已核对；真实飞鼠电路和布线质量尚未验收。元件空间、握持手感、结构强度和实际制造另需验证。

环境简明配置在 `config/cadquery-environment.yml`，精确软件包来源在 `config/cadquery-environment-explicit.txt`。本机后续安装软件包建议使用 conda 的传统解析器，避免本次 mamba 的索引解析异常。

嘉立创专业版目前支持个人及商业免费使用，企业定制、私有部署及实际制造另行收费：[官方价格政策](https://lceda.cn/page/pricing)。选型依据：[嘉立创命令行接口](https://prodocs.easyeda.com/cn/api/guide/cli.html)、[自动布线接口](https://prodocs.lceda.cn/cn/api/reference/pro-api.pcb_document.autorouting.html)、[CadQuery 导入导出](https://cadquery.readthedocs.io/en/latest/importexport.html)。

安装问题和验证证据追加在 `docs/工作记录.md`；原始日志保存在项目根的 `.logs`，安装包保存在 `.downloads`，这两处不提交到版本库。
