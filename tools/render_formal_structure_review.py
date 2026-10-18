"""从实际装配OBJ生成多角度模型截图、单件截图和检视图册。"""
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"shell/长方条正式预览"
IMAGES = OUT/"多角度检视"
FONT = "C:/Windows/Fonts/msyh.ttc"
SIZE = (1280, 1120)


def load_model():
    colors, material = {}, None
    for line in (OUT/"第二代完整装配.mtl").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields and fields[0] == "newmtl":
            material = fields[1]
        elif fields and fields[0] == "Kd":
            colors[material] = tuple(map(float, fields[1:4]))
    parts, name, vertices, faces, offset = {}, None, [], [], 1
    def flush():
        if not vertices:
            return
        points = vtk.vtkPoints()
        points.SetData(numpy_to_vtk(np.asarray(vertices, dtype=np.float64), deep=True))
        cells = vtk.vtkCellArray()
        triangles = np.asarray([[len(face), *face] for face in faces], dtype=np.int64)
        cells.ImportLegacyFormat(numpy_to_vtkIdTypeArray(triangles.ravel(), deep=True))
        data = vtk.vtkPolyData()
        data.SetPoints(points)
        data.SetPolys(cells)
        parts[name] = (data, colors.get(material, (.6, .6, .6)))
    with (OUT/"第二代完整装配.obj").open(encoding="utf-8") as source:
        for line in source:
            fields = line.split()
            if not fields:
                continue
            if fields[0] == "o":
                flush()
                offset += len(vertices)
                name, vertices, faces = fields[1], [], []
            elif fields[0] == "usemtl":
                material = fields[1]
            elif fields[0] == "v":
                vertices.append(tuple(map(float, fields[1:4])))
            elif fields[0] == "f":
                faces.append([int(value.split("/")[0])-offset for value in fields[1:]])
    flush()
    return parts


def render(parts, selected, number, title, direction, note, *, shifts=None, opacity=None):
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(.94, .955, .97)
    renderer.SetUseDepthPeeling(True)
    renderer.SetMaximumNumberOfPeels(80)
    renderer.SetOcclusionRatio(.05)
    actors = []
    for name in selected:
        mesh, color = parts[name]
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(mesh)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        if name == "一体底座":
            color = (.30, .54, .64)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetAmbient(.24)
        actor.GetProperty().SetDiffuse(.72)
        actor.GetProperty().SetSpecular(.18)
        actor.GetProperty().SetSpecularPower(28)
        if shifts and name in shifts:
            actor.SetPosition(*shifts[name])
        if opacity and name in opacity:
            actor.GetProperty().SetOpacity(opacity[name])
        renderer.AddActor(actor)
        actors.append(actor)
    camera = renderer.GetActiveCamera()
    camera.SetPosition(direction[0]*200, -direction[2]*200, direction[1]*200)
    camera.SetFocalPoint(0, 0, 0)
    camera.SetViewUp(0, -1, 0)
    if abs(direction[2]) > .9 and abs(direction[0])+abs(direction[1]) < .01:
        camera.SetViewUp(0, 0, 1)
    camera.ParallelProjectionOn()
    renderer.ResetCamera()
    camera.Zoom(.95)
    renderer.ResetCameraClippingRange()
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(*SIZE)
    window.SetAlphaBitPlanes(1)
    window.SetMultiSamples(0)
    window.AddRenderer(renderer)
    window.Render()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.ReadFrontBufferOff()
    capture.Update()
    temporary = IMAGES/f"{number:02d}_raw.png"
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(temporary))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    window.Finalize()
    with Image.open(temporary) as original:
        canvas = Image.new("RGB", (SIZE[0], SIZE[1]+116), "white")
        canvas.paste(original.convert("RGB"), (0, 76))
    draw = ImageDraw.Draw(canvas)
    draw.text((28, 18), f"{number:02d}  {title}", font=ImageFont.truetype(FONT, 30), fill="#193748")
    draw.text((28, SIZE[1]+82), note, font=ImageFont.truetype(FONT, 18), fill="#435968")
    path = IMAGES/f"{number:02d}_{title}.png"
    canvas.save(path)
    temporary.unlink()
    print(path.name, flush=True)
    return path


