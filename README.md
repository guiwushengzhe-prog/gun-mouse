# 枪型飞鼠：电路板与外壳

已安装并实际验证嘉立创专业版与 CadQuery 的程序联动。实际飞鼠的硬件方案和枪形外观尚未确定；仓库中的矩形板和开口盒只是工具验证示例。

| 工具 | 版本 | 用途与调用路径 |
| --- | --- | --- |
| 嘉立创专业版 | 4.1.66 | 原理图、电路板、布线与设计规则接口；`E:\各种软件\嘉立创专业版4\lceda-pro.exe` |
| Miniforge | 26.7.2-0 | 管理独立运行环境；`E:\GunMouseCAD\Miniforge3` |
| CadQuery | 2.8.0 | 通过代码生成实体外壳与装配；`E:\GunMouseCAD\CadQuery\python.exe` |
| CadQuery 环境内的 Python | 3.12.14 | 运行建模脚本，与原有 Python 分开 |

项目和版本库位于 `F:\项目\枪型飞鼠`。工作树（同一版本库的独立工作目录）位于 `F:\项目\枪型飞鼠\.worktrees\toolchain`，分支为 `codex/toolchain`。

`E:\GunMouseCAD` 是永久目录联接（另一个路径入口），指向 `E:\各种软件\枪型飞鼠设计工具`。Miniforge 不接受中文安装路径，所以程序用英文入口调用，文件实际仍在原先指定的软件文件夹。按用户后续指示保留现状，不额外搬移软件。

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
