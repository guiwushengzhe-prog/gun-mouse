"""导出当前装配对应的两个独立打印件，并核对实体与三角网格。"""
from pathlib import Path
import hashlib
import json
import shutil

import build_gen2_quick_preview as preview

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "release/2026-10-18/三维打印"


def main():
    base, support = preview.main(export_print_parts=True)
    m = preview.m
    refs, _, _ = preview.preview_details(m, m.references())
    refs.update(preview.preview_hardware()[0])
    parts = (("主体底座", base), ("独立摇杆支座", support))
    report = {"单位": "毫米", "打印比例": "1:1", "打印件": []}
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
