r"""离屏渲染单板自焊版的扳机局部与开关支架装配示意；不截取桌面。

运行：E:\GunMouseCAD\CadQuery\python.exe -B scripts\render_holder.py（先运行 economy_holder.py）
"""
import json
import sys
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from economy_holder import SCREW_FIX, screw  # noqa: E402
from economy_trigger import box, load_ev, prism_xz  # noqa: E402
from evt_a.render_evt_a import label, render  # noqa: E402

MODELS = ROOT / "outputs" / "economy-holder"
DELIVER = ROOT / "deliverables" / "经济型单板自焊版"


def main():
    cfg = json.loads((ROOT / "config" / "economy-trigger.json").read_text(encoding="utf-8"))
    ev = load_ev(cfg)
    ev["trigger_adjust"].update(SCREW_FIX)
    load = lambda p: cq.importers.importStep(str(p)).val()
    right = load(MODELS / "right.step").intersect(box(-26, 24, -20, 8, -40, 3))
    holder = load(MODELS / "holder.step")
    rigid = load(MODELS / "switch-rigid-nominal.step")
    hardware = load(MODELS / "m2-hardware.step")
    wires = load(MODELS / "wires-nominal.step")
    trigger = load(MODELS / "trigger.step")
    fork = load(DELIVER / "打印文件" / "扳机设定片-经济型-1.0mm.step")
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
    out = DELIVER / "预览图"
    out.mkdir(parents=True, exist_ok=True)

    items = [(right, (0.55, 0.65, 0.79), 0.35), (holder, (0.25, 0.45, 0.85), 1.0),
             (rigid, (0.16, 0.17, 0.19), 1.0), (lever, (0.7, 0.7, 0.73), 1.0),
             (hardware, (0.75, 0.75, 0.75), 1.0), (wires, (0.85, 0.15, 0.15), 1.0),
             (trigger.translate(cq.Vector(shift, 0, 0)), (0.92, 0.55, 0.16), 1.0),
             (bolt, (0.7, 0.45, 0.08), 1.0), (fork, (0.25, 0.67, 0.9), 1.0)]
    image = render(items, focal=(-7, 0, -18), position=(-7, 200, -18), view_up=(0, 0, 1), scale=22, size=(1200, 1000))
    label(image, ["单板自焊版：拿掉左半壳，从左侧看，扳机按到1.0毫米片",
                  "蓝=支架，黑=开关，红=尾线，橙=扳机，棕=调节螺钉，浅蓝=1.0毫米片",
                  "灰色直摆杆为原厂动作位置示意；开关不是供应商精确三维模型"]).save(out / "扳机设定局部.png")

    items = [(holder, (0.25, 0.45, 0.85), 1.0), (rigid, (0.16, 0.17, 0.19), 1.0), (lever, (0.95, 0.8, 0.1), 1.0),
             (hardware, (0.75, 0.75, 0.75), 1.0), (wires, (0.85, 0.15, 0.15), 1.0)]
    image = render(items, focal=(-14, 0, -16), position=(80, 70, 25), view_up=(0, 0, 1), scale=26, size=(1200, 1000))
    label(image, ["开关支架装配：开关焊片穿过中央窗口，两根尾线沿窗口下行，从支架底部出线",
                  "开关用两颗M2×16螺钉和M2螺母夹在支架两侧凸台之间；卡板插入原小板卡槽",
                  "蓝=支架，黑=开关，黄=摆杆（自由端朝下、朝出线口），灰=螺钉螺母，红=尾线"]).save(out / "开关支架装配.png")
    print(out)


if __name__ == "__main__":
    main()
