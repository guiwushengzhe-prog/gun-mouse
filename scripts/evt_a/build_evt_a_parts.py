r"""工程样 EVT-A 打印件：在正式件和预审候选件上做局部修改，并做几何自检。

不改电路板。参数在 config/evt-a.json。输出 deliverables/evt-a/打印文件/ 与 deliverables/evt-a/几何检查.json。
需要 outputs/pcb-shell-v1/preview-models（主板与扳机小板的已装配实体，outputs 不进版本库）。
运行：E:\GunMouseCAD\CadQuery\python.exe -B scripts\evt_a\build_evt_a_parts.py
"""
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
from build_shell import box, cyl_x, cyl_y  # noqa: E402
from clean_stl_zero_area import clean as clean_stl  # noqa: E402
from verify_mechanical import mesh_evidence, solid_contacts, volume_overlap  # noqa: E402

V = cq.Vector
DELIVER = ROOT / "deliverables" / "evt-a"
OUT = DELIVER / "打印文件"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def single(shape, name):
    shape = shape.clean()
    if not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError(f"{name} 不是有效单实体")
    return shape


def hex_prism_x(y, z, across_flats, x0, x1, corner_deg):
    """YZ 平面正六边形沿 X 拉伸；corner_deg 为第一个角的方向。"""
    r = across_flats / math.sqrt(3)
    pts = [V(x0, y + r * math.cos(math.radians(corner_deg + 60 * i)),
             z + r * math.sin(math.radians(corner_deg + 60 * i))) for i in range(6)]
    face = cq.Face.makeFromWires(cq.Wire.makePolygon(pts, close=True))
    return cq.Solid.extrudeLinear(face, V(x1 - x0, 0, 0))


def screw_head(ta, delta, corner_deg=90):
    """M2 外六角螺栓头，端面即扳机触点；delta 为相对原触点更压向开关的量。"""
    face = ta["nominal_face_x"] - delta
    return hex_prism_x(ta["axis_y"], ta["axis_z"], ta["head_across_flats"], face, face + ta["head_height"], corner_deg)


def screw(ta, delta, corner_deg=90):
    """整颗螺栓；杆径 2.0 大于 1.7 导孔，与扳机的重叠是自攻螺纹咬合，不作干涉判断。"""
    under = ta["nominal_face_x"] - delta + ta["head_height"]
    shank = cyl_x(ta["axis_y"], ta["axis_z"], 1.0, under, under + ta["screw_length"])
    return screw_head(ta, delta, corner_deg).fuse(shank).clean()


def modify_trigger(base, ev):
    ta, wc = ev["trigger_adjust"], ev["wire_channel_reroute"]
    t = base.cut(box(-2.01, -0.5, -2.51, 2.51, -17.01, -12.99))  # 去掉原固定触点凸台
    for key in ("fill_old", "fill_tooth_notch"):
        f = wc[key]
        t = t.fuse(box(*f["x"], -f["y_half"], f["y_half"], *f["z"]))
    for key in ("new", "jog"):
        c = wc[key]
        t = t.cut(box(*c["x"], *c["y"], *c["z"]))
    hs = ta["head_slot"]
    t = t.cut(box(*hs["x"], -hs["y_half"], hs["y_half"], *hs["z"]))
    t = t.cut(box(*hs["x"], hs["y_half"], hs["side_open_y_max"], hs["z"][0], hs["side_open_z_top"]))
    t = t.cut(cyl_x(ta["axis_y"], ta["axis_z"], ta["pilot_d"] / 2, *ta["pilot_x"]))
    return single(t, "扳机")


