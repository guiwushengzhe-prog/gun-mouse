"""只读核对正式 PCB 的装配接口；仅在本工作树 outputs 内解压和写报告。

读取交付装配 ZIP、六件 STEP/STL、保存的 PCB、配置与器件库尺寸。
所有试探体仅在内存中用于测量，不修改器件位置、孔位或任何交付设计。
运行：E:\\GunMouseCAD\\CadQuery\\python.exe -B scripts\\formal_validation\\audit_assembly_interfaces.py
"""

import json
import math
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
from audit_netlist import attributes, read_documents  # noqa: E402
from common import MIL, part_uv_rot, resolve_lcsc  # noqa: E402
from verify_mechanical import bounds, mesh_evidence, sha256, solid_contacts, volume_overlap  # noqa: E402

OUT = ROOT / "outputs" / "formal-validation"
DELIVERY = ROOT / "deliverables" / "pcb-shell-v1"
PRINTED = ("左半壳", "右半壳", "扳机", "扳机触摸面盖", "右键帽", "摇杆帽")
V = cq.Vector


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def bore(x, z, radius, y0, y1):
    return cq.Solid.makeCylinder(radius, y1 - y0, V(x, y0, z), V(0, 1, 0))


def same_shape_properties(a, b):
    return (max(abs(x - y) for x, y in zip(bounds(a), bounds(b))) < 1e-4
            and abs(a.Volume() - b.Volume()) < 1e-3)


def load_assembly(report, cfg):
    archive = DELIVERY / "整机装配" / "枪型飞鼠整机装配.step.zip"
    output = OUT / "frozen-assembly.step"
    with zipfile.ZipFile(archive) as zipped:
        entries = [name for name in zipped.namelist() if name.lower().endswith(".step")]
        if len(entries) != 1:
            raise ValueError("交付压缩包必须包含唯一整机 STEP，不猜测选择哪一个")
        with zipped.open(entries[0]) as src, output.open("wb") as dst:
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                dst.write(chunk)
    report["assembly_source"] = {"archive_sha256": sha256(archive), "entry": entries[0],
                                 "step_sha256": sha256(output)}
    assembly = cq.Assembly.load(str(output))
    candidates = [child.toCompound() for child in assembly.children]
    report["assembly_source"]["children"] = len(candidates)
    models = {}
    report["printed_parts"] = {}
    # STEP 导入器可能把子零件名读成编号，因此用独立零件的边界和体积确认，不靠显示名称猜测。
    for name in PRINTED:
        step = DELIVERY / "打印文件" / "STEP" / (name + ".step")
        stl = DELIVERY / "打印文件" / "STL" / (name + ".stl")
        independent = cq.importers.importStep(str(step)).val()
        matches = [shape for shape in candidates if same_shape_properties(shape, independent)]
        if len(matches) != 1:
            raise ValueError(f"无法在正式装配中唯一对应打印件：{name}")
        models[name] = matches[0]
        candidates.remove(matches[0])
        report["printed_parts"][name] = {"assembly_matches_independent_properties": True,
                                          "step_sha256": sha256(step), "stl_sha256": sha256(stl),
                                          "step_valid": bool(independent.isValid()), "stl": mesh_evidence(stl)}
    battery_candidates = [shape for shape in candidates if len(shape.Solids()) == 1]
    main_candidates = [shape for shape in candidates if len(shape.Solids()) > 100]
    if len(battery_candidates) != 1 or len(main_candidates) != 1:
        raise ValueError("不能唯一识别装配中的电池参考体与主板，不沿用旧工作树猜测")
    models["电池"] = battery_candidates[0]
    models["主板"] = main_candidates[0]
    candidates.remove(models["电池"])
    candidates.remove(models["主板"])
    dev = [shape for shape in candidates if bounds(shape)[1] > cfg["dev_board"]["board_xz"]["front_x"]]
    if len(dev) != 1:
        raise ValueError("不能唯一识别开发板参考体")
    models["开发板"] = dev[0]
    candidates.remove(dev[0])
    if len(candidates) != 1:
        raise ValueError("不能唯一识别扳机小板")
    models["扳机小板"] = candidates[0]
    report["model_properties"] = {name: {"valid": bool(shape.isValid()), "bounds": bounds(shape),
                                          "volume_mm3": shape.Volume(), "geometric_center_mm": shape.Center().toTuple()}
                                   for name, shape in models.items()}
    return models


