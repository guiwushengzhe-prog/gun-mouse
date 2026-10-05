"""按配置重建内部规划占位；仅离屏渲染，不生成制造文件。"""
import json
import math
from io import BytesIO
from pathlib import Path

import cadquery as cq
import vtk
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "internal-layout-v1"
SIZE = (1580, 1100)
FONT = "C:/Windows/Fonts/msyh.ttc"
BOLD = "C:/Windows/Fonts/msyhbd.ttc"


def rgb(value):
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


def box(region):
    return cq.Workplane("XY").box(*region["planning_size_xyz_mm"]).translate(
        region["center_xyz_mm"]).val()


def plane(length, width, center):
    wire = cq.Workplane("XY").rect(length, width).val()
    return cq.Face.makeFromWires(wire).translate(cq.Vector(*center))


def build(config):
    shapes = []
    shell = config["shell"]
    thickness = shell["planning_thickness_mm"]
    silhouette = cq.Workplane("XZ").polyline(shell["outline_xz_mm"]).close().extrude(
        thickness).translate((0, thickness / 2, 0)).val()
    shapes.append(("外壳轮廓规划体", silhouette, "#8092a1", 0.08))
    for region in config["regions"]:
        opacity = 0.70 if region["id"] == "trigger_switch" else 0.22
        shapes.append((region["name"], box(region), region["color"], opacity))
        x, y, z = region["center_xyz_mm"]
        bottom = z - region["planning_size_xyz_mm"][2] / 2
        if region["id"] == "main_controller":
            cx = region["main_board_center_x_mm"]
            length = region["board_outline_long_mm"]
            width = region["board_outline_short_mm"]
            extension = region["antenna_extension_mm"]
            shapes.append(("主控主板资料平面（零厚度）", plane(length, width, (cx, y, bottom)),
                           "#157641", 0.96))
            shapes.append(("天线伸出资料平面（零厚度）", plane(extension, width,
                           (cx + length / 2 + extension / 2, y, bottom)), "#f4c547", 0.96))
        if region["id"] == "imu":
            a, b, h = region["documented_size_mm"]
            nominal = cq.Workplane("XY").box(b, a, h).translate((x, y, bottom + h / 2)).val()
            shapes.append(("惯性模块资料标称体（不含排针总高）", nominal, region["color"], 0.85))
    return shapes


def add_actor(renderer, shape, color, opacity):
    data = shape.toVtkPolyData(tolerance=0.05, angularTolerance=0.12, normals=True)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(data)
    item = vtk.vtkActor()
    item.SetMapper(mapper)
    item.GetProperty().SetColor(*rgb(color))
    item.GetProperty().SetOpacity(opacity)
    item.GetProperty().SetInterpolationToPhong()
    renderer.AddActor(item)
    edges = vtk.vtkFeatureEdges()
    edges.SetInputData(data)
    edges.FeatureEdgesOn()
    edges.BoundaryEdgesOn()
    edges.ManifoldEdgesOff()
    edges.NonManifoldEdgesOff()
    edges.ColoringOff()
    edge_map = vtk.vtkPolyDataMapper()
    edge_map.SetInputConnection(edges.GetOutputPort())
    outline = vtk.vtkActor()
    outline.SetMapper(edge_map)
    outline.GetProperty().SetColor(*rgb(color))
    outline.GetProperty().SetOpacity(0.50 if opacity < 0.1 else 0.88)
    outline.GetProperty().SetLineWidth(1.5)
    renderer.AddActor(outline)


