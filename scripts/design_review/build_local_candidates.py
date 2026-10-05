r"""生成两处装配优化的真实局部替换件候选，不覆盖正式打印件。

读取正式已导出的右壳/扳机，再做局部布尔修改；保持其他面不变。
运行：E:\GunMouseCAD\CadQuery\python.exe -B scripts\design_review\build_local_candidates.py
"""
import hashlib
import json
import sys
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
from build_shell import cyl_y, prism_xz  # noqa: E402
from clean_stl_zero_area import clean as clean_stl  # noqa: E402
from verify_mechanical import mesh_evidence  # noqa: E402

OUT = ROOT / "deliverables" / "design-precheck" / "局部打印候选"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(shape, name, angle):
    if not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError(f"候选零件不是有效单实体：{name}")
    cq.exporters.export(cq.Workplane().add(shape), str(OUT / (name + ".step")))
    printed = shape.rotate((0, 0, 0), (1, 0, 0), angle)
    bb = printed.BoundingBox()
    printed = printed.translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
    stl = OUT / (name + ".stl")
    cq.exporters.export(cq.Workplane().add(printed), str(stl), tolerance=0.02, angularTolerance=0.1)
    clean_stl(stl)
    mesh = mesh_evidence(stl)
    if (mesh["connected_regions"] != 1 or mesh["boundary"]["count"]
            or mesh["non_manifold"]["count"] or mesh.get("zero_area_triangles")):
        raise ValueError(f"候选打印网格有缺陷：{name}")
    return {"valid_single_solid": True, "volume_mm3": shape.Volume(),
            "step_sha256": digest(OUT / (name + ".step")), "stl": mesh}


def main():
    cfg = json.loads((ROOT / "config" / "pcb-shell-v1.json").read_text(encoding="utf-8"))
    proposal = json.loads((ROOT / "config" / "装配优化候选.json").read_text(encoding="utf-8"))
    base_dir = ROOT / "deliverables" / "pcb-shell-v1" / "打印文件" / "STEP"
    original_paths = [base_dir / "右半壳.step", base_dir / "扳机.step"]
    before = {str(p.relative_to(ROOT)): digest(p) for p in original_paths}
    right, trigger = [cq.importers.importStep(str(p)).val() for p in original_paths]
    support = proposal["joystick_support"]
    board_back = cfg["board"]["top_face_y"] - cfg["board"]["thickness"]
    top = board_back - support["nominal_board_gap_mm"]
    x, z = support["xz_mm"]
    column = cyl_y(x, z, support["radius_mm"], support["bottom_y_mm"], top)
    new_right = right.fuse(column).clean()
    removed_right = right.cut(new_right).Volume()
    added_right = new_right.cut(right).Volume()
    if removed_right > 1e-5 or added_right <= 0:
        raise ValueError("支撑柱没有形成仅增加材料的连通结构")

    tr = cfg["trigger"]
    joint = proposal["touch_joint_relief"]
    depth = joint["total_depth_behind_cover_mm"]
    if depth <= 0.15 or depth + tr["touch_cover_thickness"] >= tr["blade"]["thickness"]:
        raise ValueError("端接腔深度不合法")
    # 扳机前斜面仍与正式模型一致，只加深上沿局部接头/引线腔。
    def surface(z):
        face = 8 + 6 * (z + 4) / 28
        return face + tr["blade"]["gap_to_grip"] + tr["blade"]["thickness"]
    z0, z1 = joint["z_min_mm"], joint["z_max_mm"]
    ct = tr["touch_cover_thickness"]
    cutter = prism_xz([(surface(z0) - ct - depth, z0), (surface(z0) + 1, z0),
                      (surface(z1) + 1, z1), (surface(z1) - ct - depth, z1)],
                     -joint["half_width_y_mm"], joint["half_width_y_mm"])
    new_trigger = trigger.cut(cutter).clean()
    added_trigger = new_trigger.cut(trigger).Volume()
    removed_trigger = trigger.cut(new_trigger).Volume()
    if added_trigger > 1e-5 or removed_trigger <= 0:
        raise ValueError("端接腔不是仅减去局部材料")
    if len(new_right.Solids()) != 1 or len(new_trigger.Solids()) != 1:
        raise ValueError("局部改动造成零件分离")
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "manufacturing_finalized": False,
        "does_not_fix_trigger_operating_tolerance": True,
        "original_source_sha256": before,
        "support": {"xz_mm": [x, z], "end_y_mm": top, "board_back_y_mm": board_back,
                    "nominal_gap_mm": support["nominal_board_gap_mm"],
                    "added_volume_mm3": added_right, "removed_volume_mm3": removed_right},
        "touch_joint": {"depth_behind_cover_mm": depth,
                        "removed_volume_mm3": removed_trigger, "added_volume_mm3": added_trigger},
        "parts": {"右半壳-摇杆支撑候选": export(new_right, "右半壳-摇杆支撑候选", 90),
                  "扳机-端接避让候选": export(new_trigger, "扳机-端接避让候选", 90)},
    }
    after = {str(p.relative_to(ROOT)): digest(p) for p in original_paths}
    if after != before:
        raise ValueError("正式源模型变化，不能交付候选结果")
    report["original_source_unchanged"] = True
    (OUT / "候选几何检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
