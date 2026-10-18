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
BATTERY_FLOOR_Y = -19.3
PRINT_FLOOR_Y = -BATTERY_FLOOR_Y
BATTERY_DROP_Z = 12.0
# 支架在元件面，H2保留短柱；摇杆通过板边缺口跨到拇指面。
SHORT_POST_Y = -7.8
BATTERY = tuple(v for c, length in zip(C["battery"]["center_xyz"], C["battery"]["size_xyz"])
                for v in (c-length/2, c+length/2))
BATTERY = (*BATTERY[:4], BATTERY[4]-BATTERY_DROP_Z, BATTERY[5]-BATTERY_DROP_Z)
SM_CFG, GY_CFG = C["modules"]["mcu"], C["modules"]["imu"]
SM = (*SM_CFG["x"], SM_CFG["component_face_y"]-SM_CFG["board_thickness"],
      SM_CFG["component_face_y"], *SM_CFG["z"])
GY = (*GY_CFG["x"], GY_CFG["component_face_y"]-GY_CFG["board_thickness"],
      GY_CFG["component_face_y"], *GY_CFG["z"])
JOYSTICK = next(p for p in C["parts"] if p["ref"] == "SW1")
JOY_PIN_TO_MOUNT = C.get("joystick_mounting", {}).get("pin_to_near_mount_row_mm", 2.4)
# 旧名义模型按1毫米放置；用补充尺寸修正模块位置，主板五孔与弯针水平段不动。
JOY_OUTWARD_SHIFT = JOY_PIN_TO_MOUNT-1.0
JOY_NEAR_Y = FACE_Y_SUM+7.3+JOY_OUTWARD_SHIFT
JOY_ARM_Y = (JOY_NEAR_Y-1.8, JOY_NEAR_Y+1.8)
# DZYJ标称图：黑板33x27，孔距26.4x19.5，孔径3.3；图注尺寸误差0.5-1mm。
# 器件外形使用原始模块坐标，载板孔与网络使用配置中的最终装配坐标。
JOY_PIN_CENTER = (C["battery"]["center_xyz"][0]+4.0, 5.0)
JOY_BOARD = (JOY_PIN_CENTER[0]-13.5, JOY_PIN_CENTER[0]+13.5,
             -37.0-JOY_OUTWARD_SHIFT, -4.0-JOY_OUTWARD_SHIFT, 2.2, 3.8)
JOY_AXIS = (JOY_PIN_CENTER[0], -20.5-JOY_OUTWARD_SHIFT, JOY_BOARD[5])
JOY_HOLES = [(JOY_PIN_CENTER[0]+dx, y)
             for y in (-7.3-JOY_OUTWARD_SHIFT, -33.7-JOY_OUTWARD_SHIFT) for dx in (-9.75, 9.75)]
JOY_MOUNT_HOLES = JOY_HOLES[:2]
JOY_SHARED_HOLES = [(h["id"], *h["xz"])
                    for h in next(p for p in C["parts"] if p["ref"] == "SW1_ALT")["npth"]
                    if h["id"].startswith("JOY_SHARED_FAR_")]
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