def render(shapes, side, regions):
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.965, 0.976, 0.988)
    renderer.SetUseDepthPeeling(True)
    renderer.SetMaximumNumberOfPeels(100)
    renderer.SetOcclusionRatio(0.01)
    for _, shape, color, opacity in shapes:
        add_actor(renderer, shape, color, opacity)
    camera = renderer.GetActiveCamera()
    focus = (25, 0, -27)
    camera.SetFocalPoint(*focus)
    camera.SetPosition(*(25, 430, -27) if side else (235, 330, 175))
    camera.SetViewUp(0, 0, 1)
    camera.ParallelProjectionOn()
    renderer.ResetCamera()
    camera.Zoom(1.14)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(True)
    window.SetAlphaBitPlanes(True)
    window.SetMultiSamples(0)
    window.SetSize(*SIZE)
    window.AddRenderer(renderer)
    try:
        window.Render()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(window)
        capture.ReadFrontBufferOff()
        capture.Update()
        writer = vtk.vtkPNGWriter()
        writer.SetWriteToMemory(True)
        writer.SetInputConnection(capture.GetOutputPort())
        writer.Write()
        picture = Image.open(BytesIO(memoryview(writer.GetResult()).tobytes())).convert("RGB")
        def project(point):
            renderer.SetWorldPoint(*point, 1)
            renderer.WorldToDisplay()
            x, y, _ = renderer.GetDisplayPoint()
            return x + 40, SIZE[1] - y + 180
        points = {name: project(point) for name, point in (
            ("origin", (0, 0, 0)), ("x", (25, 0, 0)), ("y", (0, 25, 0)),
            ("z", (0, 0, 25)), ("front", (118, 0, 47)), ("back", (-67, 0, 47)))}
        centers = {region["id"]: project(region["center_xyz_mm"]) for region in regions}
        return picture, centers, points
    finally:
        window.Finalize()


def wrapped(draw, text, xy, font, width, fill="#486071"):
    x, y = xy
    line = ""
    for char in text:
        if draw.textlength(line + char, font=font) > width and line:
            draw.text((x, y), line, font=font, fill=fill)
            y += font.size + 5
            line = ""
        line += char
    draw.text((x, y), line, font=font, fill=fill)
    return y + font.size + 5


def decorate(config, rendered, side):
    picture, centers, axes = rendered
    canvas = Image.new("RGB", (2220, 1510), "#f6f9fc")
    canvas.paste(picture, (40, 180))
    draw = ImageDraw.Draw(canvas)
    title = ImageFont.truetype(BOLD, 44)
    label = ImageFont.truetype(FONT, 26)
    small = ImageFont.truetype(FONT, 22)
    number = ImageFont.truetype(BOLD, 25)
    view = "左侧投影 · 前方在左" if side else "左前上方透视 · 同一坐标"
    draw.text((48, 32), "内部布局占位参考 / " + view, font=title, fill="#18384e")
    draw.text((50, 98), "透明盒＝规划空间；板面＝资料平面。不是制造模型或已验证装配。", font=label, fill="#526879")
    for index, region in enumerate(config["regions"], 1):
        px, py = centers[region["id"]]
        draw.rounded_rectangle((px - 20, py - 20, px + 20, py + 20), radius=7, fill="white", outline=region["color"], width=3)
        draw.text((px, py), str(index), font=number, anchor="mm", fill="#243b4e")
        y = 183 + (index - 1) * 111
        draw.rounded_rectangle((1650, y, 1690, y + 40), radius=6, fill=region["color"])
        draw.text((1670, y + 20), str(index), font=number, anchor="mm", fill="white")
        next_y = wrapped(draw, region["name"], (1704, y), label, 463)
        values = " × ".join(f"{v:g}" for v in region["planning_size_xyz_mm"])
        wrapped(draw, "规划盒 X/Y/Z：" + values + " 毫米", (1704, next_y + 3), small, 463)
    for key, text in (("front", "前 / X+"), ("back", "后 / X−")):
        px, py = axes[key]
        draw.text((px, py), text, font=label, fill="#344f65", anchor="mm")
    anchor = (230, 1190)
    ox, oy = axes["origin"]
    for key, text, color in (("x", "X 向前", "#ce5656"), ("y", "Y 向左", "#398d64"), ("z", "Z 向上", "#4377b5")):
        dx, dy = axes[key][0] - ox, axes[key][1] - oy
        length = math.hypot(dx, dy)
        if length < 1:
            draw.ellipse((anchor[0] - 8, anchor[1] - 8, anchor[0] + 8, anchor[1] + 8), outline=color, width=3)
            draw.text((anchor[0] - 140, anchor[1] + 25), text + "（朝向观察者）", font=small, fill=color)
            continue
        end = (anchor[0] + 88 * dx / length, anchor[1] + 88 * dy / length)
        draw.line((anchor, end), fill=color, width=4)
        draw.ellipse((end[0] - 4, end[1] - 4, end[0] + 4, end[1] + 4), fill=color)
        draw.text(end, text, font=small, fill=color, anchor="ms" if key == "z" else "mt")
    controller = next(r for r in config["regions"] if r["id"] == "main_controller")
    summary = report(config)
    notes = [
        f"主控：主板57.15×27.94；天线伸出6.24，总长63.39。{controller['planning_size_xyz_mm'][2]:g}毫米高度仅为预留。",
        "惯性模块：资料标称17.8×20.6×2.8；8毫米含接线规划高度尚未实测。",
        "普通PS2采用其他厂家尺寸参考盒，不能代替DZYJ实物；微动只表达参考壳体。",
        f"壳体厚{config['shell']['planning_thickness_mm']:g}毫米；摇杆外凸使规划总宽至少{summary['planning_total_thickness_mm']:g}毫米，帽、摆动及安装座另核对。",
        "主控规划盒与壳体的关系、盒间重叠见报告；未知高度、孔位与公差未定稿。",
    ]
    for i, text in enumerate(notes):
        draw.text((50, 1310 + i * 35), text, font=small, fill="#506474")
    return canvas


