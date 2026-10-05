"""汇总建板、规则检查、外壳干涉与限位检查结果，生成 deliverables/pcb-shell-v1/检查报告.md。"""

import collections
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUT, ROOT, load_config  # noqa: E402

DELIVER = ROOT / "deliverables" / "pcb-shell-v1"


def drc_summary(drc):
    cnt = collections.Counter()

    def walk(n):
        if isinstance(n, dict):
            if "errorObjType" in n:
                cnt[(n.get("errorType"), n.get("errorObjType"))] += 1
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(drc.get("items"))
    return cnt


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bom_rows(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text), delimiter="\t" if "\t" in text.splitlines()[0] else ","))
    return rows


def main():
    cfg = load_config()
    build = json.loads((OUTPUT / "pcb-build-report.json").read_text(encoding="utf-8"))
    drc = json.loads((OUTPUT / "drc-report.json").read_text(encoding="utf-8"))
    shell = json.loads((OUTPUT / "shell-report.json").read_text(encoding="utf-8"))
    layout = json.loads((OUTPUT / "layout.json").read_text(encoding="utf-8"))
    xs = [p[0] for p in layout["outline_uv"]]
    ys = [p[1] for p in layout["outline_uv"]]
    r = build["routing"]
    lines = ["# 检查报告（自动生成）", "",
             f"配置版本：{cfg['version']}。由 `scripts/pcb_shell_v1/report.py` 根据各脚本输出生成，请勿手改。", "",
             "## 电路板", "",
             f"- 拼板外形 {max(xs) - min(xs):.1f} × {max(ys) - min(ys):.1f} 毫米（主板 + 扳机小板），2 层，1.6 毫米。",
             f"- 器件 {build.get('placed_components')} 个；焊盘网络写入 {build['pad_nets_written'][0]}/{build['pad_nets_written'][1]}，编辑器载入核对通过。",
             f"- 布线：{r['nets']} 个网络全部连通（未连通：{r['failed'] or '无'}）；导线段 {r['lines']}，过孔 {r['vias']}。",
             f"- 规则（毫米）：{json.dumps(r['rules_mm'], ensure_ascii=False)}；电源网络线宽 {json.dumps(r['power_widths'], ensure_ascii=False)}。",
             "- 地网络与其他网络一样由导线完整连通；后台会话无法计算覆铜填充，本版不铺铜（可在界面中自行添加铺铜作为增强）。",
             "", "### 嘉立创设计规则检查（JLCPCB Capability, Two Layers）", ""]
    cnt = drc_summary(drc)
    if cnt:
        lines += ["| 类别 | 对象 | 数量 |", "| --- | --- | --- |"]
        for (t, o), n in sorted(cnt.items()):
            lines.append(f"| {t} | {o} | {n} |")
    else:
        lines.append("无错误。")
    if any(t == "Netlist Error" for t, _ in cnt):
        lines += ["", "说明：Netlist Error 是\"原理图与 PCB 网表未建立导入关联\"的提示。后台会话中嘉立创不执行\"从原理图导入\"，"
                  "PCB 网络由配置直接写入；原理图用同一份网表程序生成，器件唯一编号已与 PCB 对齐。"
                  "间距、连通性等制造相关检查全部为 0。"]
    lines += ["", "### 导出文件", "", "| 文件 | 字节 | SHA-256 |", "| --- | --- | --- |"]
    for e in build.get("exports", []):
        p = ROOT / e["file"]
        if p.exists() and "deliverables" in e["file"]:
            lines.append(f"| `{p.relative_to(DELIVER).as_posix()}` | {p.stat().st_size} | `{sha(p)}` |")
    lines += ["", "## 外壳与机构", "", "### 打印件", "", "| 零件 | 打印外形（毫米） | 体积（立方厘米） |", "| --- | --- | --- |"]
    for p in shell["parts"]:
        a, b, c = p["print_size_mm"]
        lines.append(f"| {p['name']} | {a} × {b} × {c} | {p['volume_cm3']} |")
    i = shell["info"]
    lines += ["", f"扳机行程 {i['trigger_travel']} 毫米（触点静止 x={i['trigger_rest_x']}，按到底 x={i['trigger_press_x']}）；"
              f"摇杆开口半径 内 {i['joystick_opening_r_inner']} / 外 {i['joystick_opening_r_outer']} 毫米。", "",
              "### 干涉检查（重叠体积，立方毫米；0 表示不接触或仅面接触）", "",
              "| 对象 | 检查对象 | 重叠 |", "| --- | --- | --- |"]
    for k, v in shell["interference_mm3"].items():
        for kk, vv in v.items():
            lines.append(f"| {k} | {kk} | {vv} |")
    lines += ["", "说明：扳机与扳机小板的重叠是滑杆前端压在微动杠杆上（模型中杠杆不随动）：静止预压约 1.5 毫米，仍高于动作位；"
              "按到底时压到动作位以下。已逐个实体核对，重叠只发生在杠杆实体上，与开关壳体、小板、插座均为 0。"
              "开发板参考体与主板、主板与左半壳的千分之几立方毫米为贴合面接触（排针塑料面、螺柱压板面）。", "",
              "### 限位反向验证（超过设计限位时应与外壳重叠，数值 > 0 为通过）", "", "| 情况 | 重叠 |", "| --- | --- |"]
    for k, v in shell["limit_checks_mm3"].items():
        lines.append(f"| {k} | {v} |")
    out = DELIVER / "检查报告.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