def root_gusset(x0, x1, top_z):
    """托架外缘的圆角三角筋，将握持载荷接入原支撑梁。"""
    points = [(BATTERY_FLOOR_Y, -30.5-BATTERY_DROP_Z),
              (-8.2, -30.5-BATTERY_DROP_Z), (BASE[0], top_z)]
    wire = cq.Wire.makePolygon([V(x0, y, z) for y, z in points], close=True)
    shape = cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), V(x1-x0, 0, 0))
    return cq.Workplane().add(shape).edges("|X").fillet(.8).val()


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
    for a, b in [((-12, 36), (-12, 45)),
                 ((-51, -4), (-27, -27)), ((-12, 36), (-15, 0)),
                 ((-15, 0), (-27, -27)),
                 ((-51, -4), (-49, -32)), ((-27, -27), (-26, -32)),
                 ((-51, -4), (JOY_MOUNT_HOLES[0][0], 0)),
                 ((JOY_MOUNT_HOLES[0][0], 0), (-15, 0))]:
        parts.append(beam(a, b, 3.6))
    # 上横梁靠主板布置，避开摇杆帽上方的拇指接近空间。
    parts.append(beam((-56, 45), (-12, 45), 3.6, -6.8, -3.8))
    for a, b in [((-56, 36), (-58, 45)), ((-58, 45), (-56, 45))]:
        parts.append(beam(a, b, 3.6, -6.8, -3.8))
    parts.append(box(-13.8, -10.2, BASE[0], -3.8, 43.2, 46.8))
    for h in P["mount_holes"]:
        x, z = h["xz"]
        start_y = SHORT_POST_Y if h["id"] == "H2" else BASE[0]
        parts.append(cy(x, z, 3.2, start_y, BACK))

    # 开窗框架保持平底，向外加厚0.5毫米，不侵占电池内腔。
    floor = box(-50.5, -24.9, BATTERY_FLOOR_Y, BASE[1], -113.8-BATTERY_DROP_Z, -30.5-BATTERY_DROP_Z)
    floor = cq.Workplane().add(floor).edges("|Y").fillet(0.8).val()
    parts.append(floor)
    # 两侧深梁高出电池名义表面0.5毫米；放入面与上端出线口敞开。
    for x0, x1 in [(-50.5, -48.2), (-27.2, -24.9)]:
        rail = box(x0, x1, BATTERY_FLOOR_Y, -8.2, -113.8-BATTERY_DROP_Z, -30.4-BATTERY_DROP_Z)
        parts.append(cq.Workplane().add(rail).edges("|Z").fillet(.5).val())
    parts += [box(-49.3, -26.1, -17.1, -12.7, -113.6-BATTERY_DROP_Z, -112.6-BATTERY_DROP_Z),
              root_gusset(-51.4, -48.2, -10),
              root_gusset(-27.2, -24.0, -24)]
    # 沿外缘延长两根连接筋，避开板底的电源开关和电池出线端。
    parts += [beam((-50,-32),(-50,-44),3.6), beam((-26,-32),(-26,-44),3.6)]

    # 下部薄护板挡住八颗手焊小件；上方两块模块保持敞开。
    parts.append(box(-54.5, -23.6, BASE[0], BASE[1], -34, -7.2))
    # 从主板前方的原有缺口绕过，短臂仍托住摇杆靠板的两个孔。
    parts += [box(-19.4, -15.8, BASE[0], JOY_ARM_Y[1], 2, 4.2),
              box(-19.4, -15.8, *JOY_ARM_Y, -5.8, 4.2),
              box(-46.85, -15.8, *JOY_ARM_Y, -8.8, -2.2)]
    for x, original_y in JOY_MOUNT_HOLES:
        y = FACE_Y_SUM-original_y
        parts.append(cz(x, y, 3.4, -5.8, JOY_BOARD[4]))

    # 直针备用位的远侧两孔兼作弯针支座穿板锚点。
    # 中央深梁只走两模块之间的空隙，再将原L臂背侧托到载板附近。
    for _, x, z in JOY_SHARED_HOLES:
        parts += [cy(x, z, 3.4, -12.8, BACK),
                  beam((x, z), (-37.5, 35), 4.5, -10, BACK)]
    parts += [box(-39.75, -35.25, -10, BACK, 6.7, 35),
              box(-39.75, -15.8, -10, BACK, 6.7, 9.5),
              box(-19.4, -15.8, -10, BACK, 2, 9.5)]

    # SS位置保持，支承移到其背面；缩短到M2x10，不让螺钉伸出支架。
    for x, z in SS_HOLES:
        parts.append(cy(x, z, 3.4, -17.2, -8.66))
    parts += [box(-17.6, -10.8, -17.2, -8.66, -17.4, -1.1),
              beam((-14.2, -5), (-12, 12), 4.5),
              beam((-14.2, -14), (-27, -27), 4.5)]
    s = fuse(parts)
    cuts = []
    for h in P["mount_holes"]:
        x, z = h["xz"]
        cuts.append(cy(x, z, 1.2, -20, BACK+0.2))
    for i, (_, x, z) in enumerate(JOY_SHARED_HOLES):
        cuts.append(cy(x, z, 1.2, -12.1, BACK+.1))
        # 外侧有原主板固定柱；螺母改从两锚点之间的上部间隙滑入。
        x0, x1 = (x-2.35, x+8.5) if i == 0 else (x-8.5, x+2.35)
        cuts.append(box(x0, x1, -6.3, -4.5, z-2.1, z+2.1))
    # 加强筋到达H4，保留原轴孔和螺钉头空间。
    cuts += [cy(-27, -27, 1.2, -21, BACK+.2),
             cy(-27, -27, 2.2, -21, BASE[0])]
    # 根筋避开小件本体，并给元件插入时的3.5毫米行程留空间。
    for p in C["parts"]:
        if p["kind"] in {"resistor", "capacitor"}:
            e=p["envelope"]
            cuts.append(box(e["x"][0]-.8,e["x"][1]+.8,
                            BACK-e["y_above_board"]-4.3,BACK+.1,
                            e["z"][0]-.8,e["z"][1]+.8))
    # 给右键焊脚留出空间，避免新增摇杆短臂顶到焊点。
    for tail in next(p for p in C["parts"] if p["ref"] == "SW2")["pads"]:
        cuts.append(cy(*tail["xz"], 1.5, BACK-1.2, BACK+.1))
    for z in (-98, -57):
        z -= BATTERY_DROP_Z
        for x0, x1 in [(-50.6, -48.1), (-27.3, -24.8)]:
            cuts.append(box(x0, x1, -17.2, -14.4, z-2, z+2))
    # 两列小窗减料，中央纵筋和绑带附近横筋连续；窗边圆角减小尖角。
    for x0, x1 in [(-47.2, -40.4), (-35.0, -28.2)]:
        for z0, z1 in [(-109.3, -101.2), (-94.8, -83), (-80.6, -68.8),
                       (-66.4, -60.2), (-53.8, -41.2)]:
            z0,z1 = z0-BATTERY_DROP_Z,z1-BATTERY_DROP_Z
            window = box(x0, x1, -21, -16.7, z0, z1)
            cuts.append(cq.Workplane().add(window).edges("|Y").fillet(.8).val())
    for i, (x, original_y) in enumerate(JOY_MOUNT_HOLES):
        y = FACE_Y_SUM-original_y
        # 原弯针在板上面；模块降4毫米，螺钉及短柱跟随，仍用M2x10。
        cuts.append(cz(x, y, 2.15, -8.9, -3.8))
        if i == 0:
            cuts.append(cz(x, y, 1.2, -6, JOY_BOARD[4]+.1))
        else:
            # 2.4 x 3.6mm short slot along X accommodates the drawing's
            # stated tolerance while the other hole locates the module.
            cuts.append(fuse([cz(x-.6, y, 1.2, -6, JOY_BOARD[4]+.1),
                              cz(x+.6, y, 1.2, -6, JOY_BOARD[4]+.1),
                              box(x-.6, x+.6, y-1.2, y+1.2, -6, JOY_BOARD[4]+.1)]))
    for x, z in SS_HOLES:
        cuts.append(cy(x, z, 1.15, -17.3, -8.5))
        cuts.append(box(-21, -11.7, -11.45, -9.45, z-2.15, z+2.15))
        cuts.append(cy(x,z,2.2,-1.5,.95))
    # 给扳机信号孔的露脚留空间，不削薄摇杆支柱本身。
    for pad in next(p for p in C["parts"] if p["ref"]=="J_TRIG")["pads"]:
        cuts.append(cy(*pad["xz"],1.3,TOP-.1,TOP+1.15))
    for cut in cuts:
        s = s.cut(cut)
    return s.clean()


