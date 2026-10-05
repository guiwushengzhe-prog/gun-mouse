"""只读核对已保存的机构实体和打印网格，不重新生成或改动设计。

默认仅写 outputs/pcb-shell-finish-audit/mechanical-verification.json。
需要原交付的 outputs/pcb-shell-v1/preview-models；它们用于读取已装配的板和器件。
运行：E:\\GunMouseCAD\\CadQuery\\python.exe -B scripts\\pcb_shell_v1\\verify_mechanical.py
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import cadquery as cq
import numpy as np
import vtk


ROOT = Path(__file__).resolve().parents[2]
DELIVERY = ROOT / "deliverables" / "pcb-shell-v1"
PARTS = ("左半壳", "右半壳", "扳机", "扳机触摸面盖", "右键帽", "摇杆帽")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bounds(shape):
    b = shape.BoundingBox()
    return [b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax]


def disjoint(a, b):
    return any(a[i + 1] < b[i] or b[i + 1] < a[i] for i in (0, 2, 4))


def volume_overlap(a, b):
    if disjoint(bounds(a), bounds(b)):
        return 0.0
    return float(a.intersect(b).Volume())


def solid_contacts(a, b):
    """逐实体记录交集，不把预期按压接触直接算成通过。"""
    contacts = []
    ab = bounds(a)
    for index, solid in enumerate(b.Solids()):
        if disjoint(ab, bounds(solid)):
            continue
        overlap = a.intersect(solid)
        volume = float(overlap.Volume())
        if volume > 1e-6:
            contacts.append({"solid_index": index, "overlap_mm3": volume,
                             "overlap_bounds": bounds(overlap), "other_bounds": bounds(solid)})
    return contacts


def mesh_evidence(path):
    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(path))
    reader.Update()
    mesh = reader.GetOutput()
    connectivity = vtk.vtkPolyDataConnectivityFilter()
    connectivity.SetInputData(mesh)
    connectivity.SetExtractionModeToAllRegions()
    connectivity.Update()
    evidence = {"triangles": mesh.GetNumberOfCells(), "bounds": mesh.GetBounds(),
                "connected_regions": connectivity.GetNumberOfExtractedRegions()}
    for kind in ("boundary", "non_manifold"):
        edges = vtk.vtkFeatureEdges()
        edges.SetInputData(mesh)
        edges.FeatureEdgesOff()
        edges.ManifoldEdgesOff()
        edges.SetBoundaryEdges(kind == "boundary")
        edges.SetNonManifoldEdges(kind == "non_manifold")
        edges.Update()
        data = edges.GetOutput()
        evidence[kind] = {"count": data.GetNumberOfCells(),
                          "points": [data.GetPoint(i) for i in range(data.GetNumberOfPoints())]}
    raw = path.read_bytes()
    dtype = np.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attr", "<u2")])
    # 交付件为二进制 STL；若以后改为文本，不猜测其三角面存储格式。
    if len(raw) >= 84 and len(raw) == 84 + int.from_bytes(raw[80:84], "little") * 50:
        triangles = np.frombuffer(raw[84:], dtype=dtype)
        vertices = triangles["vertices"].astype(np.float64)
        area = np.linalg.norm(np.cross(vertices[:, 1] - vertices[:, 0],
                                       vertices[:, 2] - vertices[:, 0]), axis=1) / 2
        evidence["zero_area_triangles"] = np.flatnonzero(area == 0).tolist()
        points = evidence["non_manifold"]["points"]
        if len(points) == 2:
            matches = []
            for point in points:
                matches.append(np.any(np.all(vertices == point, axis=2), axis=1))
            indices = np.flatnonzero(matches[0] & matches[1])
            evidence["non_manifold_incident_faces"] = [
                {"triangle": int(i), "area_mm2": float(area[i]),
                 "vertices": vertices[i].tolist(), "normal": triangles["normal"][i].tolist()}
                for i in indices]
    return evidence


def main():
    parser = argparse.ArgumentParser(description="只读核对保存的机构模型，不重新生成外壳")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "outputs" / "pcb-shell-v1" / "preview-models")
    parser.add_argument("--baseline-step-dir", type=Path, help="可选：只读的原交付 STEP 目录，用于比较体积")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "outputs" / "pcb-shell-finish-audit" / "mechanical-verification.json")
    args = parser.parse_args()
    cfg_path = ROOT / "config" / "pcb-shell-v1.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    evidence = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "scope": "读取既有实体和网格；仅刚体平移、旋转以检查操作状态；不修改或生成交付外形",
                "config_sha256": sha256(cfg_path), "parts": {}, "models": {}}
    evidence["builder_sha256"] = sha256(ROOT / "scripts" / "pcb_shell_v1" / "build_shell.py")
    cleanup_path = ROOT / "outputs" / "pcb-shell-v1" / "stl-zero-area-cleanup.json"
    if cleanup_path.is_file():
        evidence["zero_area_cleanup"] = json.loads(cleanup_path.read_text(encoding="utf-8"))
    for name in PARTS:
        step = DELIVERY / "打印文件" / "STEP" / (name + ".step")
        stl = DELIVERY / "打印文件" / "STL" / (name + ".stl")
        shape = cq.importers.importStep(str(step)).val()
        evidence["parts"][name] = {
            "step_sha256": sha256(step), "stl_sha256": sha256(stl),
            "step_valid": bool(shape.isValid()), "solid_count": len(shape.Solids()),
            "step_volume_mm3": float(shape.Volume()), "stl": mesh_evidence(stl)}
        if args.baseline_step_dir:
            baseline_path = args.baseline_step_dir / (name + ".step")
            baseline = cq.importers.importStep(str(baseline_path)).val()
            evidence["parts"][name]["baseline"] = {
                "file": str(baseline_path), "sha256": sha256(baseline_path),
                "volume_mm3": float(baseline.Volume()),
                "volume_change_mm3": float(shape.Volume() - baseline.Volume())}
    print("Six saved STEP and STL parts checked.", flush=True)
    models = {}
    for name in ("left", "right", "trigger", "cap", "knob", "daughter", "pcb", "dev", "battery"):
        path = args.model_dir / (name + ".step")
        if not path.is_file():
            raise FileNotFoundError(f"已保存的装配参考模型缺失：{path}；本脚本不会重新生成")
        models[name] = cq.importers.importStep(str(path)).val()
        evidence["models"][name] = {"file": str(path), "sha256": sha256(path),
                                    "valid": bool(models[name].isValid())}
    print("Saved assembly reference bodies loaded.", flush=True)
    left, right, main_board = models["left"], models["right"], models["pcb"]
    tr = cfg["trigger"]["switch_contact_from_board"]
    travel = tr["rest"] - tr["stop"]
    movers = {"扳机静止": models["trigger"],
              "扳机按到底": models["trigger"].translate(cq.Vector(-travel, 0, 0)),
              "右键帽静止": models["cap"],
              "右键帽按到底": models["cap"].translate(cq.Vector(0, -0.85, 0))}
    evidence["shell_contacts_mm3"] = {
        name: {"左半壳": volume_overlap(solid, left), "右半壳": volume_overlap(solid, right)}
        for name, solid in movers.items()}
    evidence["daughter_contacts"] = {
        name: solid_contacts(movers[name], models["daughter"]) for name in ("扳机静止", "扳机按到底")}
    evidence["right_button_pressed_board_contacts"] = solid_contacts(movers["右键帽按到底"], main_board)
    evidence["thin_contact_details"] = {"主板与左壳": solid_contacts(main_board, left),
                                          "主板与开发板": solid_contacts(main_board, models["dev"])}
    js = cfg["joystick"]
    pivot = cq.Vector(js["shaft_xz"][0], cfg["board"]["top_face_y"] + js["pivot_above_pcb_assumed"],
                      js["shaft_xz"][1])
    high_tip = js["shaft_tip_above_pcb"][1]
    tilt_checks = {}
    for height in js["shaft_tip_above_pcb"]:
        centered = models["knob"].translate(cq.Vector(0, height - high_tip, 0))
        for axis_name, axis in (("X", cq.Vector(1, 0, 0)), ("Z", cq.Vector(0, 0, 1))):
            for sign in (-1, 1):
                tilted = centered.rotate(pivot, pivot + axis, sign * js["stop_angle_deg"])
                tilt_checks[f"轴高{height}，{axis_name}{sign:+d}，{js['stop_angle_deg']}度"] = {
                    "左半壳": volume_overlap(tilted, left), "右半壳": volume_overlap(tilted, right)}
    evidence["joystick_tilt_contacts_mm3"] = tilt_checks
    shell = left.fuse(right)
    beyond = models["knob"].rotate(pivot, pivot + cq.Vector(1, 0, 0), js["max_angle_deg"] + 1)
    evidence["limit_reverse_checks_mm3"] = {
        "扳机多压0.5毫米": volume_overlap(models["trigger"].translate(cq.Vector(-travel - 0.5, 0, 0)), shell),
        "扳机向前0.5毫米": volume_overlap(models["trigger"].translate(cq.Vector(0.5, 0, 0)), shell),
        "摇杆帽倾斜24度": volume_overlap(beyond, shell),
        "右键帽多压0.3毫米": volume_overlap(models["cap"].translate(cq.Vector(0, -1.15, 0)), shell)}
    evidence["dimension_boundaries"] = {
        "trigger_stop_margin_to_min_operating_height_mm": tr["operate_min"] - tr["stop"],
        "trigger_note": "负余量表示不能由该组参数保证整个动作高度公差范围均触发；不更改现有行程",
        "battery_foam_space_at_max_thickness_mm": cfg["battery"]["pocket_thickness"] - cfg["battery"]["fits_up_to"][0],
        "touch_cover_adhesive_space_mm": 0.15,
        "assumptions": {"开发板厚度": cfg["dev_board"]["board_thickness_assumed"],
                        "开发板元件高度": cfg["dev_board"]["component_height_assumed"],
                        "摇杆转动中心高": js["pivot_above_pcb_assumed"]},
        "note": "实体检查不能验证打印公差、线束、压簧、胶层或真实开关的动作公差"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.output), "models_loaded": len(models),
                      "parts_checked": len(PARTS)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
