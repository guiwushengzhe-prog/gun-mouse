"""核对单板自焊版左壳与已通过GY模块适配检查的左壳为同一实体（不移槽）。"""
import hashlib
import json
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]
GY_LEFT = ROOT / "deliverables" / "经济型改版" / "打印文件" / "左半壳-经济型.step"
NEW_LEFT = ROOT / "deliverables" / "经济型单板自焊版" / "打印文件" / "左半壳-单板自焊.step"
OUT = ROOT / "outputs" / "economy-holder" / "左壳与GY适配核对.json"


def main():
    a, b = (cq.importers.importStep(str(p)).val() for p in (GY_LEFT, NEW_LEFT))
    box = lambda s: [round(v, 4) for v in (lambda x: (x.xmin, x.xmax, x.ymin, x.ymax, x.zmin, x.zmax))(s.BoundingBox())]
    result = {"GY适配检查所用左壳": str(GY_LEFT.relative_to(ROOT)),
              "GY适配检查所用左壳SHA256": hashlib.sha256(GY_LEFT.read_bytes()).hexdigest(),
              "本版左壳": str(NEW_LEFT.relative_to(ROOT)),
              "本版左壳SHA256": hashlib.sha256(NEW_LEFT.read_bytes()).hexdigest(),
              "体积mm3": [round(a.Volume(), 3), round(b.Volume(), 3)], "包围盒mm": [box(a), box(b)],
              "差集mm3": {"GY版减本版": a.cut(b).Volume(), "本版减GY版": b.cut(a).Volume()}}
    result["同一实体"] = max(result["差集mm3"].values()) < 1e-6 and result["包围盒mm"][0] == result["包围盒mm"][1]
    if not result["同一实体"]:
        raise ValueError("左壳与GY适配检查所用左壳不同")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