def references():
    r = {"电池": box(*BATTERY), "开发板": box(*SM), "陀螺仪板": box(*GY)}
    r["载板"] = prism(P["outline_xz"], BACK, TOP)
    for h in P["mount_holes"]:
        r["载板"] = r["载板"].cut(cy(*h["xz"], h["d"]/2, BACK-.1, TOP+.1))
    for part in C["parts"]:
        if not part.get("reserve", False):
            continue
        for pad in part.get("npth", []):
            x,z=pad["xz"]
            dx,dz=pad["drill"]
            if dx==dz:
                bore=cy(x,z,dx/2,BACK-.1,TOP+.1)
            else:
                offset=(dx-dz)/2
                bore=fuse([cy(x-offset,z,dz/2,BACK-.1,TOP+.1),
                           cy(x+offset,z,dz/2,BACK-.1,TOP+.1),
                           box(x-offset,x+offset,BACK-.1,TOP+.1,z-dz/2,z+dz/2)])
            r["载板"]=r["载板"].cut(bore)
    for p in C["parts"]:
        if not p.get("populate", True):
            continue
        if p["ref"] in {"SW1", "J_MCU", "J_GY"}:
            continue
        envs = p.get("envelopes", [p["envelope"]] if "envelope" in p else [])
        backside = p.get("model_reference_mount_side", p.get("mount_side")) == "bottom"
        for i, e in enumerate(envs):
            ys = e.get("y_above_board", 0)
            a, b = ys if isinstance(ys, list) else (0, ys)
            y0, y1 = (BACK-b, BACK-a) if backside else (TOP+a, TOP+b)
            if e.get("kind") == "cylinder_y":
                s = cy(*e["xz"], e["radius"], y0, y1)
            else:
                s = box(*e["x"], y0, y1, *e["z"])
            r[f"{p['ref']}-本体{i}"] = flip_about_x(s, p["position_xz"][1])
        for i, pad in enumerate(p.get("model_reference_pads", p.get("pads", []))):
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
                         for pad in p.get("model_reference_pads", p["pads"])])
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
    old_z = JOYSTICK.get("model_reference_position_xz", JOYSTICK["position_xz"])[1]
    r["SW1-五针示意"] = fuse([cy(x+p["xz"][1]-old_z, JOY_PIN_CENTER[1],
                                    .32, FACE_Y_SUM-1.44, TOP+1)
                                  for p in JOYSTICK.get("model_reference_pads", JOYSTICK["pads"])])
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
    # 整个模块按实体旋转换面；配置pads已按这个最终姿态同步。
    for name, shape in list(r.items()):
        if name.startswith("SW1-") or name == "摇杆全角度留空":
            r[name] = shape.rotate((JOY_PIN_CENTER[0], MIDDLE_Y, 0),
                                   (JOY_PIN_CENTER[0], MIDDLE_Y, 1), 180)
        elif name.startswith("开发板") or name in {"USB接口", "USB插头留空"}:
            r[name] = flip_about_x(shape, (SM[4]+SM[5])/2)
        elif name.startswith("陀螺仪"):
            r[name] = flip_about_x(shape, (GY[4]+GY[5])/2)
        elif name.startswith("SS"):
            r[name] = opposite_face(shape)
    return r


