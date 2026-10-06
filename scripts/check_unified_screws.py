"""核对全机螺丝统一为 M2 杯头内六角（GB70.1/DIN912）两种长度：M2×10 与 M2×20。

- 合壳 7 颗：PA2×20 盘头自攻 → M2×20 杯头；长度不变，头部落在原 Ø4.4 沉孔内，检查不冒出外壳。
- GY 压框 2 颗：PA2×10 盘头自攻 → M2×10 杯头；长度不变，杯头更高，按各支持板厚复查头部障碍。
- 开关支架 2 颗：M2×16 → M2×20；螺杆多伸出 4 毫米，检查与壳体、主板、扳机全行程和尾线。
- 扳机调节 1 颗：本就是 M2×10 杯头，由 economy_holder.py 检查。
导孔均为 Ø1.7，与扳机 M2 机牙自攻导孔相同，不改任何打印件。先运行 economy_holder.py。
"""
import json
import sys
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
import economy_trigger as et  # noqa: E402
from build_shell import Shell, cyl_y  # noqa: E402
from economy_mechanical import obstruction_volume, overlap  # noqa: E402
from verify_mechanical import volume_overlap  # noqa: E402

V = cq.Vector
HOLDER = ROOT / "outputs" / "economy-holder"
OUT = HOLDER / "螺丝统一核对.json"
CUP_D, CUP_K = 4.0, 2.1  # 商家实测头径3.9、头厚2.0；按4.0×2.1保守检查


def compound(items):
    return cq.Compound.makeCompound(items)


def main():
    shell_cfg = json.loads((ROOT / "config" / "pcb-shell-v1.json").read_text(encoding="utf-8"))
    mech = json.loads((ROOT / "config" / "economy-mechanical.json").read_text(encoding="utf-8"))
    trig_cfg = json.loads((ROOT / "config" / "economy-trigger.json").read_text(encoding="utf-8"))
    load = lambda p: cq.importers.importStep(str(p)).val()
    left, right, holder, trigger = (load(HOLDER / f"{n}.step") for n in ("left", "right", "holder", "trigger"))
    wires = load(HOLDER / "wires-nominal.step")
    model_dir = Path(mech["source_models"])
    pcb, dev, knob = (load(model_dir / f"{n}.step") for n in ("pcb", "dev", "knob"))
    board_solids = [(s, [s.BoundingBox().xmin, s.BoundingBox().xmax, s.BoundingBox().ymin,
                         s.BoundingBox().ymax, s.BoundingBox().zmin, s.BoundingBox().zmax]) for s in pcb.Solids()]
    report = {"统一方案": {"M2×10杯头内六角": "扳机调节1 + GY压框2 = 每套3颗",
                       "M2×20杯头内六角": "合壳7 + 开关支架2 = 每套9颗", "M2六角螺母": "开关支架2颗",
                       "工具": "1.5毫米内六角扳手一把"},
              "检查头部尺寸mm": {"头径": CUP_D, "头厚": CUP_K}}

    # 1. 合壳：头座 head_seat_y，向外长出头厚；须完全在原外壳外轮廓之内、且不吃到右壳实体。
    sc, s = shell_cfg["shell"]["screw"], shell_cfg["shell"]
    seat = sc["head_seat_y"]
    points = [tuple(h["xz"]) for h in shell_cfg["board"]["mount_holes"]] + [tuple(p) for p in s["shell_only_screws_xz"]]
    envelope = Shell(shell_cfg).outer
    shell_rows = {}
    for x, z in points:
        head = cyl_y(x, z, CUP_D / 2, seat - CUP_K, seat)
        row = {"头部伸出外壳轮廓mm3": head.cut(envelope).Volume(), "头部与右壳实体mm3": volume_overlap(head, right),
               "沉孔径mm": sc["head_counterbore_d"]}
        # 外表面到头顶的余量：沿头轴向外逐步探测，直到探针离开外轮廓。
        depth = 0.0
        while depth < 10 and cyl_y(x, z, 0.05, seat - CUP_K - depth - 0.1, seat - CUP_K - depth).cut(envelope).Volume() < 1e-9:
            depth += 0.1
        row["头顶低于外壳表面约mm"] = round(depth, 1)
        for key in ("头部伸出外壳轮廓mm3", "头部与右壳实体mm3"):
            et.zero(f"合壳螺丝{(x, z)}{key}", row[key])
        shell_rows[f"X{x}_Z{z}"] = row
    report["合壳7颗_M2×20杯头"] = shell_rows

    # 2. GY 压框：头部朝主板/开发板一侧，按全部支持板厚检查。
    m, c = mech["module"], mech["clamp"]
    gy_rows = {}
    for thickness in m["board_thickness_supported"]:
        front = m["component_face_y"] - thickness - c["thickness"]
        heads = compound([cyl_y(x, z, CUP_D / 2, front - CUP_K, front) for x, z in c["mounts_xz"]])
        row = {"螺丝头与左壳": overlap(heads, left), "螺丝头与开发板": overlap(heads, dev),
               "螺丝头与主板含元件": obstruction_volume(heads, board_solids)}
        joystick = shell_cfg["joystick"]
        pivot = V(joystick["shaft_xz"][0], shell_cfg["board"]["top_face_y"] + joystick["pivot_above_pcb_assumed"],
                  joystick["shaft_xz"][1])
        row["螺丝头与摇杆帽±20度"] = max(overlap(knob.rotate(pivot, pivot + axis, a), heads)
                                   for axis in (V(1, 0, 0), V(0, 0, 1)) for a in (-20, 20))
        for key, value in row.items():
            et.zero(f"GY压框板厚{thickness}{key}", value)
        gy_rows[str(thickness)] = row
    report["GY压框2颗_M2×10杯头_各板厚mm3"] = gy_rows

    # 3. 开关支架：M2×20 从凸台顶面向 -Y 伸出，检查螺杆全长。
    h = trig_cfg["holder"]
    _, _, holes = et.switch_models(trig_cfg)
    top = h["boss_y"][1]
    shanks = compound([cyl_y(x, z, 1.0, top - 20.0, top) for x, z in holes])
    tips = compound([cyl_y(x, z, 1.0, top - 20.0, top - 16.0) for x, z in holes])
    travel = trig_cfg["trigger"]["travel_mm"]
    holder_row = {"加长段与左壳": volume_overlap(tips, left), "加长段与右壳": volume_overlap(tips, right),
                  "加长段与支架": volume_overlap(tips, holder), "加长段与尾线": volume_overlap(tips, wires),
                  "加长段与主板含元件": obstruction_volume(tips, board_solids),
                  "加长段与扳机静止半程到底": max(volume_overlap(tips, trigger.translate(V(-t, 0, 0)))
                                          for t in (0.0, travel / 2, travel)),
                  "螺尖Y": top - 20.0, "螺尖到左右壳最小距离mm": min(float(tips.distance(left)), float(tips.distance(right)))}
    for key, value in holder_row.items():
        if key.startswith("加长段"):
            et.zero("支架M2×20" + key, value)
    report["开关支架2颗_M2×20"] = holder_row
    report["结论"] = "统一为M2×10与M2×20两种杯头内六角加M2螺母，打印件不需修改"
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