def build_cap(cfg, ev, pressed=0.0):
    rb, rc = cfg["right_button"], ev["right_cap"]
    cap = rb["cap"]
    x, z = rb["xz"]
    yi = cfg["shell"]["half_width_y"] - cfg["shell"]["wall"]
    tip_y = cfg["board"]["top_face_y"] + rc["tip_rest_above_pcb"]
    lip_in = cfg["shell"]["half_width_y"] + rc["travel"]
    lip_out = lip_in + 1.15
    fw, fh = cap["face_w"] / 2, cap["face_h"] / 2
    flange = box(x - fw - 1.4, x + fw + 1.4, yi - cap["flange"], yi, z - fh - 1.4, z + fh + 1.4)
    body = box(x - fw, x + fw, yi - cap["flange"], lip_in, z - fh, z + fh)
    lip = box(x - fw - 0.8, x + fw + 0.8, lip_in, lip_out, z - fh - 0.8, z + fh + 0.8)
    lip = cq.Workplane().add(lip).faces(">Y").edges().fillet(0.6).val()
    stem = box(x + 0.6 - cap["stem_w"] / 2, x + 0.6 + cap["stem_w"] / 2, tip_y, yi - cap["flange"] + 0.01, z - 2, z + 2)
    solid = single(body.fuse(flange).fuse(lip).fuse(stem), "右键帽")
    return solid.translate(V(0, -pressed, 0)) if pressed else solid


def build_fork(ev, thickness, x_face):
    """设定片的使用位置：贴在弹簧座前端面 x_face 上，开口跨过弹簧。"""
    sf = ev["setting_fork"]
    x0, x1 = x_face, x_face + thickness
    fork = box(x0, x1, *sf["y_tines"], *sf["z_lower"])
    fork = fork.fuse(box(x0, x1, *sf["y_tines"], *sf["z_upper"]))
    fork = fork.fuse(box(x0, x1, *sf["handle"]["y"], *sf["handle"]["z"]))
    marks = {0.8: 1, 1.0: 2, 1.2: 3}[round(thickness, 1)]
    hy1 = sf["handle"]["y"][1]
    for i in range(marks):  # 手柄末端的缺口数表示厚度：1=0.8，2=1.0，3=1.2
        zc = sf["handle"]["z"][1] - 1.5 - 2.2 * i
        fork = fork.cut(box(x0 - 0.1, x1 + 0.1, hy1 - 1.2, hy1 + 0.1, zc - 0.6, zc + 0.6))
    return single(fork, f"设定片{thickness}")


def export(shape, name, rotations):
    OUT.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(cq.Workplane().add(shape), str(OUT / f"{name}.step"))
    printed = shape
    for axis, angle in rotations:
        printed = printed.rotate((0, 0, 0), axis, angle)
    bb = printed.BoundingBox()
    printed = printed.translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
    stl = OUT / f"{name}.stl"
    cq.exporters.export(cq.Workplane().add(printed), str(stl), tolerance=0.02, angularTolerance=0.1)
    clean_stl(stl)
    mesh = mesh_evidence(stl)
    if (mesh["connected_regions"] != 1 or mesh["boundary"]["count"]
            or mesh["non_manifold"]["count"] or mesh.get("zero_area_triangles")):
        raise ValueError(f"打印网格有缺陷：{name}")
    bb = printed.BoundingBox()
    return {"volume_mm3": round(shape.Volume(), 3), "print_size_mm": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
            "step_sha256": digest(OUT / f"{name}.step"), "mesh_connected_regions": mesh["connected_regions"],
            "mesh_open_edges": mesh["boundary"]["count"], "mesh_non_manifold": mesh["non_manifold"]["count"]}


def r3(v):
    return round(v, 3)