def preview_references():
    """完整焊接后的外形；保守包络单独用于底座检查。"""
    import sys
    from gen2_component_details import assembled_details
    return assembled_details(sys.modules[__name__], references())[0]


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
                      "component_side_projection_mm": round(BACK-start_y+2.1, 3),
                      "driver": "元件面1.5mm内六角；拇指面薄钳扶螺母"})
    for i, (x, z) in enumerate(SS_HOLES, 1):
        k = f"SS{i}"
        r[k+"-螺钉"] = cy(x, z, 2, -1.36, .74).cut(
            hex_y(x,z,1.5,-.46,.85)).fuse(cy(x, z, 1, -11.36, -1.36))
        r[k+"-头侧垫片"] = cy(x, z, 2.5, -1.66, -1.36).cut(cy(x, z, 1.1, -1.76, -1.26))
        r[k+"-支承垫片"] = cy(x, z, 2.5, -8.66, -8.06).cut(cy(x, z, 1.1, -8.76, -7.96))
        r[k+"-螺母"] = hex_y(x, z, 4, -11.25, -9.65).cut(cy(x, z, 1.05, -11.35, -9.55))
        seats.append({"id": k, "length_mm": 10, "nut_engagement_mm": 1.6,
                      "screw_tip_y_mm": -11.36, "blind_bore_end_y_mm": -17.3,
                      "tip_end_clearance_mm": 5.94, "projection_past_nut_mm": .11,
                      "projection_protected_inside_mount": True})
    for i, (x, y) in enumerate(JOY_MOUNT_HOLES, 1):
        k = f"摇杆{i}"
        top = JOY_BOARD[5]
        head = cz(x, y, 2, -5.9, -3.8).cut(hex_z(x, y, 1.5, -6, -4.6))
        r[k+"-螺钉"] = head.fuse(cz(x, y, 1, -3.8, 6.2))
        r[k+"-螺母"] = hex_z(x, y, 4, top, top+1.6).cut(
            cz(x, y, 1.05, top-.1, top+1.7))
        seats.append({"id": k, "thread": "M2", "length_mm": 10,
                      "nut_engagement_mm": 1.6, "axis_direction_xyz": [0, 0, 1],
                      "projection_past_nut_mm": .8,
                      "hole_center_xy_mm": [x, y],
                      "driver": "下方1.5mm内六角；上方薄钳扶普通M2螺母，直接压模块原孔"})
    for i, (hole_id, x, z) in enumerate(JOY_SHARED_HOLES, 1):
        k = f"共用锚点{i}"
        head = cy(x, z, 2, TOP, TOP+2.1).cut(
            hex_y(x, z, 1.5, TOP+1.0, TOP+2.2))
        r[k+"-螺钉"] = head.fuse(cy(x, z, 1, TOP-10, TOP))
        r[k+"-螺母"] = hex_y(x, z, 4, -6.2, -4.6).cut(
            cy(x, z, 1.05, -6.3, -4.5))
        seats.append({"id": hole_id, "thread": "M2", "length_mm": 10,
                      "hole_center_xz_mm": [x, z], "axis_direction_xyz": [0, -1, 0],
                      "nut_engagement_mm": 1.6, "nut_y_mm": [-6.2, -4.6],
                      "screw_tip_y_mm": round(TOP-10, 3), "blind_bore_end_y_mm": -12.1,
                      "tip_end_clearance_mm": round(TOP-10+12.1, 3),
                      "future_straight_screw_projection_past_nut_mm": .83,
                      "driver": "拇指面1.5毫米内六角；普通M2螺母从两锚点之间的上部间隙滑入背侧锚座"})
    for seat in seats:
        if "hole_center_xy_mm" in seat:
            x, y = seat["hole_center_xy_mm"]
            seat["hole_center_xy_mm"] = [x, FACE_Y_SUM-y]
    # 只有摇杆紧固件留在拇指面；主板四柱及SS支承均在元件面。
    return {name: opposite_face(shape) if name.startswith("摇杆") else shape
            for name, shape in r.items()}, seats


