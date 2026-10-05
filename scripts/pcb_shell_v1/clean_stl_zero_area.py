"""仅删除二进制 STL 中面积严格为零的退化三角面，不改其余面或实体外形。

用法：E:\\GunMouseCAD\\CadQuery\\python.exe -B scripts\\pcb_shell_v1\\clean_stl_zero_area.py
应在 build_shell.py 之后运行，再用 verify_mechanical.py 核对交付网格。
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def clean(path):
    before = path.read_bytes()
    if len(before) < 84:
        raise ValueError(f"不是完整的二进制 STL：{path}")
    count = int.from_bytes(before[80:84], "little")
    if len(before) != 84 + count * 50:
        raise ValueError(f"本脚本只处理二进制 STL，不转换文本或猜测格式：{path}")
    dtype = np.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attr", "<u2")])
    triangles = np.frombuffer(before[84:], dtype=dtype)
    vertices = triangles["vertices"].astype(np.float64)
    cross = np.cross(vertices[:, 1] - vertices[:, 0], vertices[:, 2] - vertices[:, 0])
    keep = np.any(cross != 0, axis=1)
    removed = np.flatnonzero(~keep).tolist()
    after = before
    if removed:
        # 保留的面记录逐字节不变；仅更新面数量并去掉严格零面积记录。
        after = before[:80] + struct.pack("<I", int(keep.sum())) + triangles[keep].tobytes()
        path.write_bytes(after)
    return {"file": str(path), "removed_triangle_indices": removed,
            "triangles_before": count, "triangles_after": int(keep.sum()),
            "sha256_before": hashlib.sha256(before).hexdigest(),
            "sha256_after": hashlib.sha256(after).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description="清理严格零面积网格面，保留其余表面")
    parser.add_argument("--directory", type=Path, default=ROOT / "deliverables" / "pcb-shell-v1" / "打印文件" / "STL")
    parser.add_argument("--report", type=Path, default=ROOT / "outputs" / "pcb-shell-v1" / "stl-zero-area-cleanup.json")
    args = parser.parse_args()
    files = [clean(p) for p in sorted(args.directory.glob("*.stl"))]
    report = {"method": "只删除面积严格为零的三角形；不修改任何非零面积面或 STEP 实体", "files": files}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(files), "removed_triangles": sum(len(f["removed_triangle_indices"]) for f in files)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
