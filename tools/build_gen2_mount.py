"""第二代开放样机：一件固定底座，不生成握把、塑料扳机或摇杆限位。

运行：E:\\GunMouseCAD\\CadQuery\\python.exe tools/build_gen2_mount.py
毫米；装配 X 朝前、Y 朝拇指/摇杆面、Z 朝上。载板尺寸取 pcb/carrier-config.json。
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
MIDDLE_Y = (TOP+BACK)/2
FACE_Y_SUM = TOP+BACK
BASE = (-18.8, -16.9)
PRINT_FLOOR_Y = FACE_Y_SUM-BASE[0]
# 靠拇指进入方向的H2改为近板短柱，给手留出约11毫米。
SHORT_POST_Y = -7.8
BATTERY = tuple(v for c, length in zip(C["battery"]["center_xyz"], C["battery"]["size_xyz"])
                for v in (c-length/2, c+length/2))
SM_CFG, GY_CFG = C["modules"]["mcu"], C["modules"]["imu"]
SM = (*SM_CFG["x"], SM_CFG["component_face_y"]-SM_CFG["board_thickness"],
      SM_CFG["component_face_y"], *SM_CFG["z"])
GY = (*GY_CFG["x"], GY_CFG["component_face_y"]-GY_CFG["board_thickness"],
      GY_CFG["component_face_y"], *GY_CFG["z"])
JOYSTICK = next(p for p in C["parts"] if p["ref"] == "SW1")
# DZYJ标称图：黑板33x27，孔距26.4x19.5，孔径3.3；图注尺寸误差0.5-1mm。
# 这里只改装配与一体底座，实际载板五针孔位留待用户确认姿态后更新。
JOY_PIN_CENTER = (C["battery"]["center_xyz"][0]+4.0, 5.0)
JOY_BOARD = (JOY_PIN_CENTER[0]-13.5, JOY_PIN_CENTER[0]+13.5,
             -37.0, -4.0, 4.2, 5.8)
JOY_AXIS = (JOY_PIN_CENTER[0], -20.5, JOY_BOARD[5])
JOY_HOLES = [(JOY_PIN_CENTER[0]+dx, y)
             for y in (-7.3, -33.7) for dx in (-9.75, 9.75)]
JOY_MOUNT_HOLES = JOY_HOLES[:2]
SS_HOLES = [(-14.2, -4.521), (-14.2, -14.021)]


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1-x0, y1-y0, z1-z0, V(x0, y0, z0))


def cy(x, z, r, y0, y1):
    return cq.Solid.makeCylinder(r, y1-y0, V(x, y0, z), V(0, 1, 0))


def cx(y, z, r, x0, x1):
    return cq.Solid.makeCylinder(r, x1-x0, V(x0, y, z), V(1, 0, 0))


def cz(x, y, r, z0, z1):
    return cq.Solid.makeCylinder(r, z1-z0, V(x, y, z0), V(0, 0, 1))


def opposite_face(shape):
    """塑料支撑等按PCB中面换侧；实体器件在references中按刚体翻面。"""
    return shape.mirror("XZ", (0, MIDDLE_Y, 0))


def flip_about_x(shape, z):
    return shape.rotate((0, MIDDLE_Y, z), (1, MIDDLE_Y, z), 180)


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
    for a, b in [((-12, 36), (-12, 44)),
                 ((-51, -4), (-27, -27)), ((-12, 36), (-15, 0)),
                 ((-15, 0), (-27, -27)),
                 ((-51, -4), (-49, -32)), ((-27, -27), (-26, -32)),
                 ((-51, -4), (JOY_MOUNT_HOLES[0][0], 0)),
                 ((JOY_MOUNT_HOLES[0][0], 0), (-15, 0))]:
        parts.append(beam(a, b, 3.6))
    # 上横梁靠主板布置，避开摇杆帽上方的拇指接近空间。
    parts.append(beam((-56, 44), (-12, 44), 3.6, -6.8, -3.8))
    for a, b in [((-56, 36), (-58, 44)), ((-58, 44), (-56, 44))]:
        parts.append(beam(a, b, 3.6, -6.8, -3.8))
    parts.append(box(-13.8, -10.2, BASE[0], -3.8, 42.2, 45.8))
    for h in P["mount_holes"]:
        x, z = h["xz"]
        start_y = SHORT_POST_Y if h["id"] == "H2" else BASE[0]
        parts.append(cy(x, z, 3.2, start_y, BACK))

    # Smooth shallow floor and low fences; two straps carry the pouch retention.
    floor = box(-50.5, -24.9, *BASE, -113.8, -30.5)
    floor = cq.Workplane().add(floor).edges("|Y").fillet(0.8).val()
    parts.append(floor)
    # 602060 pouch + protection/lead allowance: 20 x 80 x 8 mm.
    # The upper (+Z) end stays open so protection PCB and leads are not trapped.
    parts += [box(-49.3, -48.3, -17.1, -12.7, -113.6, -30.4),
              box(-27.1, -26.1, -17.1, -12.7, -113.6, -30.4),
              box(-49.3, -26.1, -17.1, -12.7, -113.6, -112.6)]

    # Two short arms support the existing near-edge mounting holes. The
    # board stays horizontal and its native hat points up; no strap or stop.
    for x, y in JOY_MOUNT_HOLES:
        parts.append(box(x-3.4, x+3.4, BASE[0], y+3.4, -1.8, 1.8))
        parts.append(cz(x, y, 3.4, -1.8, JOY_BOARD[4]))

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
    # 给右键焊脚留出空间，避免新增摇杆短臂顶到焊点。
    for tail in next(p for p in C["parts"] if p["ref"] == "SW2")["pads"]:
        cuts.append(cy(*tail["xz"], 1.5, BACK-1.2, BACK+.1))
    for z in (-98, -57):
        for x in (-48.8, -26.6):
            cuts.append(box(x-.75, x+.75, -20, -10, z-2, z+2))
    for i, (x, y) in enumerate(JOY_MOUNT_HOLES):
        if i == 0:
            cuts.append(cz(x, y, 1.2, -2.0, JOY_BOARD[4]+.1))
        else:
            # 2.4 x 3.6mm short slot along X accommodates the drawing's
            # stated tolerance while the other hole locates the module.
            cuts.append(fuse([cz(x-.6, y, 1.2, -2.0, JOY_BOARD[4]+.1),
                              cz(x+.6, y, 1.2, -2.0, JOY_BOARD[4]+.1),
                              box(x-.6, x+.6, y-1.2, y+1.2, -2.0, JOY_BOARD[4]+.1)]))
    for x, z in SS_HOLES:
        cuts.append(cy(x, z, 1.15, -17.0, -3.6))
        # Side-open nut slot; the deep shaft bore hides the surplus screw tip.
        cuts.append(box(-18.3, -11.7, -8.0, -6.0, z-2.15, z+2.15))
    for cut in cuts:
        s = s.cut(cut)
    return opposite_face(s.clean())


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
            r[f"{p['ref']}-本体{i}"] = flip_about_x(s, p["position_xz"][1])
        for i, pad in enumerate(p.get("pads", [])):
            if pad.get("drill"):
                rad = max(pad.get("size", [2, 2]))/2
                y0, y1 = (TOP, TOP+1) if backside else (BACK-1, BACK)
                r[f"{p['ref']}-焊脚{i}"] = flip_about_x(
                    cy(*pad["xz"], rad, y0, y1), p["position_xz"][1])
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
    # Module board and four holes use the DZYJ nominal dimensional drawing.
    # The shaft centre, hat shape and header bend remain schematic.
    x, y, z = JOY_AXIS
    board = box(*JOY_BOARD)
    for hx, hy in JOY_HOLES:
        board = board.cut(cz(hx, hy, 1.65, JOY_BOARD[4]-.1, JOY_BOARD[5]+.1))
    r["SW1-模块黑板"] = board
    r["SW1-金属本体"] = box(x-10, x+10, y-10, y+10, z, z+14)
    r["SW1-原生摇杆轴"] = cz(x, y, 2, z+13, z+23)
    r["SW1-原生摇杆帽"] = fuse([
        cz(x, y, 12, z+24.4, z+28.4),
        cq.Solid.makeCone(4, 10, 8, V(x, y, z+16.4), V(0, 0, 1))])
    old_z = JOYSTICK["position_xz"][1]
    r["SW1-五针示意"] = fuse([cy(x+p["xz"][1]-old_z, JOY_PIN_CENTER[1],
                                    .32, -5, TOP+1)
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
    r["摇杆全角度留空"] = cz(x, y, 17, z+14.5, z+35)
    r["SS手指操作留空"] = box(-6.5, 14, -6, 8, -23, 2)
    r["USB插头留空"] = box(SM[1]+1.5, SM[1]+27,
                                SM[3]-1.5, SM[3]+5.0,
                                (SM[4]+SM[5])/2-6.2, (SM[4]+SM[5])/2+6.2)
    # 整个模块按实体旋转换面；实际载板孔号尚未同步，不能用于下单。
    for name, shape in list(r.items()):
        if name.startswith("SW1-") or name == "摇杆全角度留空":
            r[name] = shape.rotate((JOY_PIN_CENTER[0], MIDDLE_Y, 0),
                                   (JOY_PIN_CENTER[0], MIDDLE_Y, 1), 180)
        elif name.startswith("开发板") or name in {"USB接口", "USB插头留空"}:
            r[name] = flip_about_x(shape, (SM[4]+SM[5])/2)
        elif name.startswith("陀螺仪"):
            r[name] = flip_about_x(shape, (GY[4]+GY[5])/2)
        elif name == "电池" or name.startswith("SS"):
            r[name] = opposite_face(shape)
    return r


def preview_references():
    """摇杆在拇指面，主板元件在相反面，帽仍朝上。"""
    return references()


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


def hex_z(x, y, af, z0, z1):
    radius = af/math.sqrt(3)
    wire = cq.Wire.makePolygon([V(x+radius*math.cos(math.radians(k*60)),
                                  y+radius*math.sin(math.radians(k*60)), z0)
                               for k in range(6)], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), V(0, 0, z1-z0))


def hardware():
    r = {}
    seats = []
    for h in P["mount_holes"]:
        x, z = h["xz"]
        start_y = SHORT_POST_Y if h["id"] == "H2" else BASE[0]
        length = 10 if h["id"] == "H2" else 20
        tip_y = start_y+length
        head = cy(x, z, 2, start_y-2.1, start_y).cut(
            hex_y(x, z, 1.5, start_y-2.2, start_y-1.1))
        r[h["id"]+"-螺钉"] = head.fuse(cy(x, z, 1, start_y, tip_y))
        r[h["id"]+"-螺母"] = hex_y(x, z, 4, TOP, TOP+1.6).cut(cy(x, z, 1.05, TOP-.1, TOP+1.7))
        seats.append({"id": h["id"], "length_mm": length, "nut_engagement_mm": 1.6,
                      "projection_past_nut_mm": round(tip_y-(TOP+1.6), 3),
                      "thumb_side_projection_mm": round(BACK-start_y+2.1, 3),
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
    for i, (x, y) in enumerate(JOY_MOUNT_HOLES, 1):
        k = f"摇杆{i}"
        top = JOY_BOARD[5]
        head = cz(x, y, 2, -3.9, -1.8).cut(hex_z(x, y, 1.5, -4.0, -2.6))
        r[k+"-螺钉"] = head.fuse(cz(x, y, 1, -1.8, 8.2))
        r[k+"-螺母"] = hex_z(x, y, 4, top, top+1.6).cut(
            cz(x, y, 1.05, top-.1, top+1.7))
        seats.append({"id": k, "thread": "M2", "length_mm": 10,
                      "nut_engagement_mm": 1.6, "axis_direction_xyz": [0, 0, 1],
                      "projection_past_nut_mm": .8,
                      "hole_center_xy_mm": [x, y],
                      "driver": "下方1.5mm内六角；上方薄钳扶普通M2螺母，直接压模块原孔"})
    for seat in seats:
        if "hole_center_xy_mm" in seat:
            x, y = seat["hole_center_xy_mm"]
            seat["hole_center_xy_mm"] = [x, FACE_Y_SUM-y]
        for key in ("screw_tip_y_mm", "blind_bore_end_y_mm"):
            if key in seat:
                seat[key] = FACE_Y_SUM-seat[key]
    return {name: opposite_face(shape) for name, shape in r.items()}, seats


def verify(s, refs):
    overlaps = {k: round(s.intersect(v).Volume(), 6) for k, v in refs.items()}
    collisions = {k: v for k, v in overlaps.items() if v > 0.001}
    insertion = {}
    groups = {"载板": [v for k, v in refs.items() if not k.startswith("SW1-") and (k == "载板" or "-本体" in k or "-焊脚" in k)],
              "摇杆": [v for k, v in refs.items() if k.startswith("SW1-")],
              "开发板": [refs[k] for k in ["开发板", "开发板元件", "开发板排针", "USB接口"]],
              "陀螺仪板": [refs[k] for k in ["陀螺仪板", "陀螺仪元件", "陀螺仪排针"]],
              "电池": [refs["电池"]], "SS": [refs["SS金属扳机本体"]]}
    # 安装面交换后，所有原有装配行程同步换向。
    paths = [("载板从元件面落到四柱", groups["载板"], (0, 0, 0), (0, -32, 0)),
             ("摇杆弯针由拇指面插入", groups["摇杆"], (0, 0, 0), (0, 32, 0)),
             ("开发板排针由元件面插入", groups["开发板"], (0, 0, 0), (0, -24, 0)),
             ("电池放入托内", groups["电池"], (0, 0, 0), (0, -32, 0)),
             ("GY排针由元件面插入", groups["陀螺仪板"], (0, 0, 0), (0, -24, 0)),
             ("SS最后放入", groups["SS"], (0, 0, 0), (0, -24, 0))]
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
        delta = (0, -5, 0)
        nut_paths[k] = round(s.intersect(swept_box(hw[k], delta)).Volume(), 6)
    for i in (1, 2):
        k = f"SS{i}-螺母"
        nut_paths[k] = round(s.intersect(swept_box(hw[k], (-8, 0, 0))).Volume(), 6)
    for i in (1, 2):
        k = f"摇杆{i}-螺母"
        nut_paths[k] = round(s.intersect(swept_box(hw[k], (0, 0, 12))).Volume(), 6)
    tool_access = {}
    for h in P["mount_holes"]:
        start_y = SHORT_POST_Y if h["id"] == "H2" else BASE[0]
        driver = opposite_face(cy(*h["xz"], 1.5, -36, start_y-2.11))
        tool_access[h["id"]] = round(s.intersect(driver).Volume(), 6)
    for i, (x, z) in enumerate(SS_HOLES, 1):
        driver = opposite_face(cy(x, z, 1.5, 5.61, 24))
        hit = s.intersect(driver).Volume()
        for n, shape in refs.items():
            if "留空" not in n and "摆杆示意" not in n:
                hit = max(hit, driver.intersect(shape).Volume())
        tool_access[f"SS{i}"] = round(hit, 6)
    for i, (x, y) in enumerate(JOY_MOUNT_HOLES, 1):
        driver = opposite_face(cz(x, y, 1.5, -24, -3.91))
        hit = s.intersect(driver).Volume()
        for n, shape in refs.items():
            if "留空" not in n and "摆杆示意" not in n:
                hit = max(hit, driver.intersect(shape).Volume())
        tool_access[f"摇杆{i}"] = round(hit, 6)
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
            "carrier_mount_holes": P["mount_holes"],
            "joystick_axis_xyz_mm": [JOY_AXIS[0], FACE_Y_SUM-JOY_AXIS[1], JOY_AXIS[2]],
            "joystick_axis_direction_xyz": joystick_direction(),
            "battery_envelope_mm": bounds(refs["电池"]),
            "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
            "installation_faces": {"拇指面+Y": "摇杆、电池托和一体底座", "元件面-Y": "开发板、陀螺仪及其他主板元件"},
            "retention": {"载板": "H2靠拇指侧改近板短柱+M2x10，其余3颗M2x20；均从底座向元件面穿入，元件面M2螺母轻夹，不另加垫片",
                          "SS": "原SS-01GL两孔，2颗M2x20；单侧垫片填0.6mm名义间隙，侧插M2螺母",
                          "开发板": "两排各9针由摇杆相反面直接焊在载板，板间留3mm，USB朝+X；电池B+/B-接两根短线，实际孔号待同步",
                          "GY": "左8右6排针由摇杆相反面直接焊在载板，板间留3mm；实际孔号待同步",
                          "摇杆": "DZYJ黑板33x27标称，原生帽朝+Z，整体相对握持中心向+X偏4mm；靠主板两孔19.5mm间距，用2颗M2x10从短柱底部向上穿，普通M2螺母在模块上方直接压原孔；塑料一孔2.4mm、一孔沿X为2.4x3.6mm，模块原孔3.3mm，保留弯针；实际载板新五孔后置",
                          "电池": "602060含保护板/出线预留20x80x8mm，出线端敞开；薄软垫+两条软绑带，不承担手掌握力"},
            "limits": ["本轮仅改安装面与装配模型；实际载板翻面孔号、摇杆五针孔和布线尚未同步，旧打板包未更新",
                       "HW504板33x27、孔距26.4x19.5及孔径3.3来自DZYJ标称图；图注误差0.5-1mm，弯针偏移、轴心及帽仍为示意",
                       "模块、SS和电池为保守包络，购入实物尺寸/树脂收缩需试装",
                       "直线插入使用包围盒连续扫掠；未模拟柔性线缆、绑带、手指及工具转动",
                       "绑带/绝缘软垫由实物固定；触摸、电池温升、无线性能需实测",
                       "右键帽原文件不变，但本底座不提供帽的防脱导向，默认直接按原生按钮"]}


def joystick_direction():
    return [0, 0, 1]


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
    camera.Zoom(1.0)
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
    refs = preview_references()
    refs.pop("载板")
    refs.update(hardware()[0])
    geometry = vtk.vtkAppendPolyData()
    meshes = []
    # 完整装配固定使用原坐标，不跟随单件底座的打印摆放方向翻转。
    for name, shape in [("一体底座", base), *refs.items()]:
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
        material = ("底座" if name == "一体底座" else "电池" if name == "电池" else "摇杆帽" if "摇杆帽" in name
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
    print("毫米；STL与OBJ同坐标。摇杆与电池托在拇指面，主板元件在反面；摇杆帽仍朝+Z。实际载板孔号与布线待同步，仅供看装配，不能整体打印。", flush=True)
    render(base, preview_references())


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
    printed = s.rotate((0, 0, 0), (1, 0, 0), -90).translate(V(-b.xmin, -b.zmin, PRINT_FLOOR_Y))
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