def pcb_layout_evidence(cfg, report):
    path = ROOT / "pcb" / "gun-mouse-v1" / "pcb" / "PCB1.epcb2"
    report["pcb_source_sha256"] = sha256(path)
    records = read_documents(path)[-1][1]
    attrs = attributes(records)
    components = {attrs[h["id"]]["Designator"]: b for h, b, _ in records if h["type"] == "COMPONENT"}
    checks = []
    for part in cfg["parts"]:
        actual = components.get(part["ref"])
        u, v, angle = part_uv_rot(cfg, part)
        if actual is None:
            checks.append({"ref": part["ref"], "missing": True})
            continue
        error = math.hypot(actual["x"] * MIL - u, actual["y"] * MIL - v)
        angle_error = abs((actual["angle"] - angle + 180) % 360 - 180)
        checks.append({"ref": part["ref"], "position_error_mm": error, "angle_error_deg": angle_error,
                       "matches_config_within_serialization_precision": error < 1e-4 and angle_error < 1e-5})
    holes = {b["num"]: b for h, b, _ in records if h["type"] == "PAD" and b.get("num", "").startswith("H")}
    comparisons = []
    for expected in cfg["board"]["mount_holes"]:
        actual = holes.get(expected["id"])
        comparisons.append({"id": expected["id"], "actual_global_xz_mm": [-actual["centerX"] * MIL, actual["centerY"] * MIL] if actual else None,
                            "actual_hole_d_mm": actual["hole"]["width"] * MIL if actual else None,
                            "expected": expected})
    copper_lines = [b for h, b, _ in records if h["type"] == "LINE" and b.get("layerId") in (1, 2)]
    limit = cfg["board"]["antenna_copper_keepout_x_min"]
    crossing = [b for b in copper_lines if max(-b["startX"] * MIL, -b["endX"] * MIL) > limit]
    report["saved_pcb_layout"] = {"component_count": len(components), "components": checks,
                                  "mount_hole_records": comparisons,
                                  "copper_lines_with_endpoint_forward_of_keepout_parameter": len(crossing),
                                  "antenna_nearby_original_components": [
                                      {"ref": ref,
                                       "actual_global_xz_mm": [-components[ref]["x"] * MIL, components[ref]["y"] * MIL],
                                       "config_xz_mm": next(p["xz"] for p in cfg["parts"] if p["ref"] == ref)}
                                      for ref in ("C5", "C6")],
                                  "keepout_note": "此参数用于原脚本铺铜轮廓；不是所有线路的强制禁布区。计数只描述几何，不能推断射频是否合格。"}
    return components


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg_path = ROOT / "config" / "pcb-shell-v1.json"
    geometry_path = ROOT / "config" / "pcb-parts-geometry.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))["parts"]
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "正式保存 PCB 与当前交付装配的文件/模型核对；不改配置、器件位置或设计；不代表打印或实物验收",
              "config_sha256": sha256(cfg_path), "geometry_sha256": sha256(geometry_path)}
    components = pcb_layout_evidence(cfg, report)
    print("Saved PCB positions recorded; importing actual delivery assembly.", flush=True)
    models = load_assembly(report, cfg)
    print("Delivery assembly and six printable parts matched.", flush=True)
    left, right, main_board = models["左半壳"], models["右半壳"], models["主板"]
    top = cfg["board"]["top_face_y"]
    back = top - cfg["board"]["thickness"]
    board_solids = [s for s in main_board.Solids() if s.BoundingBox().xlen > 110
                    and s.BoundingBox().zlen > 110 and abs(s.BoundingBox().ylen - cfg["board"]["thickness"]) < 1e-3]
    if len(board_solids) != 1:
        raise ValueError("不能唯一识别主板板体，停止孔通道检查")
    plate = board_solids[0]
    holes = []
    for h in cfg["board"]["mount_holes"]:
        x, z = h["xz"]
        holes.append({"id": h["id"], "PCB_bore_overlap_mm3": volume_overlap(plate, bore(x, z, h["d"] / 2 - 0.01, back - 0.05, top + 0.05)),
                      "right_clearance_overlap_mm3": volume_overlap(right, bore(x, z, cfg["shell"]["screw"]["clearance_hole"] / 2 - 0.01, -19.99, back - 0.001)),
                      "left_pilot_overlap_mm3": volume_overlap(left, bore(x, z, cfg["shell"]["screw"]["pilot_hole"] / 2 - 0.01, top + 0.001, top + 11.99))})
    report["mount_bore_checks"] = {"rows": holes, "probe_radial_margin_mm": 0.01,
                                    "note": "缩小试探圆柱避免数值边界；不是打印公差。左侧1.7孔为自攻底孔，未模拟螺纹、扭矩和材料强度。"}
    pin_checks = []
    for ref in ("J1", "J2"):
        part = next(p for p in cfg["parts"] if p["ref"] == ref)
        actual = components[ref]
        angle = math.radians(actual["angle"])
        for pad in geometry[resolve_lcsc(cfg, part["lcsc"])]["pads"]:
            number = int(pad["n"])
            x = -(actual["x"] * MIL + pad["x"] * math.cos(angle) - pad["y"] * math.sin(angle))
            z = actual["y"] * MIL + pad["x"] * math.sin(angle) + pad["y"] * math.cos(angle)
            expected_x = cfg["dev_board"]["pin1_x"] - (number - 1) * cfg["dev_board"]["pitch"]
            expected_z = cfg["dev_board"]["row_z"][ref]
            pin_checks.append({"ref": ref, "pin": number, "error_mm": math.hypot(x - expected_x, z - expected_z)})
    report["header_pin_alignment"] = {"pins": len(pin_checks), "maximum_error_mm": max(x["error_mm"] for x in pin_checks),
                                       "details": pin_checks, "note": "匹配开发板参考孔列，不验证用户实物板版本、针长、针径或插接保持力。"}
    usb = cfg["shell"]["usb_opening"]
    usb_x = next(p for p in cfg["parts"] if p["ref"] == "USB1")["xz"][0]
    usb_y = top + 1.63
    front_box = box(usb_x - 4.6, usb_x + 4.6, -4, 4, -95.78, -95.76)
    front_slice = main_board.intersect(front_box)
    portal = box(usb_x - usb["w"] / 2 + 0.01, usb_x + usb["w"] / 2 - 0.01,
                 usb_y - usb["h"] / 2 + 0.01, usb_y + usb["h"] / 2 - 0.01, -96.01, -95.76)
    report["usb_interface"] = {"nominal_opening_mm": [usb["w"], usb["h"]],
                                "outer_recess_mm": [usb["recess_w"], usb["recess_h"], usb["recess_depth"]],
                                "left_portal_overlap_mm3": volume_overlap(portal, left),
                                "right_portal_overlap_mm3": volume_overlap(portal, right),
                                "socket_front_slice_bounds": bounds(front_slice) if front_slice.Volume() > 0 else None,
                                "note": "仅核对库模型前端及通道；实际USB插头包胶、线尾和插拔路径未提供，不能保证所有线材可插。"}
    travel = cfg["trigger"]["switch_contact_from_board"]["rest"] - cfg["trigger"]["switch_contact_from_board"]["stop"]
    pressed = models["扳机"].translate(V(-travel, 0, 0))
    report["trigger"] = {"travel_mm": travel, "pressed_shell_overlap_mm3": {"left": volume_overlap(pressed, left), "right": volume_overlap(pressed, right)},
                         "pressed_daughter_contacts": solid_contacts(pressed, models["扳机小板"]),
                         "full_tolerance_trigger_margin_mm": cfg["trigger"]["switch_contact_from_board"]["operate_min"] - cfg["trigger"]["switch_contact_from_board"]["stop"],
                         "note": "与静态杠杆的驱动接触不证明实物触发/不过压；全公差余量为负，需要实际微动校核，可能局部调整限位。"}
    js = cfg["joystick"]
    pivot = V(js["shaft_xz"][0], top + js["pivot_above_pcb_assumed"], js["shaft_xz"][1])
    tilted = {}
    for height in js["shaft_tip_above_pcb"]:
        centered = models["摇杆帽"].translate(V(0, height - js["shaft_tip_above_pcb"][1], 0))
        for axis_name, axis in (("X", V(1, 0, 0)), ("Z", V(0, 0, 1))):
            for sign in (-1, 1):
                shape = centered.rotate(pivot, pivot + axis, sign * js["stop_angle_deg"])
                tilted[f"{height}/{axis_name}/{sign}"] = {"left": volume_overlap(shape, left), "right": volume_overlap(shape, right)}
    report["joystick"] = {"tilt_shell_contacts_mm3": tilted, "pivot_height_assumed_mm": js["pivot_above_pcb_assumed"],
                           "double_flat_hole_d_mm": js["shaft_d"] + 2 * js["knob"]["d_hole_clearance"],
                           "double_flat_hole_flat_mm": js["shaft_flat"] + 2 * js["knob"]["d_hole_clearance"],
                           "note": "未验证实际摆动中心、按下行程、打印孔收缩和帽子保持力。"}
    antennas = [s for s in models["开发板"].Solids() if bounds(s)[0] >= cfg["dev_board"]["board_xz"]["front_x"] - 1e-4]
    if len(antennas) != 1:
        raise ValueError("不能唯一识别开发板天线参考区域")
    antenna = antennas[0]
    screw_axes = [h["xz"] for h in cfg["board"]["mount_holes"]] + cfg["shell"]["shell_only_screws_xz"]
    screws = [bore(x, z, 1.0, cfg["shell"]["screw"]["head_seat_y"], cfg["shell"]["screw"]["head_seat_y"] + 20) for x, z in screw_axes]
    report["antenna_space"] = {"reference_bounds": bounds(antenna), "battery_distance_mm": antenna.distance(models["电池"]),
                               "nearest_M2_shaft_distance_mm": min(antenna.distance(s) for s in screws),
                               "note": "天线参考体与螺丝杆空间距离，不是射频仿真；未包括线束、手部、金属螺丝头和实际天线场分布。"}
    report["remaining_unknowns"] = {"battery_padding_space_at_max_thickness_mm": cfg["battery"]["pocket_thickness"] - cfg["battery"]["fits_up_to"][0],
                                   "touch_electrode_and_adhesive_stack_space_mm": 0.15,
                                   "dev_board_thickness_assumed_mm": cfg["dev_board"]["board_thickness_assumed"],
                                   "dev_board_component_height_assumed_mm": cfg["dev_board"]["component_height_assumed"],
                                   "balance": "只记录几何体积中心；真实器件、电池、线束和打印件质量未知，不输出实际重心或握持平衡结论。",
                                   "physical_acceptance": "打印公差、弹簧、摩擦、线束、连接器、充电温升、触摸和无线均需实物核对。"}
    report["pcb_source_unchanged_during_audit"] = report["pcb_source_sha256"] == sha256(ROOT / "pcb" / "gun-mouse-v1" / "pcb" / "PCB1.epcb2")
    report["manufacturing_finalized"] = False
    path = OUT / "assembly-interface-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path), "components": len(components), "mount_bores": len(holes), "manufacturing_finalized": False}, ensure_ascii=True))


if __name__ == "__main__":
    main()
