"""核对开关支架两颗 M2×16 用盘头或杯头内六角（ISO 4762）时，头部与壳体、支架、扳机全行程均不干涉。

先运行 economy_holder.py（读取其 outputs/economy-holder 下的实体）。
"""
import json
import sys
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
import economy_trigger as et  # noqa: E402
from build_shell import cyl_y  # noqa: E402
from verify_mechanical import volume_overlap  # noqa: E402

MODELS = ROOT / "outputs" / "economy-holder"
# 盘头为原检查尺寸；杯头按商家实测头径3.9、头厚2.0，并另加余量 4.0×2.1 检查。
HEADS = {"盘头_头径4.0_头高1.6": (4.0, 1.6), "杯头内六角_头径3.9_头高2.0": (3.9, 2.0),
         "杯头内六角加余量_头径4.0_头高2.1": (4.0, 2.1)}


def main():
    cfg = json.loads((ROOT / "config" / "economy-trigger.json").read_text(encoding="utf-8"))
    _, _, holes = et.switch_models(cfg)
    load = lambda name: cq.importers.importStep(str(MODELS / f"{name}.step")).val()
    left, right, holder, trigger = (load(n) for n in ("left", "right", "holder", "trigger"))
    seat, travel = cfg["holder"]["boss_y"][1], cfg["trigger"]["travel_mm"]
    report = {}
    for name, (d, k) in HEADS.items():
        heads = [cyl_y(x, z, d / 2, seat, seat + k) for x, z in holes]
        result = {"左壳mm3": sum(volume_overlap(h, left) for h in heads),
                  "右壳mm3": sum(volume_overlap(h, right) for h in heads),
                  "支架mm3": sum(volume_overlap(h, holder) for h in heads),
                  "扳机静止半程到底mm3": max(sum(volume_overlap(h, trigger.translate(cq.Vector(-t, 0, 0))) for h in heads)
                                         for t in (0.0, travel / 2, travel)),
                  "到左右壳最小距离mm": min(min(float(h.distance(left)), float(h.distance(right))) for h in heads)}
        for key, value in result.items():
            if key.endswith("mm3"):
                et.zero(name + key, value)
        report[name] = result
    out = MODELS / "支架螺钉头核对.json"
    out.write_text(json.dumps({"范围": "支架两颗M2×16螺钉头部包络；螺母侧与螺杆沿用economy_holder.py检查",
                               "结果": report}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
