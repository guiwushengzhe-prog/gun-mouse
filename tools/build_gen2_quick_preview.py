"""结构快速预览：摇杆支座独立、原生右键侧置；不改正式电路板。"""
from pathlib import Path
import json

import build_gen2_mount as m
import gen2_component_details as detail
from preview_split_support import split_support
from preview_right_button_cradle import move_right_button_cradle
from preview_local_joystick_mount import local_support, local_hardware
from preview_ss01_right import build_right_switch, right_hardware
from preview_straight_frame import reshape_frame
from preview_layout import POWER_TRANSLATION, IMU_TRANSLATION_Z, body_hardware


OUT = m.ROOT / "shell" / "快速结构预览"
ORIGINAL_DETAILS = detail.assembled_details
ORIGINAL_HARDWARE = m.hardware
ORIGINAL_BOARD_MESHES = m.routed_pcb_meshes


def preview_details(module, refs):
    refs, colors, wires = ORIGINAL_DETAILS(module, refs)
    right_refs, right_colors, terminals = build_right_switch(m)
    refs.update(right_refs)
    colors.update(right_colors)
    for name in refs:
        if name.startswith("电源开关-"):
            refs[name] = refs[name].translate(POWER_TRANSLATION)
        elif name.startswith("陀螺仪"):
            refs[name] = refs[name].translate((0, 0, IMU_TRANSLATION_Z))

    # 第三脚为空脚；原板仅使用已有右键信号和地两个焊盘。
    pads = next(p for p in m.C["parts"] if p["ref"] == "SW2")["pads"]
    refs["右键-焊点"] = m.cq.Compound.makeCompound([
        detail.solder(m, *p["xz"], .7) for p in pads if p["net"]
    ])
    signal_end = (*terminals["NO"][:2], terminals["NO"][2]-.4)
    ground_end = (*terminals["COM"][:2], terminals["COM"][2]-.4)
    routes = [
        ("右键信号短线", "BTN_R", (.16, .55, .18), [
            (-33, m.TOP + .6, -2), (-33, -7, -2),
            (-33, -10.8, -5.5), (-33, -10.8, -31.6),
            (-24, -10.8, -31.6), (-22, -10.8, -32.5), signal_end,
        ]),
        ("右键地线短线", "GND", (.025, .027, .03), [
            (-27.92, m.TOP + .6, -2), (-27.92, -7, -2),
            (-31, -7, -5.5), (-31, -7, -21.5),
            (-24, -7, -21.5), (-24, -10.8, -21.5),
            (-22, -10.8, -23.7), ground_end,
        ]),
    ]
    for name, net, rgb, points in routes:
        core, length = detail.tube(m, points, .125, .8)
        insulated = list(points)
        insulated[0] = (points[0][0], -4.5, points[0][2])
        # 露铜穿入端子的1.6毫米焊孔，焊锡填住孔并接到金属片。
        end, before = m.V(*points[-1]), m.V(*points[-2])
        insulated[-1] = (end+(before-end).normalized()*1.2).toTuple()
        jacket, _ = detail.tube(m, insulated, .4, .8)
        refs[name + "-铜芯"] = core
        refs[name + "-绝缘皮"] = jacket
        terminal = terminals["NO" if net == "BTN_R" else "COM"]
        refs[name + "-扁脚焊锡"] = m.cq.Solid.makeSphere(1.0, m.V(*terminal))
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


def preview_hardware():
    refs, seats = ORIGINAL_HARDWARE()
    refs = {n: s for n, s in refs.items()
            if not n.startswith(("共用锚点", "H1-", "H2-"))}
    refs.update(local_hardware(m))
    refs.update(right_hardware(m))
    refs.update(body_hardware(m))
    return refs, seats


def print_part(shape, name):
    printed = shape.rotate((0, 0, 0), (1, 0, 0), 90)
    b = printed.BoundingBox()
    printed = printed.translate((-b.xmin, -b.ymin, -b.zmin))
    m.cq.exporters.export(printed, str(OUT / "stl" / (name + ".stl")),
                          tolerance=.03, angularTolerance=.1)


def main(export_print_parts=True):
    global SUPPORT
    base = m.cq.importers.importStep(str(m.ROOT / "shell/step/engineering_mount.step")).val()
    parts = split_support(m, base)
    SUPPORT = local_support(m)
    base = move_right_button_cradle(m, reshape_frame(m, parts["主体底座"]))
    for name, shape in (("主体底座", base), ("独立摇杆支座", SUPPORT)):
        if not shape.isValid() or len(shape.Solids()) != 1:
            raise RuntimeError(name + "未形成有效的单件实体")
        print(name, round(shape.Volume(), 2), "立方毫米", flush=True)
    for folder in ("stl", "step", "renders"):
        (OUT / folder).mkdir(parents=True, exist_ok=True)
    m.cq.exporters.export(base, str(OUT / "step/engineering_mount.step"))
    m.cq.exporters.export(SUPPORT, str(OUT / "step/独立摇杆支座.step"))
    if export_print_parts:
        print_part(base, "主体底座_预览")
        print_part(SUPPORT, "独立摇杆支座_预览")
    m.OUT = OUT
    detail.assembled_details = preview_details
    m.hardware = preview_hardware
    m.routed_pcb_meshes = lambda b: ORIGINAL_BOARD_MESHES(b, OUT / "pcb/preview-local-mount.obj")
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