def main():
    cfg = json.loads((ROOT / "config" / "pcb-shell-v1.json").read_text(encoding="utf-8"))
    ev = json.loads((ROOT / "config" / "evt-a.json").read_text(encoding="utf-8"))
    sources = {k: ROOT / ev["base"][k] for k in ("left_half", "right_half", "trigger")}
    before = {str(p.relative_to(ROOT)): digest(p) for p in sources.values()}
    left0, right0, trig0 = (cq.importers.importStep(str(sources[k])).val() for k in ("left_half", "right_half", "trigger"))
    models = ROOT / ev["base"]["board_models"]
    pcb = cq.importers.importStep(str(models / "pcb.step")).val()
    daughter = cq.importers.importStep(str(models / "daughter.step")).val()

    ta = ev["trigger_adjust"]
    travel = cfg["trigger"]["switch_contact_from_board"]["rest"] - cfg["trigger"]["switch_contact_from_board"]["stop"]

    # ---------------- 外壳：硬限位归右半壳 + 右键支撑柱
    sd = ev["single_stop_datum"]
    b, c = sd["block"], sd["left_clearance"]
    right = right0.fuse(box(*b["x"], *b["y"], *b["z"]))
    left = left0.cut(box(b["x"][0] - c, b["x"][1] + c, b["y"][0] - c, b["y"][1] + c, b["z"][0] - c, b["z"][1] + c))
    board_back = cfg["board"]["top_face_y"] - cfg["board"]["thickness"]
    sp = ev["sw2_support_posts"]
    posts = [cyl_y(x, z, r, sp["bottom_y"], board_back - sp["board_gap"]) for x, z, r in sp["xz_r"]]
    for post in posts:
        right = right.fuse(post)
    right = single(right, "右半壳")
    left = single(left, "左半壳")

    trigger = modify_trigger(trig0, ev)
    cap = build_cap(cfg, ev)

    # ---------------- 自检
    checks = {}
    lo, hi = ta["adjust_range_mm"]
    for delta in (lo, 0.0, hi):
        for corner in (90, 0, 30):  # 螺栓头在槽内任意转角都不碰扳机
            if volume_overlap(screw_head(ta, delta, corner), trigger) > 1e-4:
                raise ValueError(f"螺栓头与扳机槽干涉：delta={delta}")
        under = ta["nominal_face_x"] - delta + ta["head_height"]
        if under + ta["screw_length"] > ta["pilot_x"][1] + 1e-6 or under + 5.0 > ta["pilot_x"][1]:
            raise ValueError(f"导孔深度或螺纹啮合不足：delta={delta}")
        s = screw(ta, delta)
        for state, dx in (("静止", 0.0), ("按到底", -travel)):
            moved = trigger.fuse(s).translate(V(dx, 0, 0))
            key = f"扳机+螺栓 delta={delta:+.1f} {state}"
            checks[key] = {"左半壳": r3(volume_overlap(moved, left)), "右半壳": r3(volume_overlap(moved, right)),
                           "扳机小板模型": r3(volume_overlap(moved, daughter))}
            if checks[key]["左半壳"] > 1e-3 or checks[key]["右半壳"] > 1e-3:
                raise ValueError(f"扳机与外壳干涉：{key}")
    over = trigger.translate(V(-travel - 0.5, 0, 0))
    limit = {"扳机多压0.5_右半壳(应>0)": r3(volume_overlap(over, right)),
             "扳机多压0.5_左半壳(应=0，硬限位只在右半壳)": r3(volume_overlap(over, left))}
    if limit["扳机多压0.5_右半壳(应>0)"] <= 0 or limit["扳机多压0.5_左半壳(应=0，硬限位只在右半壳)"] > 1e-3:
        raise ValueError(f"硬限位归属检查失败：{limit}")

    post_contacts = [solid_contacts(p, pcb) for p in posts]
    if any(post_contacts):
        raise ValueError(f"右键支撑柱与主板实体干涉：{post_contacts}")
    rc = ev["right_cap"]
    cap_checks = {}
    for state, d in (("静止", 0.0), ("按到底", rc["travel"]), ("多压0.3", rc["travel"] + 0.3)):
        moved = cap.translate(V(0, -d, 0)) if d else cap
        cap_checks[state] = {"左半壳": r3(volume_overlap(moved, left)), "右半壳": r3(volume_overlap(moved, right)),
                             "主板模型": r3(volume_overlap(moved, pcb))}
    if cap_checks["静止"]["左半壳"] > 1e-3 or cap_checks["按到底"]["左半壳"] > 1e-3 or cap_checks["多压0.3"]["左半壳"] <= 0:
        raise ValueError(f"右键帽限位检查失败：{cap_checks}")
    top = cfg["board"]["top_face_y"]
    stem_tip_pressed = rc["tip_rest_above_pcb"] - rc["travel"]

    halves = r3(volume_overlap(left, right))
    if halves > 1e-3:
        raise ValueError(f"左右半壳干涉：{halves}")

    stop_face = sd["block"]["x"][1]
    sf = ev["setting_fork"]
    spring = cyl_x(0, sf["spring_model"]["axis_z"], sf["spring_model"]["od"] / 2, stop_face, stop_face + 13.1)
    forks, fork_checks = {}, {}
    for t in sf["thickness_mm"]:
        fork = build_fork(ev, t, stop_face)
        forks[t] = fork
        at_gauge = trigger.translate(V(-travel + t, 0, 0))
        fork_checks[f"{t}"] = {"扳机": r3(volume_overlap(fork, at_gauge)), "右半壳": r3(volume_overlap(fork, right)),
                               "弹簧模型": r3(volume_overlap(fork, spring))}
        if any(v > 1e-3 for v in fork_checks[f"{t}"].values()):
            raise ValueError(f"设定片干涉：{t} {fork_checks[f'{t}']}")

    # ---------------- 导出
    parts = {
        "左半壳-EVT-A": export(left, "左半壳-EVT-A", [((1, 0, 0), -90)]),
        "右半壳-EVT-A": export(right, "右半壳-EVT-A", [((1, 0, 0), 90)]),
        "扳机-EVT-A": export(trigger, "扳机-EVT-A", [((1, 0, 0), 90)]),
        "右键帽-EVT-A": export(cap, "右键帽-EVT-A", [((1, 0, 0), -90)]),
    }
    for t, fork in forks.items():
        name = f"扳机设定片-{t:.1f}mm"
        parts[name] = export(fork, name, [((0, 1, 0), -90)])
    base_print = ROOT / "deliverables" / "pcb-shell-v1" / "打印文件"
    for name in ("扳机触摸面盖", "摇杆帽"):
        for ext, sub in (("step", "STEP"), ("stl", "STL")):
            shutil.copyfile(base_print / sub / f"{name}.{ext}", OUT / f"{name}.{ext}")
        parts[name] = {"unchanged_copy_of": f"deliverables/pcb-shell-v1/打印文件/*/{name}.*",
                       "step_sha256": digest(OUT / f"{name}.step")}

    after = {str(p.relative_to(ROOT)): digest(p) for p in sources.values()}
    if after != before:
        raise ValueError("源模型在生成期间变化")
    report = {
        "manufacturing_finalized": False,
        "scope": "工程样打印件几何自检；不证明打印配合、强度、寿命或开关实际动作位",
        "source_sha256": before,
        "board_models": {k: digest(models / f"{k}.step") for k in ("pcb", "daughter")},
        "volume_change_mm3": {
            "右半壳": r3(right.Volume() - right0.Volume()), "左半壳": r3(left.Volume() - left0.Volume()),
            "扳机": r3(trigger.Volume() - trig0.Volume())},
        "trigger_with_screw_mm3": checks,
        "trigger_stop_owner_mm3": limit,
        "trigger_screw_adjust_range_mm": [lo, hi],
        "trigger_baseline_note": "原设计扳机与小板模型的重叠为静止 1.486、按到底 8.267 mm³，来自杠杆按自由位置建模；"
                                 "螺栓头取代原触点后同类重叠属预期，不代表实物干涉",
        "sw2_posts": {"xz_r": sp["xz_r"], "end_y": r3(board_back - sp["board_gap"]), "pcb_contacts": post_contacts},
        "right_cap_mm3": cap_checks,
        "right_cap_note": f"帽杆静止端面距板 {rc['tip_rest_above_pcb']}（原厂 FP≤{rc['d2fc_fp_max']}），按到底 {stem_tip_pressed:.2f}，"
                          f"低于 OP 下限 {rc['d2fc_op'][0]}；主板模型推杆顶取三维模型 7.45，故静止重叠属预期",
        "halves_overlap_mm3": halves,
        "setting_fork_mm3": fork_checks,
        "parts": parts,
        "source_unchanged": True,
    }
    DELIVER.mkdir(parents=True, exist_ok=True)
    (DELIVER / "几何检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
