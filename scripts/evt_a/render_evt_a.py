r"""离屏渲染 EVT-A 扳机设定示意图，供组装说明使用。

运行：E:\GunMouseCAD\CadQuery\python.exe -B scripts\evt_a\render_evt_a.py
"""
import json
import sys
from io import BytesIO
from pathlib import Path

import cadquery as cq
import vtk
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_evt_a_parts import build_fork, screw  # noqa: E402

PARTS = ROOT / "deliverables" / "evt-a" / "打印文件"
OUT = ROOT / "deliverables" / "evt-a" / "预览图"


def actor(shape, color, opacity):
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(shape.toVtkPolyData(tolerance=0.03, angularTolerance=0.15, normals=True))
    a = vtk.vtkActor()
    a.SetMapper(mapper)
    a.GetProperty().SetColor(*color)
    a.GetProperty().SetOpacity(opacity)
    a.GetProperty().SetInterpolationToPhong()
    return a


def render(items, focal, position, view_up, scale, size=(1200, 900)):
    ren = vtk.vtkRenderer()
    ren.SetBackground(0.97, 0.97, 0.98)
    ren.SetUseDepthPeeling(True)
    ren.SetMaximumNumberOfPeels(60)
    for shape, color, opacity in items:
        ren.AddActor(actor(shape, color, opacity))
    cam = ren.GetActiveCamera()
    cam.SetFocalPoint(*focal)
    cam.SetPosition(*position)
    cam.SetViewUp(*view_up)
    cam.ParallelProjectionOn()
    cam.SetParallelScale(scale)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetAlphaBitPlanes(1)
    win.SetMultiSamples(0)
    win.AddRenderer(ren)
    win.SetSize(*size)
    win.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetWriteToMemory(1)
    writer.SetInputConnection(grab.GetOutputPort())
    writer.Write()
    return Image.open(BytesIO(bytes(writer.GetResult())))


def label(img, lines):
    img = img.convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype("msyh.ttc", 26)
    width = max(draw.textlength(text, font=font) for text in lines)
    draw.rectangle((12, 10, 36 + width, 22 + 36 * len(lines)), fill=(255, 255, 255, 225))
    for i, text in enumerate(lines):
        draw.text((24, 16 + 36 * i), text, fill=(30, 30, 30, 255), font=font)
    return Image.alpha_composite(img, layer).convert("RGB")


def main():
    cfg = json.loads((ROOT / "config" / "pcb-shell-v1.json").read_text(encoding="utf-8"))
    ev = json.loads((ROOT / "config" / "evt-a.json").read_text(encoding="utf-8"))
    sw = cfg["trigger"]["switch_contact_from_board"]
    travel = sw["rest"] - sw["stop"]
    load = lambda p: cq.importers.importStep(str(p)).val()  # noqa: E731
    right = load(PARTS / "右半壳-EVT-A.step")
    trigger = load(PARTS / "扳机-EVT-A.step")
    daughter = load(ROOT / ev["base"]["board_models"] / "daughter.step")
    t = 1.0
    shift = -travel + t
    bolt = screw(ev["trigger_adjust"], 0.0)
    fork = build_fork(ev, t, ev["single_stop_datum"]["block"]["x"][1])
    OUT.mkdir(parents=True, exist_ok=True)
    clip = cq.Solid.makeBox(60, 40, 50, cq.Vector(-35, -25, -40))
    right_local = right.intersect(clip)
    items = [(right_local, (0.55, 0.64, 0.76), 0.45), (daughter, (0.5, 0.3, 0.65), 1.0),
             (trigger.translate(cq.Vector(shift, 0, 0)), (0.2, 0.2, 0.22), 1.0),
             (bolt.translate(cq.Vector(shift, 0, 0)), (0.85, 0.55, 0.1), 1.0),
             (fork, (0.15, 0.6, 0.35), 1.0)]
    img = render(items, focal=(-6, 0, -18), position=(-6, 200, -18), view_up=(0, 0, 1), scale=16)
    label(img, ["扳机设定：左半壳拿掉，右半壳平放，从左侧(+Y)看",
                "绿=1.0 mm 设定片（夹在滑杆后端面与弹簧座之间，开口跨过弹簧）",
                "橙=M2 外六角螺栓：头部就是触点，往外拧压得更深，往里拧变浅"]).save(OUT / "01-扳机设定位置.png")
    img = render([(trigger, (0.2, 0.2, 0.22), 1.0), (bolt, (0.85, 0.55, 0.1), 1.0)],
                 focal=(0, 0, -18), position=(-120, 140, 20), view_up=(0, 0, 1), scale=12)
    label(img, ["扳机尾部：螺栓头槽在 +Y 侧开口，可直接用手指或镊子转动",
                "触摸线槽在尾段移到 +Y 侧，给螺栓头让位"]).save(OUT / "02-扳机尾部螺栓.png")
    print("saved", OUT)


if __name__ == "__main__":
    main()