def report(config):
    regions = config["regions"]
    bounds = {r["id"]: [(c - s / 2, c + s / 2) for c, s in zip(r["center_xyz_mm"], r["planning_size_xyz_mm"])] for r in regions}
    overlaps = []
    for i, first in enumerate(regions):
        for second in regions[i + 1:]:
            extents = [min(a[1], b[1]) - max(a[0], b[0]) for a, b in zip(bounds[first["id"]], bounds[second["id"]])]
            if all(v > 0 for v in extents):
                overlaps.append({"first": first["name"], "second": second["name"], "box_overlap_xyz_mm": extents})
    t = config["shell"]["planning_thickness_mm"] / 2
    total_y = [min(-t, *(v[1][0] for v in bounds.values())), max(t, *(v[1][1] for v in bounds.values()))]
    return {"purpose": config["purpose"], "unit": "mm", "config": "config/internal-layout-v1.json",
            "planning_y_bounds_mm": total_y, "planning_total_thickness_mm": total_y[1] - total_y[0],
            "main_controller_planning_box_above_shell_top_mm": max(0, bounds["main_controller"][2][1] - max(p[1] for p in config["shell"]["outline_xz_mm"])),
            "region_box_overlaps": overlaps, "real_part_collision_acceptance": False,
            "height_and_mounting_holes_finalized": False, "limitations": config["limitations"]}


def main():
    config = json.loads((ROOT / "config" / "internal-layout-v1.json").read_text(encoding="utf-8-sig"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    shapes = build(config)
    assembly = cq.Assembly(name="内部布局占位参考")
    for index, (name, shape, color, opacity) in enumerate(shapes):
        assembly.add(shape, name=f"{index:02d}_{name}", color=cq.Color(*rgb(color), opacity))
    step = OUTPUT / "internal-layout-reference.step"
    assembly.export(str(step), exportType="STEP")
    for side, suffix in ((True, "left"), (False, "perspective")):
        path = OUTPUT / f"layout-reference-{suffix}.png"
        decorate(config, render(shapes, side, config["regions"]), side).save(path)
        print(path)
    summary = report(config)
    (OUTPUT / "layout-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(step)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
