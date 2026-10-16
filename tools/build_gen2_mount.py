"""第二代开放样机：一件固定底座，不生成握把、塑料扳机或摇杆限位。

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
BATTERY = tuple(v for c, length in zip(C["battery"]["center_xyz"], C["battery"]["size_xyz"])
                for v in (c-length/2, c+length/2))
SM_CFG, GY_CFG = C["modules"]["mcu"], C["modules"]["imu"]
SM = (*SM_CFG["x"], SM_CFG["component_face_y"]-SM_CFG["board_thickness"],
      SM_CFG["component_face_y"], *SM_CFG["z"])
GY = (*GY_CFG["x"], GY_CFG["component_face_y"]-GY_CFG["board_thickness"],
      GY_CFG["component_face_y"], *GY_CFG["z"])
JOYSTICK = next(p for p in C["parts"] if p["ref"] == "SW1")
JOY_BOARD = tuple(v for span in JOYSTICK["module_board_xyz"] for v in span)
JOY_AXIS = (JOY_BOARD[0], (JOY_BOARD[2]+JOY_BOARD[3])/2,
            (JOY_BOARD[4]+JOY_BOARD[5])/2)
SS_HOLES = [(-14.2, -4.521), (-14.2, -14.021)]


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1-x0, y1-y0, z1-z0, V(x0, y0, z0))


def cy(x, z, r, y0, y1):
    return cq.Solid.makeCylinder(r, y1-y0, V(x, y0, z), V(0, 1, 0))


def cx(y, z, r, x0, x1):
    return cq.Solid.makeCylinder(r, x1-x0, V(x0, y, z), V(1, 0, 0))


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
    for a, b in [((-56, 36), (-12, 36)), ((-47.8, 36), (-47.8, -4)),
                 ((-47.8, -4), (-51, -4)),
                 ((-51, -4), (-27, -27)), ((-12, 36), (-27, -27)),
                 ((-51, -4), (-49, -32)), ((-27, -27), (-26, -32)),
                 ((-47.8, 5), (-46.8, 5))]:
        parts.append(beam(a, b, 3.6))
    for h in P["mount_holes"]:
        x, z = h["xz"]
        parts.append(cy(x, z, 3.2, BASE[0], BACK))

    # Smooth shallow floor and low fences; two straps carry the pouch retention.
    floor = box(-50.5, -24.9, *BASE, -113.8, -30.5)
    floor = cq.Workplane().add(floor).edges("|Y").fillet(0.8).val()
    parts.append(floor)
    # 602060 pouch + protection/lead allowance: 20 x 80 x 8 mm.
    # The upper (+Z) end stays open so protection PCB and leads are not trapped.
    parts += [box(-49.3, -48.3, -17.1, -12.7, -113.6, -30.4),
              box(-27.1, -26.1, -17.1, -12.7, -113.6, -30.4),
              box(-49.3, -26.1, -17.1, -12.7, -113.6, -112.6)]

    # MCU and IMU now solder directly onto the carrier, so their former
    # external cradles are gone. Only the joystick's header-side board edge
    # needs a shallow shelf and a loose strap. The open side leaves allowance
    # for the unmeasured bend offset of the existing header; no tight slot.
    parts += [box(-48.0, -46.0, BASE[0], -5.0, 3.2, 7.0),
              box(-54.0, -46.0, -9.0, -5.0, 5.0, 7.0),
              box(-47.8, -45.8, -9.0, -5.0, 5.0, 35.0)]

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
    # C_RAIL's outer solder tail is close to H4. Relieve the post edge
    # locally instead of making the whole carrier sit higher.
    tail = next(p for p in C["parts"] if p["ref"] == "C_RAIL")["pads"][1]
    cuts.append(cy(*tail["xz"], 1.3, BACK-1.2, BACK+.1))
    for z in (-98, -57):
        for x in (-48.8, -26.6):
            cuts.append(box(x-.75, x+.75, -20, -10, z-2, z+2))
    for z in (9.0, 32.0):
        cuts.append(box(-48.1, -45.5, -8.0, -6.0, z-1.3, z+1.3))
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
        if p["ref"] in {"SW1", "J_MCU", "J_GY"}:
            continue
        envs = p.get("envelopes", [p["envelope"]] if "envelope" in p else [])
        backside = p.get("mount_side") == "bottom"
        for i, e in enumerate(envs):
            ys = e.get("y_above_board", 0)
            a, b = ys if isinstance(ys, list) else (0, ys)
            y0, y1 = (BACK-b, BACK-a) if backside else (TOP+a, TOP+b)
            if e.get("kind") == "cylinder_y":
                s = cy(*e["xz"], e["radius"], y0, y1)
            else:
                s = box(*e["x"], y0, y1, *e["z"])
            r[f"{p['ref']}-本体{i}"] = s
        for i, pad in enumerate(p.get("pads", [])):
            if pad.get("drill"):
                rad = max(pad.get("size", [2, 2]))/2
                y0, y1 = (TOP, TOP+1) if backside else (BACK-1, BACK)
                r[f"{p['ref']}-焊脚{i}"] = cy(*pad["xz"], rad, y0, y1)
    r.update({"开发板元件": box(SM[0]+1, SM[1]-1, SM[3],
                               SM[3]+SM_CFG["front_allowance"], SM[4]+1, SM[5]-1),
              "USB接口": box(SM[1]-.5, SM[1]+1.5, SM[3], SM[3]+3.5,
                              (SM[4]+SM[5])/2-4.5, (SM[4]+SM[5])/2+4.5),
              "陀螺仪元件": box(GY[0]+1, GY[1]-1, GY[3],
                                GY[3]+GY_CFG["front_allowance"], GY[4]+1, GY[5]-1)})
    for ref, label, top_y in [("J_MCU", "开发板排针", SM[3]),
                              ("J_GY", "陀螺仪排针", GY[3])]:
        p = next(v for v in C["parts"] if v["ref"] == ref)
        r[label] = fuse([cy(*pad["xz"], .32, BACK-1, top_y+.6)
                         for pad in p["pads"]])
    # The measured items are the 34 x 26 board and 2.54-pitch header. The
    # unmeasured header bend and shaft-centre offset are schematic here;
    # the support is intentionally open rather than an exact mating slot.
    x, y, z = JOY_AXIS
    r["SW1-模块黑板"] = box(*JOY_BOARD)
    r["SW1-金属本体"] = box(x-14, x, y-10, y+10, z-10, z+10)
    r["SW1-原生摇杆轴"] = cx(y, z, 2, x-25, x-13)
    r["SW1-原生摇杆帽"] = fuse([
        cx(y, z, 12, x-32, x-28),
        cq.Solid.makeCone(10, 4, 8, V(x-28, y, z), V(1, 0, 0))])
    r["SW1-五针示意"] = fuse([cy(*p["xz"], .32, -5, TOP+1)
                                  for p in JOYSTICK["pads"]])
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
    x, y, z = JOY_AXIS
    r["摇杆全角度留空"] = cx(y, z, 17, x-39, x-14.5)
    r["SS手指操作留空"] = box(-6.5, 14, -6, 8, -23, 2)
    r["USB插头留空"] = box(SM[1]+1.5, SM[1]+27,
                                SM[3]-1.5, SM[3]+5.0,
                                (SM[4]+SM[5])/2-6.2, (SM[4]+SM[5])/2+6.2)
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
    groups = {"载板": [v for k, v in refs.items() if not k.startswith("SW1-") and (k == "载板" or "-本体" in k or "-焊脚" in k)],
              "摇杆": [v for k, v in refs.items() if k.startswith("SW1-")],
              "开发板": [refs[k] for k in ["开发板", "开发板元件", "开发板排针", "USB接口"]],
              "陀螺仪板": [refs[k] for k in ["陀螺仪板", "陀螺仪元件", "陀螺仪排针"]],
              "电池": [refs["电池"]], "SS": [refs["SS金属扳机本体"]]}
    # Install the bare carrier on the four posts, then solder the modules.
    # The joystick header enters from the back; its open shelf does not
    # require the black board to slide through a precise mating slot.
    paths = [("载板从正面落到四柱", groups["载板"], (0, 0, 0), (0, 32, 0)),
             ("摇杆弯针由背面插入", groups["摇杆"], (0, 0, 0), (0, -32, 0)),
             ("开发板排针由正面插入", groups["开发板"], (0, 0, 0), (0, 24, 0)),
             ("电池垂直放入", groups["电池"], (0, 0, 0), (0, 32, 0)),
             ("GY排针由正面插入", groups["陀螺仪板"], (0, 0, 0), (0, 24, 0)),
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
    # Fit the four carrier nuts from the exposed component side. Switch
    # nuts slide into the same open side slots as the previous prototype.
    nut_paths = {}
    for h in P["mount_holes"]:
        k = h["id"]+"-螺母"
        delta = (0, 5, 0)
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
            "carrier_mount_holes": P["mount_holes"], "joystick_axis_xyz_mm": JOY_AXIS,
            "joystick_axis_direction_xyz": joystick_direction(),
            "battery_envelope_mm": bounds(refs["电池"]),
            "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
            "retention": {"载板": "4颗M2x20从底座向元件面穿入，正面M2螺母轻夹，不另加垫片",
                          "SS": "原SS-01GL两孔，2颗M2x20；单侧垫片填0.6mm名义间隙，侧插M2螺母",
                          "开发板": "两排各9针由正面直接焊在载板，板间留3mm，USB朝+X；电池B+/B-接两根短线",
                          "GY": "左8右6排针由正面直接焊在载板，板间留3mm；其他闲脚保持默认",
                          "摇杆": "现有HW504弯针由背面插焊，黑板垂直载板、原生帽朝-X；靠排针空白板边薄托+一条软绑带，横向开放",
                          "电池": "602060含保护板/出线预留20x80x8mm，出线端敞开；薄软垫+两条软绑带，不承担手掌握力"},
            "limits": ["HW504仅黑板34x26和2.54排针实测；弯针偏移、轴心及原生帽为保守示意，薄托开放并留横向调整余地",
                       "模块、SS和电池为保守包络，购入实物尺寸/树脂收缩需试装",
                       "直线插入使用包围盒连续扫掠；未模拟柔性线缆、绑带、手指及工具转动",
                       "绑带/绝缘软垫由实物固定；触摸、电池温升、无线性能需实测",
                       "右键帽原文件不变，但本底座不提供帽的防脱导向，默认直接按原生按钮"]}


def joystick_direction():
    return next(p for p in C["parts"] if p["ref"] == "SW1").get("axis_direction_xyz", [0, 1, 0])


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


def export_assembled_stl():
    """同一组毫米几何导出装配STL和带色分组OBJ，仅供装配查看。"""
    import vtk
    base = cq.importers.importStep(str(OUT / "step" / "engineering_mount.step")).val()
    b = base.BoundingBox()
    refs = references()
    refs.pop("载板")
    refs.update(hardware()[0])
    geometry = vtk.vtkAppendPolyData()
    meshes = []
    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(OUT / "stl" / "engineering_mount.stl"))
    reader.Update()
    geometry.AddInputData(reader.GetOutput())
    meshes.append(("一体底座", "底座", reader.GetOutput()))
    for name, shape in refs.items():
        if "留空" in name:
            continue
        verts, tris = shape.tessellate(.05)
        points, cells = vtk.vtkPoints(), vtk.vtkCellArray()
        for p in verts:
            points.InsertNextPoint(p.x-b.xmin, b.zmax-p.z, p.y-BASE[0])
        for tri in tris:
            cells.InsertNextCell(3, tri)
        data = vtk.vtkPolyData()
        data.SetPoints(points)
        data.SetPolys(cells)
        geometry.AddInputData(data)
        material = ("电池" if name == "电池" else "摇杆帽" if "摇杆帽" in name
                    else "电路板" if name in {"开发板", "陀螺仪板", "SW1-模块黑板"}
                    else "芯片" if "元件" in name or "金属本体" in name
                    else "金属")
        meshes.append((name, material, data))
    board = vtk.vtkOBJReader()
    board.SetFileName(str(ROOT / "pcb" / "3d" / "gun-mouse-gen2.obj"))
    board.Update()
    board_mesh = vtk.vtkPolyData()
    board_mesh.DeepCopy(board.GetOutput())
    z0, z1 = board_mesh.GetBounds()[4:6]
    middle_y = (BACK+TOP)/2
    vertices = vtk.vtkPoints()
    for i in range(board_mesh.GetNumberOfPoints()):
        u, v, w = board_mesh.GetPoint(i)
        vertices.InsertNextPoint(-u-3-b.xmin, b.zmax-(v+45),
                                 middle_y+w-(z0+z1)/2-BASE[0])
    board_mesh.SetPoints(vertices)
    geometry.AddInputData(board_mesh)
    meshes.append(("实际载板", "电路板", board_mesh))
    triangles = vtk.vtkTriangleFilter()
    triangles.SetInputConnection(geometry.GetOutputPort())
    triangles.Update()
    path = OUT / "stl" / "第二代完整装配.stl"
    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(path))
    writer.SetFileTypeToBinary()
    writer.SetInputConnection(triangles.GetOutputPort())
    if writer.Write() != 1:
        raise RuntimeError("装配STL导出失败")
    colors = {"底座": (.22, .48, .61), "电路板": (.10, .42, .20),
              "电池": (.72, .74, .77), "摇杆帽": (.10, .10, .11),
              "芯片": (.23, .25, .27), "金属": (.64, .66, .69)}
    obj_path = OUT / "第二代完整装配.obj"
    mtl_path = obj_path.with_suffix(".mtl")
    with mtl_path.open("w", encoding="utf-8", newline="\n") as output:
        for name, rgb in colors.items():
            output.write(f"newmtl {name}\nKa 0.15 0.15 0.15\nKd {' '.join(map(str, rgb))}\n"
                         "Ks 0.2 0.2 0.2\nNs 25\nd 1.0\nillum 2\n")
    with obj_path.open("w", encoding="utf-8", newline="\n", buffering=1024*1024) as output:
        output.write(f"# 毫米；与完整装配STL同坐标，仅供查看，不能整体打印\nmtllib {mtl_path.name}\n")
        offset = 1
        for name, material, mesh in meshes:
            output.write(f"\no {name}\ng {name}\nusemtl {material}\n")
            for i in range(mesh.GetNumberOfPoints()):
                vx, vy, vz = mesh.GetPoint(i)
                output.write(f"v {vx:.6f} {vy:.6f} {vz:.6f}\n")
            for i in range(mesh.GetNumberOfCells()):
                cell = mesh.GetCell(i)
                ids = [str(offset+cell.GetPointId(j)) for j in range(cell.GetNumberOfPoints())]
                output.write("f "+" ".join(ids)+"\n")
            offset += mesh.GetNumberOfPoints()
    print(str(path), flush=True)
    print(str(obj_path), flush=True)
    print("毫米；STL与OBJ同坐标，含底座、实际PCB、器件外形示意及紧固件；仅供看装配，不能整体打印。", flush=True)


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
    import sys
    if "--assembly-only" in sys.argv:
        export_assembled_stl()
    else:
        main()