def sheet(paths, name, title, columns=2):
    thumb = (640, 618)
    margin, top = 24, 80
    rows = (len(paths)+columns-1)//columns
    canvas = Image.new("RGB", (columns*thumb[0]+(columns+1)*margin,
                                rows*thumb[1]+top+(rows+1)*margin), "#e6edf2")
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 22), title, font=ImageFont.truetype(FONT, 32), fill="#153747")
    for i, path in enumerate(paths):
        with Image.open(path) as image:
            image = image.resize(thumb, Image.Resampling.LANCZOS)
            canvas.paste(image, (margin+(i%columns)*(thumb[0]+margin), top+margin+(i//columns)*(thumb[1]+margin)))
    target = IMAGES/name
    canvas.save(target)
    return target


def layout_plan():
    """按主板坐标画分区建议，明确区别于已布线的正式预览。"""
    config = json.loads((ROOT/"pcb/carrier-config.json").read_text(encoding="utf-8"))
    canvas = Image.new("RGB", (1800, 1320), "#eef3f7")
    draw = ImageDraw.Draw(canvas)
    font = lambda size: ImageFont.truetype(FONT, size)
    draw.text((45, 24), "整体重排建议｜先留机械安装带，再排电路", font=font(34), fill="#17394c")
    draw.text((45, 78), "左：当前正式预览的真实孔位   右：分区草案，仅做空间论证，尚未布线或替换现有文件", font=font(24), fill="#4c6270")
    parts = [p for p in config["parts"] if p["kind"] in {"resistor", "capacitor"} and p.get("populate", True)]
    proposals = []
    for index, part in enumerate(parts):
        center = -45.08 if index % 2 == 0 else -40
        proposals.append({"元件": part["ref"], "建议焊孔毫米": [[center-5.08, -12-3.5*index],
                                                                  [center+5.08, -12-3.5*index]]})
    for panel, origin in enumerate((140, 1030)):
        def point(x, z):
            return (origin+(x+60)*10, 225+(40-z)*10)
        def box(x0, x1, z0, z1, fill, outline):
            draw.rounded_rectangle((*point(x0, z1), *point(x1, z0)), radius=5, fill=fill, outline=outline, width=2)
        draw.text((origin-20, 148), "当前布局" if panel == 0 else "建议分区 · 未实施", font=font(29), fill="#17394c")
        draw.polygon([point(*p) for p in config["pcb"]["outline_xz"]], fill="#d8e9de", outline="#608b75", width=3)
        box(-58.965, -41.2, 13.9, 34.5, "#d0c0e1", "#8664a5")
        draw.text(point(-57.2, 26), "惯性模块", font=font(20), fill="#553b77")
        box(-33.5, -10, 13.5, 31.5, "#d0d7df", "#6b798b")
        draw.text(point(-31.5, 23), "主控模块", font=font(20), fill="#465268")
        box(-59.35, -46.65, 4.6, 11.4, "#b8cddd", "#5c86a2")
        draw.text(point(-58.4, 9.3), "电源开关", font=font(16), fill="#244b65")
        box(-54.7, -23.55, -9.9, 2.2, "#f1d1a3", "#c17c21")
        draw.text(point(-52.4, 1), "支座 / 机械安装带", font=font(21), fill="#784a13")
        for x, z in [(-51, -4), (-36.5, -4), (-27, -38), (-51, -38)]:
            px, py = point(x, z)
            draw.ellipse((px-12, py-12, px+12, py+12), fill="white", outline="#456374", width=3)
        for x, z in [(-30, -12), (-30, -14.54), (-25.5, -12), (-25.5, -9.46)]:
            px, py = point(x, z)
            draw.ellipse((px-7, py-7, px+7, py+7), fill="#267487")
        for index, part in enumerate(parts):
            pads = [p["xz"] for p in part["pads"]] if panel == 0 else proposals[index]["建议焊孔毫米"]
            a, b = [point(*p) for p in pads]
            color = "#bb3d3d" if panel == 0 and part["ref"] == "R_TRIG" else "#337c5b"
            draw.line([a, b], fill=color, width=5)
            for px, py in (a, b):
                draw.ellipse((px-10, py-10, px+10, py+10), fill="white", outline=color, width=3)
            draw.text(((a[0]+b[0])/2-26, a[1]-26), str(index+1), font=font(17), fill=color)
        if panel == 0:
            draw.text((origin-10, 1085), "红色两焊点被支座覆盖，靠4.5毫米内腔避让。", font=font(22), fill="#a23c37")
            draw.text((origin-10, 1124), "固定孔和焊点的位置互相牵制。", font=font(22), fill="#4c6270")
        else:
            draw.text((origin-10, 1085), "八颗小元件仍每行一颗，按交错两组孔位排布。", font=font(22), fill="#34684f")
            draw.text((origin-10, 1124), "先留空安装带，再核对铜线、器件本体和装配。", font=font(22), fill="#4c6270")
    draw.text((45, 1225), "保留摇杆现有朝向与电池位置。草案没有完成主板布线和强度验证，不用于打板。", font=font(25), fill="#334f62")
    target = IMAGES/"整体分区建议_未实施.png"
    canvas.save(target)
    (IMAGES/"分区建议坐标_未实施.json").write_text(json.dumps({"状态": "空间草案，未布线，未实施",
                                                        "建议小元件": proposals}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return target


def main():
    IMAGES.mkdir(parents=True, exist_ok=True)
    parts = load_model()
    all_parts = list(parts)
    base = ["一体底座"]
    support = ["独立摇杆支座"]
    upper = [name for name in all_parts if not name.startswith(("电池-", "一体底座"))]
    # 去掉底座与电芯是明确的检视视图，普通装配图全部保留。
    board = [name for name in all_parts if name.startswith("载板-")]
    simple = ["一体底座", "独立摇杆支座", *board]
    images = []
    jobs = [
        (all_parts, "完整装配_操作面斜视", (1, 1.6, 1.1), "完整装配，包含实际主板铜层、器件、导线及五金"),
        (all_parts, "完整装配_元件面斜视", (-1, -1.6, 1), "换侧检查电源开关、按键及电池托，不隐藏零件"),
        (all_parts, "完整装配_操作面正视", (0, 1, 0), "正交视图：检查摇杆投影和固定孔分布"),
        (all_parts, "完整装配_元件面正视", (0, -1, 0), "正交视图：护板覆盖下部元件，电池托向下延伸"),
        (all_parts, "完整装配_沿主板侧视", (1, 0, 0), "侧面检查板间距离、摇杆悬伸和螺丝方向"),
        (all_parts, "完整装配_顶部视图", (0, 0, 1), "从上方检查主板、摇杆小板与原生帽的空间关系"),
        (simple, "壳体与主板_操作面", (.8, 1.5, .8), "隐藏电子器件和五金，仅检查两件塑料与真实主板"),
        (simple, "壳体与主板_元件面", (-.8, -1.5, .8), "隐藏电子器件和五金，检查三个主体固定点"),
        (upper, "上部装配_摇杆与焊点", (-.7, 1.6, .9), "隐藏主体和电池，查看摇杆支座、焊点及接线孔"),
        (base, "主体底座_内侧全貌", (1, 1.5, .9), "单件：主体内侧、按键座、固定柱和电池托"),
        (base, "主体底座_外侧全貌", (-1, -1.5, .9), "单件：外表面与电池托底面"),
        (base, "主体底座_侧面", (1, .15, .15), "单件：侧壁高度、过渡和按键承托"),
        (base, "主体底座_内侧正视", (0, 1, 0), "单件：检查大外形、开口与固定孔的整体组织"),
        (support, "摇杆支座_外侧", (1, 1.5, .9), "单件：齐平外形，螺丝头下沉，边缘小圆角"),
        (support, "摇杆支座_主板内侧", (-1, -1.5, .7), "单件：主板焊点净空4.5毫米，保留完整螺丝承力柱"),
        (support, "摇杆支座_底面", (.5, 1.2, -1.2), "单件：两处摇杆螺丝的入口与内侧凹腔"),
        (support, "摇杆支座_端面", (1, 0, 0), "单件：检查凹腔和螺孔之间的壁厚"),
    ]
    for number, (selected, title, direction, note) in enumerate(jobs, 1):
        images.append(render(parts, selected, number, title, direction, note))
    internal = [name for name in parts if name.startswith(("R_TRIG-焊点", "摇杆1-", "摇杆2-", "H3-", "支座固定-"))]
    images.append(render(parts, ["独立摇杆支座", *internal], 18,
                         "支座与高焊点_透明检视", (-.9, -1.3, .8),
                         "支座设为透明，仅用于检查4毫米高电阻焊点和螺丝承力区",
                         opacity={"独立摇杆支座": .30}))
    exploded_shifts = {name: ((0, 0, -16) if name == "一体底座" else
                             (0, 0, 16) if name == "独立摇杆支座" else (0, 0, 0))
                       for name in simple}
    images.append(render(parts, simple, 19, "主板与两壳件_分解图", (1, 1.4, .8),
                         "检视分解图：两壳件沿主板法向各移开16毫米，实际装配位置未改变",
                         shifts=exploded_shifts))
    sheets = [sheet(images[:6], "总览_完整装配.png", "完整装配｜六个方向"),
              sheet([*images[6:9], images[18]], "总览_主板与结构关系.png", "主板与结构｜隐藏件与分解检视"),
              sheet(images[9:13], "总览_主体底座.png", "主体底座｜四个方向"),
              sheet(images[13:17], "总览_摇杆支座.png", "摇杆支座｜四个方向")]
    plan = layout_plan()
    cards = "\n".join(f'<a href="多角度检视/{html.escape(path.name)}"><img src="多角度检视/{html.escape(path.name)}" loading="lazy"><span>{html.escape(path.stem)}</span></a>' for path in images)
    (OUT/"多角度检视.html").write_text(f'''<!doctype html><meta charset="utf-8"><title>长方条正式预览 · 多角度检视</title>
<style>body{{font:16px "Microsoft YaHei",sans-serif;background:#edf2f6;color:#193748;margin:24px}}h1{{font-size:28px}}p{{line-height:1.7}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:18px}}a{{background:white;border-radius:10px;overflow:hidden;text-decoration:none;color:inherit;box-shadow:0 3px 16px #1232}}img{{width:100%;display:block}}span{{display:block;padding:12px}}</style>
<h1>长方条正式预览 · 多角度检视</h1><p>由本目录实际完整装配模型生成；点击图片查看原图。带“隐藏”说明的视图仅用于检视，其余完整装配均保留主板、器件、导线和五金。<br>主板焊点按最高4毫米加0.5毫米余量；原生摇杆小板短脚净空3毫米。静态模型检查不能替代实物试装。<br><a href="整体检视与重排建议.md">查看检查结论与整体重排建议</a></p><main>{cards}</main><h2>整体分区草案 · 未实施</h2><a href="多角度检视/{plan.name}"><img style="max-width:1300px" src="多角度检视/{plan.name}"></a>''', encoding="utf-8")
    (IMAGES/"视图目录.json").write_text(json.dumps({"单张截图": [path.name for path in images],
                                               "总览图": [path.name for path in sheets]}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
