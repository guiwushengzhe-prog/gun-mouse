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


def optional_report(name):
    path = OUTPUT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def audit_status(report):
    if report.get("passed") is True:
        return "通过其声明的核对范围"
    if report.get("passed") is False:
        return "存在差异，未通过"
    return "已有记录，但未提供明确通过判定"


def append_netlist_audits(lines):
    lines += ["", "### 网表核对证据", ""]
    offline = optional_report("netlist-handoff-report.json")
    if offline is None:
        lines.append("- 未读取到离线网表核对报告，不推断配置、原理图和 PCB 一致。")
    else:
        lines += [f"- 离线核对：{audit_status(offline)}；器件 {offline.get('configured_components', '未记录')} 个，"
                  f"已配置连线引脚 {offline.get('configured_connected_pins', '未记录')} 个。",
                  "- 证据：`验证记录/netlist-handoff-report.json`（生成输入为同名 outputs 文件）。", "",
                  "| 离线核对项目 | 差异数量 |", "| --- | --- |"]
        for key, label in (
            ("config_vs_exported_pcb", "配置与导出 PCB 网表"),
            ("config_vs_saved_pcb", "配置与保存的 PCB 焊盘网络"),
            ("pcb_vs_schematic_unique_ids", "PCB 与原理图器件唯一编号"),
            ("exported_unique_ids_stale", "导出网表唯一编号是否陈旧"),
            ("schematic_pin_differences", "原理图真实引线与引脚网络"),
            ("wire_groups_with_conflicting_net_labels", "同一引线组内冲突网络标记"),
            ("unsupported_mirrored_components", "未能核对的镜像器件"),
        ):
            items = offline.get(key)
            lines.append(f"| {label} | {len(items) if isinstance(items, list) else '未记录'} |")
        lines += ["", "离线核对使用保存文件中的符号引脚和导线几何；不代替软件编译网表、设计规则检查或实物电气验收。"]
    compiled = optional_report("schematic-netlist-handoff-report.json")
    if compiled is None:
        lines += ["", "- 未读取到嘉立创软件编译网表比较报告，不把离线核对称作软件网表编译通过。"]
    else:
        pcb_compared = compiled.get("pcb_compared")
        pcb_compared_text = "是" if pcb_compared is True else "否" if pcb_compared is False else "未记录"
        lines += ["", f"- 嘉立创软件编译网表比较：{audit_status(compiled)}。",
                  f"- 编译报告器件 {compiled.get('component_count', '未记录')} 个，"
                  f"引脚 {compiled.get('pin_count', '未记录')} 个；"
                  f"是否完成 PCB 比较：{pcb_compared_text}。",
                  "- 证据：`验证记录/schematic-netlist-handoff-report.json`；软件网表生成成功本身不代表与 PCB 一致。"]
        differences = compiled.get("differences")
        if isinstance(differences, list):
            lines.append(f"- 软件网表比较差异：{len(differences)} 项。")
        if compiled.get("scope"):
            lines.append(f"- 报告范围：{compiled['scope']}")