def verify(s, refs):
    overlaps = {k: round(s.intersect(v).Volume(), 6) for k, v in refs.items()}
    collisions = {k: v for k, v in overlaps.items() if v > 0.001}
    insertion = {}
    groups = {"载板小件": [v for k, v in refs.items() if not k.startswith("SW1-") and ("-本体" in k or "-焊脚" in k)],
              "摇杆": [v for k, v in refs.items() if k.startswith("SW1-")],
              "开发板": [refs[k] for k in ["开发板", "开发板元件", "开发板排针", "USB接口"]],
              "陀螺仪板": [refs[k] for k in ["陀螺仪板", "陀螺仪元件", "陀螺仪排针"]],
              "电池": [refs["电池"]], "SS": [refs["SS金属扳机本体"]]}
    # 裸板从上方滑入，避开跨板短臂；随后由侧面把模块送入敞开腔体，再完成3.5mm直插。
    # L形板轮廓沿+Z的连续扫掠保持缺口，不能用整板矩形包围盒填掉缺口。
    max_z=max(z for _,z in P["outline_xz"])
    bare_sweep=prism([(x,z+120 if z==max_z else z) for x,z in P["outline_xz"]],BACK,TOP)
    insertion["裸载板从上方滑入支架"]=round(s.intersect(bare_sweep).Volume(),6)
    paths = [("小元件在敞开腔体内插入", groups["载板小件"], (0, 0, 0), (0, -3.5, 0)),
             ("摇杆弯针由拇指面插入", groups["摇杆"], (0, 0, 0), (0, 32, 0)),
             ("开发板在敞开腔体内插入", groups["开发板"], (0, 0, 0), (0, -3.5, 0)),
             ("电池放入托内", groups["电池"], (0, 0, 0), (0, 32, 0)),
             ("GY在敞开腔体内插入", groups["陀螺仪板"], (0, 0, 0), (0, -3.5, 0)),
             ("SS从前方缺口放入", groups["SS"], (0, 0, 0), (25, 0, 0))]
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
    for i in (1, 2):
        k = f"摇杆{i}-螺母"
        nut_paths[k] = round(s.intersect(swept_box(hw[k], (0, 0, 12))).Volume(), 6)
    for i, _ in enumerate(JOY_SHARED_HOLES, 1):
        k = f"共用锚点{i}-螺母"
        path = swept_box(hw[k], (6 if i == 1 else -6, 0, 0))
        hit = s.intersect(path).Volume()
        for n, shape in refs.items():
            if "留空" not in n and "摆杆示意" not in n:
                hit = max(hit, path.intersect(shape).Volume())
        nut_paths[k] = round(hit, 6)
    tool_access = {}
    for h in P["mount_holes"]:
        start_y = SHORT_POST_Y if h["id"] == "H2" else BASE[0]
        driver = cy(*h["xz"], 1.5, -36, start_y-2.11)
        tool_access[h["id"]] = round(s.intersect(driver).Volume(), 6)
    for i, (x, z) in enumerate(SS_HOLES, 1):
        driver = cy(x, z, 1.5, .75, 24)
        hit = s.intersect(driver).Volume()
        for n, shape in refs.items():
            if "留空" not in n and "摆杆示意" not in n:
                hit = max(hit, driver.intersect(shape).Volume())
        tool_access[f"SS{i}"] = round(hit, 6)
    for i, (x, y) in enumerate(JOY_MOUNT_HOLES, 1):
        driver = opposite_face(cz(x, y, 1.5, -24, -5.91))
        hit = s.intersect(driver).Volume()
        for n, shape in refs.items():
            if "留空" not in n and "摆杆示意" not in n:
                hit = max(hit, driver.intersect(shape).Volume())
        tool_access[f"摇杆{i}"] = round(hit, 6)
    for i, (_, x, z) in enumerate(JOY_SHARED_HOLES, 1):
        driver = cy(x, z, 1.5, TOP+2.11, 30)
        hit = s.intersect(driver).Volume()
        for n, shape in refs.items():
            if "留空" not in n and "摆杆示意" not in n:
                hit = max(hit, driver.intersect(shape).Volume())
        tool_access[f"共用锚点{i}"] = round(hit, 6)
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
            "joystick_dimension_basis": C.get("joystick_mounting", {}),
            "battery_envelope_mm": bounds(refs["电池"]),
            "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
            "installation_faces": {"拇指面+Y": "摇杆及从主板缺口绕过的局部短臂", "元件面-Y": "一体支架、电池托、八颗小件护板；上方两块模块仍敞开且位置不变"},
            "retention": {"载板": "元件面四柱固定；H2用M2x10，其余3颗M2x20，拇指面M2螺母轻夹，不另加垫片",
                          "SS": "原SS-01GL两孔，改用2颗已有M2x10；原垫片填0.6mm名义间隙，元件面侧插M2螺母",
                          "开发板": "两排各9针由摇杆相反面直接焊在载板，板间留3mm，USB朝+X；电池B+/B-接两根短线，孔号与网络已同步",
                          "GY": "左8右6排针由摇杆相反面直接焊在载板，板间留3mm；孔号与网络已同步",
                          "摇杆": "DZYJ黑板33x27标称，原生帽朝+Z；模块降低4mm，让原有弯针和塑料条在小板上面；主板五孔不变。模块近侧两孔用2颗M2x10固定在原短柱；另用2颗M2x10经主板远侧共用孔固定背侧深梁，将原L臂背部支到主板附近，均用普通M2螺母、不新增垫片；未来直针模式可用共用孔固定模块另两角",
                          "电池": "602060含保护板/出线预留20x80x8mm；2.4mm开窗框筋、深侧梁及圆角根筋承担握持载荷，放入面与出线端敞开；两条软绑带经侧壁窗口仅作防脱，不勒紧软包"},
            "battery_structure": {"outer_width_mm": 25.6, "frame_thickness_mm": 2.4,
                                  "side_beam_width_mm": 2.3, "side_beam_depth_mm": 11.1,
                                  "battery_side_clearance_mm": .5, "rim_above_battery_mm": .5,
                                  "window_count": 10, "window_width_mm": 6.8,
                                  "window_corner_radius_mm": .8, "root_radius_mm": .8,
                                  "note": "外缘承力，开放面与小窗不能提供全方向抗压保护；未做载荷实测"},
            "limits": ["八颗手焊小元件，实际载板翻面孔号、摇杆横排五针孔和布线已同步；仍需实物插装与通电验证",
                       "HW504板33x27、孔距26.4x19.5及孔径3.3来自DZYJ标称图；图注误差0.5-1mm，弯针偏移、轴心及帽仍为示意",
                       "模块、SS和电池为保守包络，购入实物尺寸/树脂收缩需试装",
                       "裸板轮廓与最终直插行程已检查；模块先从侧面送入敞开腔体的转向动作未作刚体全程仿真",
                       "手焊线为可行建议路径；绑带/绝缘软垫由实物固定，触摸、电池温升、无线性能需实测",
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


def routed_pcb_meshes(b, source=None):
    """保留实际板的分材质铜层、绿油、丝印，避免OBJ读取后整板变单色。"""
    import vtk
    source = source or ROOT / "pcb" / "3d" / "gun-mouse-gen2.obj"
    material_data, current = {}, None
    for line in source.with_suffix(".mtl").read_text(encoding="utf-8").splitlines():
        words=line.split()
        if not words:
            continue
        if words[0]=="newmtl":
            current=words[1]
            material_data[current]=[.5,.5,.5,1.]
        elif words[0]=="Kd":
            material_data[current][:3]=map(float,words[1:4])
        elif words[0]=="d":
            material_data[current][3]=float(words[1])
    vertices, groups, current = [], {}, None
    for line in source.read_text(encoding="utf-8").splitlines():
        words=line.split()
        if not words:
            continue
        if words[0]=="v":
            vertices.append(tuple(map(float,words[1:4])))
        elif words[0]=="usemtl":
            current=words[1]
            groups.setdefault(current,[])
        elif words[0]=="f":
            groups[current].append([int(w.split("/")[0])-1 for w in words[1:]])
    mid_w=(min(p[2] for p in vertices)+max(p[2] for p in vertices))/2
    labels={"mtl1":"载板-基材","mtl7037":"载板-绿色保护层","mtl10481":"载板-丝印",
            "mtl12537":"载板-真实铜层焊盘","mtl44413":"载板-孔壁金属"}
    meshes,colors=[],{}
    for material,faces in groups.items():
        points,cells=vtk.vtkPoints(),vtk.vtkCellArray()
        remap={}
        for face in faces:
            ids=[]
            for old in face:
                if old not in remap:
                    u,v,w=vertices[old]
                    remap[old]=points.InsertNextPoint(-u-3-b.xmin,b.zmax-(v+45),
                                                     MIDDLE_Y+w-mid_w-BASE[0])
                ids.append(remap[old])
            cells.InsertNextCell(len(ids),ids)
        data=vtk.vtkPolyData()
        data.SetPoints(points)
        data.SetPolys(cells)
        name=labels.get(material,"载板-"+material)
        meshes.append((name,name,data))
        colors[name]=material_data[material]
    return meshes,colors


def export_assembled_stl(render_preview=True):
    """同一组毫米几何导出装配STL和带色分组OBJ，仅供装配查看。"""
    import vtk
    import sys
    from gen2_component_details import assembled_details
    base = cq.importers.importStep(str(OUT / "step" / "engineering_mount.step")).val()
    b = base.BoundingBox()
    refs, detail_colors, wires = assembled_details(sys.modules[__name__], references())
    refs.pop("载板")
    refs.update(hardware()[0])
    geometry = vtk.vtkAppendPolyData()
    meshes = []
    colors = {"底座": (.22,.48,.61), "电路板": (.10,.42,.20),
              "电池": (.72,.74,.77), "摇杆帽": (.10,.10,.11),
              "芯片": (.23,.25,.27), "金属": (.64,.66,.69)}
    colors.update(detail_colors)
    invalid=[name for name,shape in refs.items() if not shape.isValid()]
    if invalid:
        raise RuntimeError("详细外形无效："+"、".join(invalid))
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
        material = (name if name in detail_colors else "底座" if name == "一体底座" else "电池" if name == "电池" else "摇杆帽" if "摇杆帽" in name
                    else "电路板" if name in {"开发板", "陀螺仪板", "SW1-模块黑板"}
                    else "芯片" if "元件" in name or "金属本体" in name
                    else "金属")
        meshes.append((name, material, data))
    board_meshes,board_colors=routed_pcb_meshes(b)
    colors.update(board_colors)
    for item in board_meshes:
        geometry.AddInputData(item[2])
        meshes.append(item)
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
    obj_path = OUT / "第二代完整装配.obj"
    mtl_path = obj_path.with_suffix(".mtl")
    with mtl_path.open("w", encoding="utf-8", newline="\n") as output:
        for name, rgba in colors.items():
            output.write(f"newmtl {name}\nKa 0.15 0.15 0.15\nKd {' '.join(map(str, rgba[:3]))}\n"
                         f"Ks 0.2 0.2 0.2\nNs 25\nd {rgba[3] if len(rgba)>3 else 1.0}\nillum 2\n")
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
    report_path=OUT/"assembly-check.json"
    report=json.loads(report_path.read_text(encoding="utf-8"))
    wire_shapes={n:s for n,s in refs.items() if n.endswith("-绝缘皮")}
    base_hits={n:round(base.intersect(s).Volume(),5) for n,s in wire_shapes.items()}
    pair_hits={}
    wire_names=list(wire_shapes)
    for i,a in enumerate(wire_names):
        for other in wire_names[i+1:]:
            hit=wire_shapes[a].intersect(wire_shapes[other]).Volume()
            if hit>.001:
                pair_hits[a+"/"+other]=round(hit,5)
    report["assembled_model"]={"object_count":len(meshes),"invalid_shapes":invalid,
                               "manual_wire_count":len(wires),"wires":wires,
                               "wire_insulation_vs_mount_mm3":base_hits,
                               "wire_insulation_pair_overlaps_mm3":pair_hits,
                               "pcb_sha256":hashlib.sha256((ROOT/"pcb/gun-mouse-supermini-carrier.kicad_pcb").read_bytes()).hexdigest(),
                               "real_copper_materials":[n for n,_,_ in board_meshes],
                               "appearance_basis":"开发板为本地官方器件参考外形；其余小件和线弯曲为名义外形。B焊盘和铜箔尾按照片比读，未实测。",
                               "stl_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                               "obj_sha256":hashlib.sha256(obj_path.read_bytes()).hexdigest()}
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"毫米；{len(meshes)}组实体、{len(wires)}根手焊线；包含实际铜层及焊点。仅供装配查看，不能整体打印。",flush=True)
    if not render_preview:
        return
    # 使用完整导出网格离屏渲染，不打开任何软件窗口。
    renderer=vtk.vtkRenderer()
    renderer.SetBackground(.92,.94,.96)
    for _,material,mesh in meshes:
        mapper=vtk.vtkPolyDataMapper(); mapper.SetInputData(mesh)
        actor=vtk.vtkActor(); actor.SetMapper(mapper)
        rgb=colors[material]; actor.GetProperty().SetColor(*rgb[:3])
        actor.GetProperty().SetOpacity(rgb[3] if len(rgb)>3 else 1)
        renderer.AddActor(actor)
    camera=renderer.GetActiveCamera()
    camera.SetPosition(210,-230,-200); camera.SetViewUp(0,-1,0)
    camera.ParallelProjectionOn(); renderer.ResetCamera()
    window=vtk.vtkRenderWindow(); window.SetOffScreenRendering(1)
    window.SetSize(1400,1400); window.AddRenderer(renderer); window.Render()
    capture=vtk.vtkWindowToImageFilter(); capture.SetInput(window); capture.ReadFrontBufferOff(); capture.Update()
    png=vtk.vtkPNGWriter(); png.SetFileName(str(OUT/"renders/gen2-assembly.png"))
    png.SetInputConnection(capture.GetOutputPort()); png.Write(); window.Finalize()


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
    printed = s.rotate((0, 0, 0), (1, 0, 0), 90).translate(V(-b.xmin, b.zmax, PRINT_FLOOR_Y))
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
