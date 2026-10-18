"""导出当前装配对应的两个独立打印件，并核对实体与三角网格。"""
from pathlib import Path
import hashlib
import json
import shutil

import build_gen2_quick_preview as preview
from preview_layout import BODY_MOUNT_HOLES, SHARED_SCREW_SEAT_Y, SHARED_EAR_THICKNESS
from preview_local_joystick_mount import ACTIVE_LOCAL_HOLES
from preview_ss01_right import MOUNT_HOLES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "release/2026-10-18-结构简化版/三维打印"


def main():
    base, support = preview.main(export_print_parts=True)
    m = preview.m
    refs, _, _ = preview.preview_details(m, m.references())
    refs.update(preview.preview_hardware()[0])
    parts = (("主体底座", base), ("独立摇杆支座", support))
    report = {"单位": "毫米", "打印比例": "1:1", "打印件": []}
    tools = {}
    for name, (x, z) in BODY_MOUNT_HOLES.items():
        seat = SHARED_SCREW_SEAT_Y if name == "H3" else m.BASE[0]
        tools[name] = m.cy(x, z, 1.1, -35, seat-2.11)
    for i, (x, old_y) in enumerate(m.JOY_MOUNT_HOLES, 1):
        tools[f"摇杆小板{i}"] = m.cz(x, m.FACE_Y_SUM-old_y, 1.1, -24, -5.91)
    for i, (x, z) in enumerate(ACTIVE_LOCAL_HOLES, 2):
        tools[f"支座{i}"] = m.cy(x, z, 1.1, 6.71, 30)
    for i, (x, z) in enumerate(m.SS_HOLES, 1):
        tools[f"扳机{i}"] = m.cy(x, z, 1.1, .45, 30)
    for i, (x, z) in enumerate(MOUNT_HOLES, 1):
        tools[f"右键{i}"] = m.cy(x, z, 1.1, -5.49, 30)
    all_shapes = {**refs, "主体底座": base}
    accesses = {}
    for name, tool in tools.items():
        collisions = {other: round(tool.intersect(shape).Volume(), 5)
                      for other, shape in all_shapes.items()
                      if "留空" not in other and tool.intersect(shape).Volume() > .001}
        if collisions:
            raise RuntimeError((name, "工具入口阻挡", collisions))
        accesses[name] = 0
    nut_paths = {}
    for name, nut in refs.items():
        if not name.endswith("螺母") or not name.startswith(("SS", "右键")):
            continue
        path = m.swept_box(nut, (-12, 0, 0) if name.startswith("SS") else (12, 0, 0))
        hits = {part: round(path.intersect(shape).Volume(), 5) for part, shape in parts
                if path.intersect(shape).Volume() > .001}
        if hits:
            raise RuntimeError((name, "螺母侧插阻挡", hits))
        nut_paths[name] = 0
    report["工具通道交叠"] = accesses
    report["按键螺母侧插交叠"] = nut_paths
    report["共用H3"] = {"连接耳厚度毫米": SHARED_EAR_THICKNESS,
                      "M2螺丝长度毫米": 20,
                      "螺杆超出螺母毫米": round(SHARED_SCREW_SEAT_Y+20-(m.TOP+SHARED_EAR_THICKNESS+1.6), 3)}
    for name, shape in parts:
        collisions = {}
        for other, component in refs.items():
            if other == name or "留空" in other:
                continue
            volume = shape.intersect(component).Volume()
            if volume > .001:
                collisions[other] = round(volume, 5)
        source = preview.OUT / "stl" / (name + "_预览.stl")
        mesh = m.verify_mesh(source, shape.Volume())
        if not shape.isValid() or len(shape.Solids()) != 1 or collisions or not mesh["pass"]:
            raise RuntimeError((name, collisions, mesh))
        import vtk
        reader = vtk.vtkSTLReader()
        reader.SetFileName(str(source))
        reader.Update()
        bounds = reader.GetOutput().GetBounds()
        if any(abs(bounds[i]) > 1e-5 for i in (0, 2, 4)):
            raise RuntimeError((name, "打印坐标原点异常", bounds))
        OUT.mkdir(parents=True, exist_ok=True)
        target = OUT / (name + ".stl")
        shutil.copy2(source, target)
        item = {"文件": target.name, "实体数": 1,
                "体积_立方毫米": round(shape.Volume(), 3),
                "打印尺寸_毫米": [round(bounds[i+1]-bounds[i], 3) for i in (0, 2, 4)],
                "器件导线五金交叠": collisions, "三角网格检查": mesh,
                "SHA256": hashlib.sha256(target.read_bytes()).hexdigest()}
        report["打印件"].append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    report["检查边界"] = "静态模型和网格检查；未完成实物试装、承压及通电验证。"
    (OUT / "模型核对.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
