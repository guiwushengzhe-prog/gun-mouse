"""离屏渲染 PCB-Shell-V1 预览图（读取 build_shell.py 输出的单件 STEP），不截取桌面。

输出：deliverables/pcb-shell-v1/预览图/*.png
"""

import sys
from io import BytesIO
from pathlib import Path

import cadquery as cq
import vtk
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUT, ROOT  # noqa: E402

MODELS = OUTPUT / "preview-models"
OUT = ROOT / "deliverables" / "pcb-shell-v1" / "预览图"

COLORS = {
    "left": ((0.62, 0.72, 0.82), 0.35), "right": ((0.50, 0.60, 0.72), 0.35),
    "trigger": ((0.18, 0.18, 0.2), 1.0), "cover": ((0.25, 0.55, 0.9), 1.0),
    "cap": ((0.18, 0.18, 0.2), 1.0), "knob": ((0.12, 0.12, 0.12), 1.0),
    "dev": ((0.15, 0.35, 0.75), 0.9), "battery": ((0.85, 0.75, 0.3), 0.8),
    "pcb": ((0.1, 0.55, 0.28), 1.0), "daughter": ((0.5, 0.3, 0.65), 1.0),
}


def load(name):
    path = MODELS / f"{name}.step"
    return cq.importers.importStep(str(path)).val() if path.exists() else None


def actor(shape, color, opacity):
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(shape.toVtkPolyData(tolerance=0.05, angularTolerance=0.2, normals=True))
    a = vtk.vtkActor()
    a.SetMapper(mapper)
    a.GetProperty().SetColor(*color)
    a.GetProperty().SetOpacity(opacity)
    a.GetProperty().SetInterpolationToPhong()
    return a


def render(shapes, position, view_up=(0, 0, 1), size=(1100, 820), zoom=1.1, overrides=None):
    ren = vtk.vtkRenderer()
    ren.SetBackground(0.97, 0.97, 0.98)
    ren.SetUseDepthPeeling(True)
    ren.SetMaximumNumberOfPeels(60)
    for name, shape in shapes.items():
        color, opacity = (overrides or {}).get(name, COLORS[name])
        ren.AddActor(actor(shape, color, opacity))
    cam = ren.GetActiveCamera()
    cam.SetFocalPoint(25, 0, -25)
    cam.SetPosition(*position)
    cam.SetViewUp(*view_up)
    cam.ParallelProjectionOn()
    ren.ResetCamera()
    cam.Zoom(zoom)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(True)
    win.SetMultiSamples(0)
    win.SetAlphaBitPlanes(True)
    win.SetSize(*size)
    win.AddRenderer(ren)
    try:
        win.Render()
        grab = vtk.vtkWindowToImageFilter()
        grab.SetInput(win)
        grab.ReadFrontBufferOff()
        grab.Update()
        w = vtk.vtkPNGWriter()
        w.SetWriteToMemory(True)
        w.SetInputConnection(grab.GetOutputPort())
        w.Write()
        return Image.open(BytesIO(memoryview(w.GetResult()).tobytes())).convert("RGB")
    finally:
        win.Finalize()


def caption(img, text):
    draw = ImageDraw.Draw(img)
    font = None
    for f in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]:
        if Path(f).exists():
            font = ImageFont.truetype(f, 26)
            break
    draw.rectangle([0, 0, img.width, 44], fill=(255, 255, 255))
    draw.text((16, 8), text, fill=(30, 30, 30), font=font)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    m = {n: load(n) for n in COLORS}
    m = {k: v for k, v in m.items() if v is not None}
    inner = {k: v for k, v in m.items() if k not in ("left", "right")}
    views = [
        ("01-整机左前视.png", {**m}, (160, 260, 60), "整机（外壳半透明）：左侧可见摇杆帽与右键帽", None),
        ("02-右半壳内部.png", {k: v for k, v in m.items() if k != "left"}, (20, 300, -10),
         "取下左半壳：主板、开发板、扳机小板、电池仓与滑动扳机", {"right": ((0.55, 0.65, 0.78), 1.0)}),
        ("03-右半壳空壳.png", {"right": m["right"]}, (20, 300, -10), "右半壳内部结构：螺柱、支撑柱、卡槽、电池仓、扳机滑道",
         {"right": ((0.55, 0.65, 0.78), 1.0)}),
        ("04-左半壳空壳.png", {"left": m["left"]}, (20, -300, -10), "左半壳内部结构：压板螺柱、摇杆开口、右键开口、导轨",
         {"left": ((0.62, 0.72, 0.84), 1.0)}),
        ("05-内部器件.png", inner, (120, 220, 80), "内部器件与机构件（不含外壳）", None),
    ]
    for fname, shapes, pos, text, ov in views:
        img = render(shapes, pos, overrides=ov)
        caption(img, text).save(OUT / fname)
        print(OUT / fname)


if __name__ == "__main__":
    main()
