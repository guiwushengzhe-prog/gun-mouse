"""结构快速预览：摇杆支座独立、原生右键侧置；不改正式电路板。"""
from pathlib import Path
import json

import build_gen2_mount as m
import gen2_component_details as detail
from preview_split_support import split_support
from preview_right_button_cradle import move_right_button_cradle


OUT = m.ROOT / "shell" / "快速结构预览"
ORIGINAL_DETAILS = detail.assembled_details


def preview_details(module, refs):
    refs, colors, wires = ORIGINAL_DETAILS(module, refs)
    pivot = (-33, m.BACK - 3.25, -2)
    for name in ("右键-黑色外壳", "右键-原生按钮", "右键-扁脚"):
        refs[name] = refs[name].rotate(
            pivot, (pivot[0], pivot[1], pivot[2] + 1), 90
        ).translate((13.85, -4.32, -23))

    # 第三脚为空脚；原板仅使用已有右键信号和地两个焊盘。
    pads = next(p for p in m.C["parts"] if p["ref"] == "SW2")["pads"]
    refs["右键-焊点"] = m.cq.Compound.makeCompound([
        detail.solder(m, *p["xz"], .7) for p in pads if p["net"]
    ])
    routes = [
        ("右键信号短线", "BTN_R", (.16, .55, .18), [
            (-33, m.TOP + .6, -2), (-33, -5.2, -2),
            (-31, -5.2, -5.5), (-31, -10.8, -5.5),
            (-31, -10.8, -21.5), (-23.2, -10.8, -21.5),
            (-23.2, -10.8, -25),
        ]),
        ("右键地线短线", "GND", (.025, .027, .03), [
            (-27.92, m.TOP + .6, -2), (-27.92, -5.72, -2),
            (-28.5, -5.72, -5.5), (-28.5, -5.72, -21.5),
            (-23.2, -5.72, -21.5), (-23.2, -5.72, -25),
        ]),
    ]
    for name, net, rgb, points in routes:
        core, length = detail.tube(m, points, .125, .8)
        insulated = list(points)
        insulated[0] = (points[0][0], -4.5, points[0][2])
        # 线尾留下露铜段，与扁脚搭焊。
        insulated[-1] = (points[-1][0], points[-1][1], -24.2)
        jacket, _ = detail.tube(m, insulated, .4, .8)
        refs[name + "-铜芯"] = core
        refs[name + "-绝缘皮"] = jacket
        refs[name + "-扁脚焊锡"] = m.cq.Solid.makeSphere(.55, m.V(*points[-1]))
        colors[name + "-铜芯"] = (.72, .39, .16)
        colors[name + "-绝缘皮"] = rgb
        colors[name + "-扁脚焊锡"] = (.69, .71, .73)
        wires.append({"name": name, "net": net,
                      "centreline_length_mm": round(length, 2),
                      "insulation_diameter_mm": .8,
                      "endpoints_xyz_mm": [points[0], points[-1]],
                      "path_xyz_mm": points})
    refs["独立摇杆支座"] = SUPPORT
    colors["独立摇杆支座"] = (.91, .43, .12)
    return refs, colors, wires


def print_part(shape, name):
    printed = shape.rotate((0, 0, 0), (1, 0, 0), 90)
    b = printed.BoundingBox()
    printed = printed.translate((-b.xmin, -b.ymin, -b.zmin))
    m.cq.exporters.export(printed, str(OUT / "stl" / (name + ".stl")),
                          tolerance=.03, angularTolerance=.1)


def main():
    global SUPPORT
    base = m.cq.importers.importStep(str(m.ROOT / "shell/step/engineering_mount.step")).val()
    parts = split_support(m, base)
    SUPPORT = parts["独立摇杆支座"]
    base = move_right_button_cradle(m, parts["主体底座"])
    for name, shape in (("主体底座", base), ("独立摇杆支座", SUPPORT)):
        if not shape.isValid() or len(shape.Solids()) != 1:
            raise RuntimeError(name + "未形成有效的单件实体")
        print(name, round(shape.Volume(), 2), "立方毫米", flush=True)
    for folder in ("stl", "step", "renders"):
        (OUT / folder).mkdir(parents=True, exist_ok=True)
    m.cq.exporters.export(base, str(OUT / "step/engineering_mount.step"))
    m.cq.exporters.export(SUPPORT, str(OUT / "step/独立摇杆支座.step"))
    print_part(base, "主体底座_预览")
    print_part(SUPPORT, "独立摇杆支座_预览")
    m.OUT = OUT
    detail.assembled_details = preview_details
    report_path = OUT / "assembly-check.json"
    report_path.write_text(json.dumps({"preview": True}, ensure_ascii=False), encoding="utf-8")
    m.export_assembled_stl()
    report = json.loads(report_path.read_text(encoding="utf-8"))["assembled_model"]
    print(json.dumps({"线与底座交叠": report["wire_insulation_vs_mount_mm3"],
                      "线与线交叠": report["wire_insulation_pair_overlaps_mm3"]},
                     ensure_ascii=False), flush=True)
    # 正式记录不生成预览中间报告，只交付模型和效果图。
    report_path.unlink()


if __name__ == "__main__":
    main()
