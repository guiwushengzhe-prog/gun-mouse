r"""离屏渲染工厂代焊 SS-01GL 小板局部示意；不截取桌面。"""
import json
import sys
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from economy_trigger import box, load_ev, prism_xz, screw  # noqa: E402
from evt_a.render_evt_a import label, render  # noqa: E402


def main():
    cfg = json.loads((ROOT / "config" / "economy-trigger.json").read_text(encoding="utf-8"))
    ev = load_ev(cfg)
    models = ROOT / "outputs" / "economy-trigger"
    parts = ROOT / "deliverables" / "经济型工厂代焊版" / "打印文件"
    output = ROOT / "deliverables" / "经济型工厂代焊版" / "预览图" / "扳机设定局部.png"
    load = lambda p: cq.importers.importStep(str(p)).val()
    clip = box(-26, 24, -20, 8, -40, 3)
    right = load(models / "right.step").intersect(clip)
    daughter = load(models / "daughter-reference.step")
    rigid = load(models / "switch-rigid-nominal.step")
    trigger = load(models / "trigger.step")
    fork = load(parts / "扳机设定片-经济型-1.0mm.step")
    travel = cfg["trigger"]["travel_mm"]
    shift = -travel + 1.0
    switch = cfg["switch"]
    op_x = switch["body_bottom_x"] + sum(switch["operating_height_from_bottom"]) / 2
    za = switch["body_left_z"] - switch["action_from_left"]
    xp = switch["body_bottom_x"] + switch["body_envelope_height"]
    zp = switch["body_left_z"] - 3.4
    lever = prism_xz([(xp, zp), (op_x, za), (op_x - 0.3, za), (xp - 0.3, zp)], -1.8, 1.8)
    delta = ev["trigger_adjust"]["nominal_face_x"] + shift - op_x
    bolt = screw(ev["trigger_adjust"], delta).translate(cq.Vector(shift, 0, 0))
    items = [(right, (0.55, 0.65, 0.79), 0.35), (daughter, (0.2, 0.55, 0.35), 1.0),
             (rigid, (0.16, 0.17, 0.19), 1.0), (lever, (0.7, 0.7, 0.73), 1.0),
             (trigger.translate(cq.Vector(shift, 0, 0)), (0.92, 0.55, 0.16), 1.0),
             (bolt, (0.7, 0.45, 0.08), 1.0), (fork, (0.25, 0.67, 0.9), 1.0)]
    image = render(items, focal=(-7, 0, -18), position=(-7, 200, -18),
                   view_up=(0, 0, 1), scale=22, size=(1200, 1000))
    output.parent.mkdir(parents=True, exist_ok=True)
    label(image, ["工厂代焊小板版：拿掉左半壳，从左侧看，扳机按到1.0毫米片",
                  "绿=小板和连接器，黑=SS-01GL本体，橙=新扳机，蓝=1.0毫米设定片",
                  "灰色直摆杆为原厂动作位置示意；开关不是供应商精确三维模型"]).save(output)
    print(output)


if __name__ == "__main__":
    main()