def append_mechanical_audit(lines, cfg):
    mechanical = optional_report("mechanical-handoff-report.json")
    lines += ["", "### 独立实体与打印网格核对", ""]
    if mechanical is None:
        lines.append("未读取到独立机械核对记录，不能声明六件打印网格已完成封闭性验证。")
        return
    parts = mechanical.get("parts", {})
    current = (mechanical.get("config_sha256") == sha(ROOT / "config" / "pcb-shell-v1.json") and len(parts) == 6)
    for name, part in parts.items():
        for kind, suffix, key in (("STEP", ".step", "step_sha256"), ("STL", ".stl", "stl_sha256")):
            path = DELIVER / "打印文件" / kind / (name + suffix)
            current = current and path.is_file() and part.get(key) == sha(path)
    lines += [f"配置及六件交付文件与核对记录的校验值：{'一致' if current else '不一致或缺失，以下记录不得视为当前文件通过'}。",
              "证据：`验证记录/mechanical-handoff-report.json`。实体有效、网格封闭只说明保存文件的几何状态，不代表已经打印装配。", "",
              "| 零件 | STEP 实体有效 | 实体数 | 网格连通体 | 开放边 | 非流形边 | 零面积面 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, part in parts.items():
        mesh = part.get("stl", {})
        zero = mesh.get("zero_area_triangles")
        lines.append(f"| {name} | {'是' if part.get('step_valid') is True else '否或未记录'} | "
                     f"{part.get('solid_count', '未记录')} | {mesh.get('connected_regions', '未记录')} | "
                     f"{mesh.get('boundary', {}).get('count', '未记录')} | "
                     f"{mesh.get('non_manifold', {}).get('count', '未记录')} | "
                     f"{len(zero) if isinstance(zero, list) else '未记录'} |")
    if mechanical.get("cutting_allowance_note"):
        lines += ["", mechanical["cutting_allowance_note"]]
    baselines = [(name, part["baseline"]["volume_change_mm3"]) for name, part in parts.items()
                 if "volume_change_mm3" in part.get("baseline", {})]
    if baselines:
        lines += ["", "| 相对原交付实体 | 体积变化（立方毫米） |", "| --- | --- |"]
        for name, change in baselines:
            lines.append(f"| {name} | {change:.9f} |")
        unchanged = [name for name, change in baselines if abs(change) < 1e-9]
        if unchanged:
            lines.append(f"\n{len(unchanged)} 件体积不变：{'、'.join(unchanged)}。")
    cleanup = mechanical.get("zero_area_cleanup", {})
    files = cleanup.get("files", [])
    if files:
        removed = sum(len(item.get("removed_triangle_indices", [])) for item in files)
        lines += ["", f"网格清理删除 {removed} 个严格零面积三角面；非零面积面记录保持不变。"
                  "清理脚本为 `clean_stl_zero_area.py`，它不修改 STEP 实体外形。"]
    lines += ["", "### 操作状态的实际接触记录", "",
              "正交集保留为接触记录，不笼统写作所有实体干涉通过。开关杠杆和柱塞在参考模型中不会随按压变形或移动。", "",
              "| 操作状态 | 与不随动开关模型的交集（立方毫米） | 接触实体索引 |", "| --- | --- | --- |"]
    for name, contacts in mechanical.get("daughter_contacts", {}).items():
        volume = sum(item["overlap_mm3"] for item in contacts)
        lines.append(f"| {name}与扳机小板 | {volume:.9f} | {', '.join(str(item['solid_index']) for item in contacts) or '无'} |")
    contacts = mechanical.get("right_button_pressed_board_contacts", [])
    lines.append(f"| 右键帽按到底与主板 | {sum(item['overlap_mm3'] for item in contacts):.9f} | "
                 f"{', '.join(str(item['solid_index']) for item in contacts) or '无'} |")
    lines += ["", "本次逐实体交集位置对应扳机微动杠杆和右键微动柱塞；扳机未与小板板体、开关壳体或插座出现体积交集。"
              "这是已保存模型的接触位置核对，不是实际微动运动和触发点验收。", "",
              "| 数值贴合薄层 | 交集体积（立方毫米） | Y 向交集厚度（毫米） |", "| --- | --- | --- |"]
    for name, contacts in mechanical.get("thin_contact_details", {}).items():
        volume = sum(item["overlap_mm3"] for item in contacts)
        thickness = max((item["overlap_bounds"][3] - item["overlap_bounds"][2] for item in contacts), default=0)
        lines.append(f"| {name} | {volume:.9f} | {thickness:.9f} |")
    lines += ["", "主板与左壳约 0.003 立方毫米、开发板与排母约 0.004 立方毫米的正交集对应约 0.000028 毫米厚的导出贴合薄层。"
              "它们不是检查得到的零交集；该数值薄层解释也不等于实际装配公差已经验证。", "",
              "### 摇杆轴高范围核对", "", "| 保存模型操作状态 | 左壳交集 | 右壳交集 |", "| --- | --- | --- |"]
    for name, values in mechanical.get("joystick_tilt_contacts_mm3", {}).items():
        lines.append(f"| {name} | {values['左半壳']:.9f} | {values['右半壳']:.9f} |")
    archive = mechanical.get("assembly_archive")
    if archive:
        lines += ["", f"整机压缩包内 STEP 与当前未压缩 STEP 的校验值：{'一致' if archive.get('matches') is True else '未确认一致'}。"]


def append_unverified_boundaries(lines, cfg):
    contact = cfg["trigger"]["switch_contact_from_board"]
    travel = contact["rest"] - contact["stop"]
    required_min = contact["rest"] - contact["operate_max"]
    required_max = contact["rest"] - contact["operate_min"]
    battery = cfg["battery"]
    spare = battery["pocket_thickness"] - battery["fits_up_to"][0]
    lines += ["", "## 实物未验收与尺寸边界", "",
              "本报告完成的是文件、连接记录及模型核对，不能作为制造定稿或首轮打印必然装好的保证。"
              "本轮尚未进行实际打印、完整装配、电气上电、无线、触摸稳定性和真实开关动作验收。", "",
              f"- 扳机触点静止高度 {contact['rest']}、动作高度 {contact['operate_min']}～{contact['operate_max']}；"
              f"所需行程 {required_min:.1f}～{required_max:.1f}，现行行程 {travel:.1f}。"
              f"动作高度下限的个体还差 {max(0, required_max - travel):.1f} 毫米，不能保证整个动作公差范围触发。",
              f"- 按配置引用的 SS 规格，余行程至少 1.2 毫米；动作高度上限的个体到现行限位会再压 "
              f"{contact['operate_max'] - contact['stop']:.1f} 毫米，超过上述保证量。"
              "实际触发与剩余可压行程须核对，可能需要局部调整扳机或限位；本轮未擅自改变该机构。",
              "- 触摸盖凹槽比盖厚仅多约 0.15 毫米，铜箔和胶层的叠加厚度要核对。使用薄胶层，不能照原清单给触摸盖贴 1～2 毫米泡棉。",
              f"- 电池仓厚 {battery['pocket_thickness']} 毫米；最大厚 {battery['fits_up_to'][0]} 的电池只剩 {spare:.1f} 毫米名义余量。"
              "只有较薄电池才可配厚泡棉，电池与垫片总厚还须预留打印误差；保护板、插头和线头也需要实测。",
              f"- 开发板厚度 {cfg['dev_board']['board_thickness_assumed']}、元件高度 "
              f"{cfg['dev_board']['component_height_assumed']}、摇杆转动中心高 "
              f"{cfg['joystick']['pivot_above_pcb_assumed']} 毫米仍为假定或参考。"
              "线束弯曲、插拔空间、弹簧和打印收缩未完成实物验收。"]


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
             f"配置版本：{cfg['version']}。由 `scripts/pcb_shell_v1/report.py` 根据各脚本输出生成，请勿手改。",
             "这是文件检查报告；软件检查与模型核对结果分别列出，不代表制造或实物验收完成。", "",
             "## 电路板", "",
             f"- 拼板外形 {max(xs) - min(xs):.1f} × {max(ys) - min(ys):.1f} 毫米（主板 + 扳机小板），2 层，1.6 毫米。",
             f"- 原建板记录：器件 {build.get('placed_components')} 个；焊盘网络写入 {build['pad_nets_written'][0]}/{build['pad_nets_written'][1]}，原流程进行了编辑器载入核对。",
             f"- 布线器记录：{r['nets']} 个网络，未连通列表 {r['failed'] or '无'}；导线段 {r['lines']}，过孔 {r['vias']}。",
             f"- 规则（毫米）：{json.dumps(r['rules_mm'], ensure_ascii=False)}；电源网络线宽 {json.dumps(r['power_widths'], ensure_ascii=False)}。",
             "- 本版保留导线连接地网络的设计，没有铺铜；原后台流程未完成覆铜填充，不据此推断所有软件环境均不支持。",
             "", "### 嘉立创设计规则检查（两层板工艺规则）", ""]
    cnt = drc_summary(drc)
    lines += [f"读取 `drc-report.json`：软件报告总数 {drc.get('count', '未记录')}；逐项解析数 {sum(cnt.values())}。", ""]
    if cnt:
        lines += ["| 类别 | 对象 | 数量 |", "| --- | --- | --- |"]
        for (t, o), n in sorted(cnt.items()):
            lines.append(f"| {t} | {o} | {n} |")
    else:
        lines.append("该份软件记录为 0 项错误。" if drc.get("count") == 0 else "未获得可确认零错误的分项记录。")
    if any(t == "Netlist Error" for t, _ in cnt):
        lines += ["", "软件仍报告原理图与 PCB 网表不一致，当前设计规则检查没有清零。"
                  "不能将该错误缩减为编号或导入关联提示；离线核对和软件编译网表比较证据分别列出，"
                  "也不能替代这份软件检查结果。"]
    append_netlist_audits(lines)
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
              "### 原模型干涉记录（重叠体积，立方毫米；0 含舍入到零或仅面接触的情况）", "",
              "| 对象 | 检查对象 | 重叠 |", "| --- | --- | --- |"]
    for k, v in shell["interference_mm3"].items():
        for kk, vv in v.items():
            lines.append(f"| {k} | {kk} | {vv} |")
    lines += ["", "微动模型没有随动杠杆和柱塞；按压后的正交集必须按接触对象解释。"
              "扳机能否实际触发、微动会否过压不能由该表单独确定。", "",
              "### 限位反向验证（模型超过设计限位时应与外壳重叠）", "", "| 情况 | 重叠 |", "| --- | --- |"]
    for k, v in shell["limit_checks_mm3"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "正交集说明模型设置了对应限位；不代表打印件强度或实际开关余行程已经验收。"]
    append_mechanical_audit(lines, cfg)
    append_unverified_boundaries(lines, cfg)
    out = DELIVER / "检查报告.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
