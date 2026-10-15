"""第二代开放样机：一件固定底座，不生成握把、扳机、帽子或摇杆限位。

运行：E:\\GunMouseCAD\\CadQuery\\python.exe tools/build_gen2_mount.py
毫米；装配 X 朝前、Y 朝元件面、Z 朝上。载板尺寸取 pcb/carrier-config.json。
STL 已转为底面朝下的打印方向；STEP 保留装配坐标。
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "shell"
V = cq.Vector
CONFIG = ROOT / "pcb" / "carrier-config.json"
C = json.loads(CONFIG.read_text(encoding="utf-8"))
P = C["pcb"]
TOP = P["top_face_y"]
BACK = TOP - P["thickness"]
BASE = (-18.8, -16.9)
BATTERY = (-53.2, -22.2, -16.7, -8.7, -84.25, -31.75)
SM = (-7.5, 16.0, -14.6, -13.0, 14.0, 32.0)
GY = (-22.0, -1.4, 7.8, 9.0, 20.1, 37.9)
SS_HOLES = [(-14.2, -4.521), (-14.2, -14.021)]


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1-x0, y1-y0, z1-z0, V(x0, y0, z0))


def cy(x, z, r, y0, y1):
    return cq.Solid.makeCylinder(r, y1-y0, V(x, y0, z), V(0, 1, 0))


def fuse(items):
    return items[0].fuse(*items[1:]).clean()


def prism(points, y0, y1):
    w = cq.Wire.makePolygon([V(x, y0, z) for x, z in points], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(w), V(0, y1-y0, 0))


def beam(a, b, width, y0=BASE[0], y1=BASE[1]):
    x, z = a
    dx, dz = b[0]-x, b[1]-z
    length = math.hypot(dx, dz)
    px, pz = -dz/length*width/2, dx/length*width/2
    return fuse([prism([(x+px, z+pz), (b[0]+px, b[1]+pz),
                         (b[0]-px, b[1]-pz), (x-px, z-pz)], y0, y1),
                 cy(*a, width/2, y0, y1), cy(*b, width/2, y0, y1)])


def build_mount():
    parts = []
    # Sparse carrier skeleton; the long lower portion is only a battery tray.
    for a, b in [((-56, 36), (-12, 36)), ((-56, 36), (-51, -4)),
                 ((-51, -4), (-27, -27)), ((-12, 36), (-27, -27)),
                 ((-51, -4), (-53, -32)), ((-27, -27), (-24, -32)),
                 ((-56, 36), (-56, 42)), ((-56, 42), (17, 42)),
                 ((17, 42), (17, 12)), ((17, 12), (-10, 12)),
                 ((-10, 12), (-12, 36))]:
        parts.append(beam(a, b, 3.6))
    for h in P["mount_holes"]:
        x, z = h["xz"]
        parts.append(cy(x, z, 3.2, BASE[0], BACK))

    # Smooth shallow floor and low fences; two straps carry the pouch retention.
    floor = box(-56, -19.4, *BASE, -86, -30)
    floor = cq.Workplane().add(floor).edges("|Y").fillet(0.8).val()
    parts.append(floor)
    parts += [box(-54.7, -53.7, -17.1, -12.7, -85.8, -30.2),
              box(-21.7, -20.7, -17.1, -12.7, -85.8, -30.2),
              box(-54.7, -20.7, -17.1, -12.7, -85.8, -84.8),
              box(-54.7, -20.7, -17.1, -12.7, -31.4, -30.4)]

    # SuperMini: ledges on free short edges, USB pull/push stops, one narrow strap.
    # Preserve the EVT-1 position, antenna -X, USB +X; no pin headers.
    for z0, z1 in [(12.5, 13.8), (32.2, 33.5)]:
        parts.append(box(-8.8, 18.0, -17.2, -12.6, z0, z1))
    for z0, z1 in [(13.8, 14.6), (31.4, 32.2)]:
        parts.append(box(-6.5, 15.0, -17.2, -14.6, z0, z1))
    for z0, z1 in [(12.5, 17.6), (28.4, 33.5)]:
        parts.append(box(16.2, 18.0, -17.2, -12.6, z0, z1))
    # Ceramic antenna stays exposed. Rear corner stops touch only PCB corners.
    for z0, z1 in [(12.5, 15.0), (31.0, 33.5)]:
        parts.append(box(-8.8, -7.7, -17.2, -12.6, z0, z1))
    parts += [box(10.7, 13.3, -18.0, -14.6, 11.0, 13.8),
              box(10.7, 13.3, -18.0, -14.6, 32.2, 35.0)]

    # GY edge cradle is integrated. It hangs from above the carrier's Z=40 edge;
    # no post crosses the carrier, the joystick or SuperMini.
    for x0, x1 in [(-20, -16), (-8, -4)]:
        parts.append(box(x0, x1, -17.2, 7.8, 40.5, 43.5))
        parts.append(box(x0, x1, 5.6, 7.8, 37.3, 41.0))
    parts += [box(-22.9, -0.5, 5.6, 7.8, 37.3, 39.5),
              box(-22.9, -21.6, 5.6, 7.8, 19.3, 39.5),
              box(-2.2, -0.5, 5.6, 7.8, 19.3, 39.5),
              box(-22.9, -0.5, 5.6, 7.8, 19.3, 20.7),
              box(-22.9, -0.5, 7.6, 9.3, 38.2, 39.5),
              box(-0.5, 0.6, 5.6, 9.3, 19.3, 39.5)]

    # SS-01GL screws locate the switch. A single-side integral plate replaces
    # the separate sliding holder; two M2x20 screws can be reused from EVT-1.
    for x, z in SS_HOLES:
        parts.append(cy(x, z, 3.4, -17.2, -3.8))
    parts += [box(-17.6, -10.8, -17.2, -6.0, -17.4, -1.1),
              beam((-14.2, -5), (-12, 12), 4.5),
              beam((-14.2, -14), (-27, -27), 4.5)]
    s = fuse(parts)
    cuts = []
    for h in P["mount_holes"]:
        x, z = h["xz"]
        cuts.append(cy(x, z, 1.2, -20, BACK+0.2))
    for z in (-75, -45):
        for x in (-54.65, -20.75):
            cuts.append(box(x-.75, x+.75, -20, -10, z-2, z+2))
    # SuperMini strap slots: no strap touches the antenna or the USB mouth.
    for z0, z1 in [(11.8, 13.2), (32.8, 34.2)]:
        cuts.append(box(10.9, 13.1, -19, -14.4, z0, z1))
    # GY strap exits in open side notches; only board free-edge bands are loaded.
    for x0, x1 in [(-23.1, -21.6), (-2.2, .8)]:
        cuts.append(box(x0, x1, 5.4, 7.0, 27.2, 29.8))
    for x, z in SS_HOLES:
        cuts.append(cy(x, z, 1.15, -17.0, -3.6))
        # Side-open nut slot; the deep shaft bore hides the surplus screw tip.
        cuts.append(box(-18.3, -11.7, -8.0, -6.0, z-2.15, z+2.15))
    for cut in cuts:
        s = s.cut(cut)
    return s.clean()


def references():
    r = {"电池": box(*BATTERY), "开发板": box(*SM), "陀螺仪板": box(*GY)}
    r["载板"] = prism(P["outline_xz"], BACK, TOP)
    for h in P["mount_holes"]:
        r["载板"] = r["载板"].cut(cy(*h["xz"], h["d"]/2, BACK-.1, TOP+.1))
    for p in C["parts"]:
        if not p.get("populate", True):
            continue
        envs = p.get("envelopes", [p["envelope"]] if "envelope" in p else [])
        for i, e in enumerate(envs):
            ys = e.get("y_above_board", 0)
            a, b = ys if isinstance(ys, list) else (0, ys)
            if e.get("kind") == "cylinder_y":
                s = cy(*e["xz"], e["radius"], TOP+a, TOP+b)
            else:
                s = box(*e["x"], TOP+a, TOP+b, *e["z"])
            r[f"{p['ref']}-本体{i}"] = s
        for i, pad in enumerate(p.get("pads", [])):
            if pad.get("drill"):
                rad = max(pad.get("size", [2, 2]))/2
                r[f"{p['ref']}-焊脚{i}"] = cy(*pad["xz"], rad, BACK-1, BACK)
    r.update({"开发板元件": box(-6.5, 15, -13, -9.5, 15, 31),
              "开发板背线": box(-6.5, 15, -16.6, -14.6, 15.6, 30.4),
              "USB接口": box(16, 18.5, -13, -9.5, 18.5, 27.5),
              "陀螺仪元件": box(-21, -2.4, 9, 11.8, 21.1, 36.9),
              "陀螺仪焊线": box(-12, -3, 11.8, 14, 20.1, 23.1)})
    ss = fuse([box(-17.1, -7.6, -3.2, 3.2, -19.221, .579),
               box(-7.6, -6.9, -3.2, 3.2, -7.421, .579)])
    for x, z in SS_HOLES:
        ss = ss.cut(cy(x, z, 1.175, -3.3, 3.3))
    for off in (1.6, 10.4, 17.7):
        z = .579-off
        ss = ss.fuse(box(-20.6, -17.09, -1.6, 1.6, z-.25, z+.25))
    r["SS金属扳机本体"] = ss.clean()
    # Lever is shown as a conservative straight strip; it is not a measured
    # actuated supplier STEP. The entire finger/front corridor stays empty.
    r["SS金属摆杆示意"] = box(-3.6, -3.3, -2.5, 2.5, -20, -1)
    r["摇杆全角度留空"] = cy(-33, 23, 9.0, TOP+12.45, TOP+21)
    r["SS手指操作留空"] = box(-6.5, 14, -6, 8, -23, 2)
    r["USB插头留空"] = box(18.5, 44, -14.5, -8, 16.825, 29.175)
    return r


def bounds(s):
    b = s.BoundingBox()
    return [round(v, 4) for v in (b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax)]


def swept_box(s, delta):
    """整个直线行程的包围盒，保守包含连续扫掠，不靠少量姿态采样。"""
    b = s.BoundingBox()
    dx, dy, dz = delta
    return box(b.xmin+min(0, dx), b.xmax+max(0, dx),
               b.ymin+min(0, dy), b.ymax+max(0, dy),
               b.zmin+min(0, dz), b.zmax+max(0, dz))


def hex_y(x, z, af, y0, y1):
    r = af/math.sqrt(3)
    return prism([(x+r*math.cos(math.radians(k*60)),
                   z+r*math.sin(math.radians(k*60))) for k in range(6)], y0, y1)


def hardware():
    r = {}
    seats = []
    for h in P["mount_holes"]:
        x, z = h["xz"]
        head = cy(x, z, 2, -20.9, -18.8).cut(hex_y(x, z, 1.5, -21, -19.9))
        r[h["id"]+"-螺钉"] = head.fuse(cy(x, z, 1, -18.8, 1.2))
        r[h["id"]+"-螺母"] = hex_y(x, z, 4, TOP, TOP+1.6).cut(cy(x, z, 1.05, TOP-.1, TOP+1.7))
        seats.append({"id": h["id"], "length_mm": 20, "nut_engagement_mm": 1.6,
                      "projection_past_nut_mm": round(1.2-(TOP+1.6), 3),
                      "driver": "底部1.5mm内六角；正面薄钳扶螺母"})
    for i, (x, z) in enumerate(SS_HOLES, 1):
        k = f"SS{i}"
        r[k+"-螺钉"] = cy(x, z, 2, 3.5, 5.6).fuse(cy(x, z, 1, -16.5, 3.5))
        r[k+"-头侧垫片"] = cy(x, z, 2.5, 3.2, 3.5).cut(cy(x, z, 1.1, 3.1, 3.6))
        r[k+"-支承垫片"] = cy(x, z, 2.5, -3.8, -3.2).cut(cy(x, z, 1.1, -3.9, -3.1))
        r[k+"-螺母"] = hex_y(x, z, 4, -7.6, -6).cut(cy(x, z, 1.05, -7.7, -5.9))
        seats.append({"id": k, "length_mm": 20, "nut_engagement_mm": 1.6,
                      "screw_tip_y_mm": -16.5, "blind_bore_end_y_mm": -17,
                      "tip_end_clearance_mm": .5, "projection_past_nut_mm": 8.9,
                      "projection_protected_inside_mount": True})
    return r, seats


def verify(s, refs):
    overlaps = {k: round(s.intersect(v).Volume(), 6) for k, v in refs.items()}
    collisions = {k: v for k, v in overlaps.items() if v > 0.001}
    insertion = {}
    groups = {"载板": [v for k, v in refs.items() if k == "载板" or "-本体" in k or "-焊脚" in k],
              "开发板": [refs[k] for k in ["开发板", "开发板元件", "开发板背线", "USB接口"]],
              "陀螺仪板": [refs[k] for k in ["陀螺仪板", "陀螺仪元件", "陀螺仪焊线"]],
              "电池": [refs["电池"]], "SS": [refs["SS金属扳机本体"]]}
    # One-piece GY cradle overhangs the carrier. Use deliberate two-stage
    # paths, with the SS/GY installed after the carrier. No flexing is assumed.
    paths = [("载板高2mm从下边滑入", groups["载板"], (0, 2, 0), (0, 0, -110)),
             ("载板落下2mm", groups["载板"], (0, 0, 0), (0, 2, 0)),
             ("开发板高5mm从USB端滑入", groups["开发板"], (0, 5, 0), (35, 0, 0)),
             ("开发板落下5mm", groups["开发板"], (0, 0, 0), (0, 5, 0)),
             ("电池垂直放入", groups["电池"], (0, 0, 0), (0, 32, 0)),
             ("GY最后垂直放入", groups["陀螺仪板"], (0, 0, 0), (0, 24, 0)),
             ("SS最后垂直放入", groups["SS"], (0, 0, 0), (0, 24, 0))]
    for label, shapes, offset, delta in paths:
        hit = max(s.intersect(swept_box(v.translate(V(*offset)), delta)).Volume() for v in shapes)
        insertion[label] = round(hit, 6)
    hw, seats = hardware()
    hardware_hits = {}
    for k, v in hw.items():
        hit = s.intersect(v).Volume()
        for n, shape in refs.items():
            if "留空" in n or "摆杆示意" in n:
                continue
            hit = max(hit, v.intersect(shape).Volume())
        if hit > .001:
            hardware_hits[k] = round(hit, 6)
    # Nut paths are from side at H1 (the GY cradle is overhead); otherwise
    # before fitting the GY/module. Switch nuts slide in their open side slot.
    nut_paths = {}
    for h in P["mount_holes"]:
        k = h["id"]+"-螺母"
        delta = (28, 0, 0) if h["id"] == "H1" else (0, 5, 0)
        nut_paths[k] = round(s.intersect(swept_box(hw[k], delta)).Volume(), 6)
    for i in (1, 2):
        k = f"SS{i}-螺母"
        nut_paths[k] = round(s.intersect(swept_box(hw[k], (-8, 0, 0))).Volume(), 6)
    tool_access = {}
    for h in P["mount_holes"]:
        driver = cy(*h["xz"], 1.5, -36, -20.91)
        tool_access[h["id"]] = round(s.intersect(driver).Volume(), 6)
    for i, (x, z) in enumerate(SS_HOLES, 1):
        driver = cy(x, z, 1.5, 5.61, 24)
        hit = s.intersect(driver).Volume()
        for n, shape in refs.items():
            if "留空" not in n and "摆杆示意" not in n:
                hit = max(hit, driver.intersect(shape).Volume())
        tool_access[f"SS{i}"] = round(hit, 6)
    return {"scope": "第二代名义几何与保守包络；不是实物试装", "valid": s.isValid(),
            "solids": len(s.Solids()), "bounds_assembly_mm": bounds(s),
            "volume_mm3": round(s.Volume(), 3),
            "mass_g": {"树脂1.2": round(s.Volume()*.0012, 2), "尼龙1.01": round(s.Volume()*.00101, 2)},
            "new_printed_parts": 1, "overlaps_mm3": collisions,
            "conservative_continuous_insertion_overlaps_mm3": insertion,
            "fastener_overlaps_mm3": hardware_hits, "nut_insertion_overlaps_mm3": nut_paths,
            "axial_driver_access_overlaps_mm3": tool_access,
            "fasteners": seats,
            "all_pass": s.isValid() and len(s.Solids()) == 1 and not collisions and not hardware_hits and max(insertion.values()) < .001 and max(nut_paths.values()) < .001 and max(tool_access.values()) < .001,
            "carrier_mount_holes": P["mount_holes"], "joystick_axis_xz_mm": [-33, 23],
            "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
            "retention": {"载板": "4颗M2x20从底座向元件面穿入，正面M2螺母轻夹，不另加垫片",
                          "SS": "原SS-01GL两孔，2颗M2x20；单侧垫片填0.6mm名义间隙，侧插M2螺母",
                          "开发板": "端部止挡+边托+软绑带，USB朝+X，背线<=2mm",
                          "GY": "集成边托+绝缘垫+软绑带，不压芯片、不允许模块晃动",
                          "电池": "薄软垫+两条软绑带，不承担手掌握力"},
            "limits": ["模块、SS和电池为保守包络，购入实物尺寸/树脂收缩需试装",
                       "直线插入使用包围盒连续扫掠；未模拟柔性线缆、绑带、手指及工具转动",
                       "绑带/绝缘软垫由实物固定；触摸、电池温升、无线性能需实测",
                       "右键帽原文件不变，但本底座不提供帽的防脱导向，默认直接按原生按钮"]}


def render(s, refs):
    import vtk
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(.96, .97, .98)
    for name, shape in [("底座", s), *refs.items()]:
        if "留空" in name or "焊脚" in name:
            continue
        verts, tris = shape.tessellate(.1)
        points, cells = vtk.vtkPoints(), vtk.vtkCellArray()
        for p in verts:
            points.InsertNextPoint(p.x, p.y, p.z)
        for tri in tris:
            cells.InsertNextCell(3, tri)
        data = vtk.vtkPolyData()
        data.SetPoints(points)
        data.SetPolys(cells)
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(data)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        color = (.22, .48, .61) if name == "底座" else (.18, .55, .31) if name in ["载板", "开发板", "陀螺仪板"] else (.72, .74, .77) if name == "电池" else (.72, .73, .76) if "摆杆" in name else (.3, .32, .35)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetAmbient(.35)
        actor.GetProperty().SetDiffuse(.65)
        actor.GetProperty().SetOpacity(.9 if name == "底座" else 1)
        renderer.AddActor(actor)
    camera = renderer.GetActiveCamera()
    camera.SetPosition(190, 230, 145)
    camera.SetFocalPoint(-21, -3, -20)
    camera.SetViewUp(0, 0, 1)
    camera.ParallelProjectionOn()
    renderer.ResetCamera()
    camera.Zoom(1.12)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(1400, 1400)
    window.AddRenderer(renderer)
    window.Render()
    image = vtk.vtkWindowToImageFilter()
    image.SetInput(window)
    image.ReadFrontBufferOff()
    image.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(OUT / "renders" / "gen2-assembly.png"))
    writer.SetInputConnection(image.GetOutputPort())
    writer.Write()
    window.Finalize()


def verify_mesh(path, cad_volume):
    import vtk
    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(path))
    reader.MergingOn()
    reader.Update()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(reader.GetOutputPort())
    clean.Update()
    edges = vtk.vtkFeatureEdges()
    edges.SetInputConnection(clean.GetOutputPort())
    edges.BoundaryEdgesOn()
    edges.NonManifoldEdgesOn()
    edges.FeatureEdgesOff()
    edges.ManifoldEdgesOff()
    edges.Update()
    connected = vtk.vtkPolyDataConnectivityFilter()
    connected.SetInputConnection(clean.GetOutputPort())
    connected.SetExtractionModeToAllRegions()
    connected.Update()
    mass = vtk.vtkMassProperties()
    mass.SetInputConnection(clean.GetOutputPort())
    mass.Update()
    ratio = abs(mass.GetVolume()-cad_volume)/cad_volume
    result = {"open_or_nonmanifold_edges": edges.GetOutput().GetNumberOfCells(),
              "connected_bodies": connected.GetNumberOfExtractedRegions(),
              "mesh_vs_cad_volume_relative_difference": round(ratio, 6)}
    result["pass"] = result["open_or_nonmanifold_edges"] == 0 and result["connected_bodies"] == 1 and ratio < .005
    return result


def main():
    s = build_mount()
    refs = references()
    report = verify(s, refs)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not report["all_pass"]:
        raise SystemExit("名义几何检查未通过，不导出打样文件")
    for folder in ("stl", "step", "renders"):
        (OUT / folder).mkdir(parents=True, exist_ok=True)
    cq.exporters.export(s, str(OUT / "step" / "engineering_mount.step"))
    b = s.BoundingBox()
    printed = s.rotate((0, 0, 0), (1, 0, 0), 90).translate(V(-b.xmin, b.zmax, -BASE[0]))
    report["bounds_print_mm"] = bounds(printed)
    assert abs(printed.BoundingBox().zmin) < 1e-5, "打印底面必须落在Z=0"
    path = OUT / "stl" / "engineering_mount.stl"
    cq.exporters.export(printed, str(path), tolerance=.03, angularTolerance=.1)
    report["stl_check"] = verify_mesh(path, s.Volume())
    assert report["stl_check"]["pass"], "打印网格检查失败"
    report["stl_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT / "assembly-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    render(s, refs)


if __name__ == "__main__":
    main()
