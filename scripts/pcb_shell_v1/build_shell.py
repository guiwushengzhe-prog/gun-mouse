"""PCB-Shell-V1 参数化外壳与机构件（CadQuery）。

所有零件在整机坐标中建模（X 向前、Y 向左、Z 向上，毫米），数值全部来自 config/pcb-shell-v1.json。
导出：各零件 STEP、按打印姿态摆放的 STL、整机装配 STEP、干涉检查报告与预览图。

运行：
    $env:PYTHONUTF8 = '1'
    & 'E:\\GunMouseCAD\\CadQuery\\python.exe' scripts\\pcb_shell_v1\\build_shell.py
需要先运行 layout.py；若存在 outputs/pcb-shell-v1/pcb-with-parts.step（build_pcb.py 导出），会一并装配并做干涉检查。
"""

import json
import math
import sys
from pathlib import Path

import cadquery as cq
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Trsf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUT, ROOT, fillet_segments, load_config, write_json  # noqa: E402
from clean_stl_zero_area import clean as clean_stl  # noqa: E402

V = cq.Vector
DELIVER = ROOT / "deliverables" / "pcb-shell-v1"
# 握把前缘 G(8,-4)→H(2,-32) 相对竖直的倾角，扳机面盖按此平躺打印
COVER_TILT = math.degrees(math.atan2(6.0, 28.0))


# ---------------------------------------------------------------- 基础几何

def box(x0, x1, y0, y1, z0, z1):
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    z0, z1 = sorted((z0, z1))
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def cyl_y(x, z, r, y0, y1):
    y0, y1 = sorted((y0, y1))
    return cq.Solid.makeCylinder(r, y1 - y0, V(x, y0, z), V(0, 1, 0))


def cyl_x(y, z, r, x0, x1):
    x0, x1 = sorted((x0, x1))
    return cq.Solid.makeCylinder(r, x1 - x0, V(x0, y, z), V(1, 0, 0))


def cone_y(x, z, r0, r1, y0, y1):
    return cq.Solid.makeCone(r0, r1, y1 - y0, V(x, y0, z), V(0, 1, 0))


def outline_wire(points_r, y):
    edges = []
    for seg in fillet_segments(points_r):
        if seg[0] == "line":
            (a, b) = seg[1], seg[2]
            edges.append(cq.Edge.makeLine(V(a[0], y, a[1]), V(b[0], y, b[1])))
        else:
            a, m, b = seg[1], seg[2], seg[3]
            edges.append(cq.Edge.makeThreePointArc(V(a[0], y, a[1]), V(m[0], y, m[1]), V(b[0], y, b[1])))
    return cq.Wire.assembleEdges(edges)


def prism_xz(points, y0, y1):
    """XZ 平面多边形沿 Y 拉伸。"""
    wire = cq.Wire.makePolygon([V(x, y0, z) for x, z in points], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), V(0, y1 - y0, 0))


def fillet_y_faces(solid, r):
    wp = cq.Workplane().add(solid)
    return wp.faces(">Y or <Y").edges().fillet(r).val()


def fuse(base, *others):
    for o in others:
        base = base.fuse(o)
    return base.clean()


def cut(base, *others):
    for o in others:
        base = base.cut(o)
    return base.clean()


def transformed(shape, matrix, offset):
    """matrix 为 3×3 行主序旋转，offset 为平移。"""
    t = gp_Trsf()
    m = matrix
    t.SetValues(m[0][0], m[0][1], m[0][2], offset[0],
                m[1][0], m[1][1], m[1][2], offset[1],
                m[2][0], m[2][1], m[2][2], offset[2])
    return cq.Shape.cast(BRepBuilderAPI_Transform(shape.wrapped, t, True).Shape())


# ---------------------------------------------------------------- 外壳

class Shell:
    def __init__(self, cfg):
        self.cfg = cfg
        s = cfg["shell"]
        self.s = s
        self.half = s["half_width_y"]
        self.wall = s["wall"]
        self.split = s["split_y"]
        self.inner_y = self.half - self.wall
        pts = s["outline_xz"]
        outer_face = cq.Face.makeFromWires(outline_wire(pts, -self.half))
        outer = cq.Solid.extrudeLinear(outer_face, V(0, 2 * self.half, 0))
        self.outer = fillet_y_faces(outer, s["edge_fillet"])
        inner_wire = outline_wire(pts, -self.inner_y).offset2D(-self.wall, "arc")[0]
        inner = cq.Solid.extrudeLinear(cq.Face.makeFromWires(inner_wire), V(0, 2 * self.inner_y, 0))
        self.inner = fillet_y_faces(inner, s["edge_fillet"] - self.wall)
        self.hollow = self.outer.cut(self.inner)

    def halves(self):
        big = 400
        left = self.hollow.intersect(box(-big, big, self.split, big, -big, big))
        right = self.hollow.intersect(box(-big, big, -big, self.split, -big, big))
        return left, right

    def keep_inside(self, solid):
        """把从内壁长出的特征裁在外壳外表面以内。"""
        return solid.intersect(self.outer)


def build_shell(cfg):
    sh = Shell(cfg)
    left, right = sh.halves()
    s = cfg["shell"]
    b = cfg["board"]
    sc = s["screw"]
    split = sh.split
    yi = sh.inner_y
    top_y = b["top_face_y"]
    back_y = top_y - b["thickness"]
    add_l, add_r, cut_l, cut_r = [], [], [], []

    # 主板螺柱：右半壳顶住板背面，左半壳压住板面；M2 自攻螺丝从右侧穿板拧入左侧
    for h in b["mount_holes"]:
        x, z = h["xz"]
        add_r.append(sh.keep_inside(cyl_y(x, z, sc["boss_d"] / 2, -yi - 1.5, back_y)))
        add_l.append(sh.keep_inside(cyl_y(x, z, sc["boss_d"] / 2, top_y, yi + 1.5)))
        cut_r.append(cyl_y(x, z, sc["clearance_hole"] / 2, -sh.half - 1, back_y + 0.1))
        cut_r.append(cyl_y(x, z, sc["head_counterbore_d"] / 2, -sh.half - 1, sc["head_seat_y"]))
        cut_l.append(cyl_y(x, z, sc["pilot_hole"] / 2, top_y - 0.1, top_y + 12))
    # 仅连接外壳的螺柱
    for x, z in s["shell_only_screws_xz"]:
        add_r.append(sh.keep_inside(cyl_y(x, z, sc["boss_d"] / 2, -yi - 1.5, split)))
        add_l.append(sh.keep_inside(cyl_y(x, z, sc["boss_d"] / 2, split, yi + 1.5)))
        cut_r.append(cyl_y(x, z, sc["clearance_hole"] / 2, -sh.half - 1, split + 0.1))
        cut_r.append(cyl_y(x, z, sc["head_counterbore_d"] / 2, -sh.half - 1, sc["head_seat_y"]))
        cut_l.append(cyl_y(x, z, sc["pilot_hole"] / 2, split - 0.1, split + 12))

    # 上板条背面支撑（避开排母引脚行 z=12.3/37.7）
    for x, z in [(57.0, 25.0), (31.0, 25.0), (6.0, 25.0)]:
        add_r.append(sh.keep_inside(cyl_y(x, z, 2.5, -yi - 1.5, back_y)))
    # 开发板防脱：左壳内柱靠近模组屏蔽罩上方，留 0.9 毫米间隙
    dv = cfg["dev_board"]
    dev_top = top_y + dv["female_header_height"] + dv["male_header_plastic"] + dv["board_thickness_assumed"]
    shield_top = dev_top + 3.1
    for x in (46.0, 55.0):
        add_l.append(sh.keep_inside(cyl_y(x, dv["board_xz"]["center_z"], 2.0, shield_top + 0.9, yi + 1.5)))

    # 扳机小板卡槽（左右各一条，底端封闭承托，顶端由左壳封闭）
    d = b["daughter"]
    xt = d["assembled_top_face_x"]
    xb = xt - b["thickness"]
    a0, a1 = d["outline_local"]["a"]
    b0, b1 = d["outline_local"]["b"]
    rib_x = (xb - 1.4, xt + 1.6)
    slot_x = (xb - 0.15, xt + 0.15)
    for sign, half, adds, cuts in [(-1, "R", add_r, cut_r), (1, "L", add_l, cut_l)]:
        edge = a1 if sign > 0 else a0
        y_in = edge - sign * 1.4
        y_out = sign * (yi + 1.5)
        z_lo = b0 - 1.0
        z_hi = b1 + (1.5 if sign > 0 else -1.5)
        adds.append(sh.keep_inside(box(*rib_x, y_in, y_out, z_lo, z_hi)))
        # 槽深多留 0.9 毫米，容纳掰邮票孔后的残留凸起
        cuts.append(box(*slot_x, y_in - sign * 0.01, edge + sign * 0.9, b0 - 0.25,
                        b1 + (0.25 if sign > 0 else 5)))

    # 电池仓：四周肋板与底部支撑条（右半壳）；顶部中段留出电池线
    bt = cfg["battery"]
    (px0, pz0), (px1, pz1) = bt["pocket_xz_min"], bt["pocket_xz_max"]
    pocket_back = back_y - 0.5 - bt["pocket_thickness"]
    rib_top = back_y - 1.2
    t = 1.2
    ribs = [box(px0 - t, px1 + t, -yi - 1.5, rib_top, pz0 - t, pz0),
            box(px0 - t, px0, -yi - 1.5, rib_top, pz0 - t, pz1 + t),
            box(px1, px1 + t, -yi - 1.5, rib_top, pz0 - t, pz1 + t),
            box(px0 - t, -46.0, -yi - 1.5, rib_top, pz1, pz1 + t),
            box(-34.0, px1 + t, -yi - 1.5, rib_top, pz1, pz1 + t)]
    for zz in (pz0 + 10, (pz0 + pz1) / 2, pz1 - 10):
        ribs.append(box(px0, px1, -yi - 1.5, pocket_back, zz - 1.5, zz + 1.5))
    add_r.extend(sh.keep_inside(r) for r in ribs)

    # 扳机滑道：窗口、导轨、限位与弹簧座
    tr = cfg["trigger"]
    sw = tr["switch_contact_from_board"]
    x_rest = xt + sw["rest"]
    x_press = xt + sw["stop"]
    travel = x_rest - x_press
    bar_z0, bar_z1 = tr["bar"]["z"]
    by = tr["bar"]["y_half"]
    window = box(-0.5, 16, -by - 0.35, by + 0.35, bar_z0 - 0.35, bar_z1 + 0.35)
    cut_l.append(window)
    cut_r.append(window)
    # 底导轨
    rail_b = box(x_press + 1.5 - 1.0, 14, -7.5, 7.5, bar_z0 - 2.0, bar_z0 - 0.35)
    # 顶导轨（只在前段，避开微动杠杆）；其后端面同时是复位限位，挡住滑杆尾部的凸齿
    rest_stop_x = x_rest + 2.0
    rail_t = box(rest_stop_x, 14, -7.5, 7.5, bar_z1 + 0.35, bar_z1 + 2.2)
    # 弹簧座兼按压硬限位（滑杆下段后端面）
    lower_rear_press = x_press + 1.5
    spring_block = box(x_press - 4.0 + 1.5, lower_rear_press, -by - 0.5, by + 0.5,
                       bar_z0 - 0.5, tr["spring"]["axis_z"] + 3.3)
    for solid in (rail_b, rail_t, spring_block):
        add_l.append(sh.keep_inside(solid.intersect(box(-100, 100, split, 100, -200, 200))))
        add_r.append(sh.keep_inside(solid.intersect(box(-100, 100, -100, split, -200, 200))))

    # 右键开口与限位（左半壳）
    rb = cfg["right_button"]
    rx, rz = rb["xz"]
    cap = rb["cap"]
    cut_l.append(box(rx - cap["face_w"] / 2 - 0.3, rx + cap["face_w"] / 2 + 0.3, yi - 1, sh.half + 1,
                     rz - cap["face_h"] / 2 - 0.3, rz + cap["face_h"] / 2 + 0.3))
    # 摇杆锥形开口：20° 时摇杆杆身碰到开口内缘
    js = cfg["joystick"]
    jx, jz = js["shaft_xz"]
    pivot_y = top_y + js["pivot_above_pcb_assumed"]
    tan = math.tan(math.radians(js["stop_angle_deg"]))
    rs = js["knob"]["stem_d"] / 2 / math.cos(math.radians(js["stop_angle_deg"]))
    r_in = (yi - pivot_y) * tan + rs
    r_out = (sh.half - pivot_y) * tan + rs
    cut_l.append(cone_y(jx, jz, r_in, r_out + 0.5, yi - 0.01, sh.half + 0.5))

    # 底部：Type-C、开关、充电灯
    bp = b["bottom_pocket"]
    zb_out = -96.0
    pocket_floor = zb_out + 1.3
    pocket = box(bp["x"][0] - 1.0, bp["x"][1] + 1.0, -4.5, 5.5, zb_out + sh.wall + 0.05, pocket_floor)
    usb = s["usb_opening"]
    usb_x = next(p for p in cfg["parts"] if p["ref"] == "USB1")["xz"][0]
    usb_y = top_y + 1.63
    usb_cut = box(usb_x - usb["w"] / 2, usb_x + usb["w"] / 2, usb_y - usb["h"] / 2, usb_y + usb["h"] / 2,
                  zb_out - 1, pocket_floor + 0.1)
    usb_recess = box(usb_x - usb["recess_w"] / 2, usb_x + usb["recess_w"] / 2, usb_y - usb["recess_h"] / 2,
                     usb_y + usb["recess_h"] / 2, zb_out - 1, zb_out + usb["recess_depth"])
    sw3_x = next(p for p in cfg["parts"] if p["ref"] == "SW3")["xz"][0]
    ss = s["switch_slot"]
    sw_cut = box(sw3_x - ss["w"] / 2, sw3_x + ss["w"] / 2, top_y - 0.3, top_y - 0.3 + ss["h"], zb_out - 1,
                 pocket_floor + 0.1)
    led = next(p for p in cfg["parts"] if p["ref"] == "LED1")["xz"]
    # 径向增加 0.01 毫米布尔切削余量，消除灯孔与分壳面的零厚度相切；名义孔轴和配置不变。
    led_cut = cq.Solid.makeCylinder(s["led_window_d"] / 2 + 0.01, 6, V(led[0], top_y + 0.8, zb_out - 1), V(0, 0, 1))
    for cuts in (cut_l, cut_r):
        cuts.extend([pocket, usb_cut, usb_recess, sw_cut, led_cut])

    left = cut(fuse(left, *add_l), *cut_l)
    right = cut(fuse(right, *add_r), *cut_r)
    info = {"joystick_opening_r_inner": round(r_in, 2), "joystick_opening_r_outer": round(r_out, 2),
            "trigger_rest_x": x_rest, "trigger_press_x": x_press, "trigger_travel": round(travel, 2)}
    return sh, left, right, info


# ---------------------------------------------------------------- 机构件

def build_trigger(cfg, offset_x=0.0):
    tr = cfg["trigger"]
    b = cfg["board"]
    xt = b["daughter"]["assembled_top_face_x"]
    sw = tr["switch_contact_from_board"]
    x_end = xt + sw["rest"]
    z0, z1 = tr["bar"]["z"]
    by = tr["bar"]["y_half"]
    bl = tr["blade"]
    # 握把前缘 G(8,-4)→H(2,-32)，扳机片背面与之平行并留 gap
    g, h = (8.0, -4.0), (2.0, -32.0)

    def face_x(z):
        return g[0] + (h[0] - g[0]) * (z - g[1]) / (h[1] - g[1])

    bz0, bz1 = bl["z"]
    gap = bl["gap_to_grip"]
    thick = bl["thickness"]
    prof = [(face_x(bz1) + gap, bz1), (face_x(bz1) + gap + thick, bz1 - 1.5),
            (face_x(bz0) + gap + thick, bz0 + 1.5), (face_x(bz0) + gap, bz0)]
    w = bl["width_y"] / 2
    blade = prism_xz(prof, -w, w)
    blade = cq.Workplane().add(blade).edges("|Y").fillet(1.5).val()
    bar = box(x_end + 1.5, face_x(z1) + gap + 1.0, -by, by, z0, z1)
    nose = box(x_end, x_end + 1.6, -2.5, 2.5, tr["contact_z"] - 2.0, tr["contact_z"] + 2.0)
    # 复位凸齿：静止时前端面贴住顶导轨后端面
    tooth = box(x_end + 0.5, x_end + 2.0, -by, by, z1, z1 + tr["bar"]["rest_tooth_height"])
    trig = fuse(blade, bar, nose, tooth)
    sp = tr["spring"]
    spring_hole = cyl_x(0, sp["axis_z"], sp["hole_d"] / 2, x_end + 1.5 - 0.1, x_end + 1.5 + sp["hole_depth"])
    # 触摸铜箔凹槽（前面），面盖厚 cover_t，凹槽深 cover_t + 0.15
    ct = tr["touch_cover_thickness"]
    recess_prof = [(face_x(bz1 - 3) + gap + thick - ct - 0.15, bz1 - 3), (face_x(bz1 - 3) + gap + thick + 2, bz1 - 3),
                   (face_x(bz0 + 3) + gap + thick + 2, bz0 + 3), (face_x(bz0 + 3) + gap + thick - ct - 0.15, bz0 + 3)]
    recess = prism_xz(recess_prof, -w + 1.2, w - 1.2)
    # 导线槽：面盖上沿 → 扳机片顶面 → 背面 → 滑杆顶面
    wire = [box(face_x(bz1) + gap - 0.5, face_x(bz1) + gap + thick + 1, -0.7, 0.7, bz1 - 1.3, bz1 + 1),
            prism_xz([(face_x(bz1) + gap - 1.2, bz1 + 1), (face_x(bz1) + gap + 0.2, bz1 + 1),
                      (face_x(z1) + gap + 0.2, z1 - 1), (face_x(z1) + gap - 1.2, z1 - 1)], -0.7, 0.7),
            box(x_end - 1, face_x(z1) + gap + 1.0, -0.7, 0.7, z1 - 1.2, z1 + 0.1)]
    trig = cut(trig, spring_hole, recess, *wire)
    cover_prof = [(face_x(bz1 - 3.15) + gap + thick - ct, bz1 - 3.15), (face_x(bz1 - 3.15) + gap + thick, bz1 - 3.15),
                  (face_x(bz0 + 3.15) + gap + thick, bz0 + 3.15), (face_x(bz0 + 3.15) + gap + thick - ct, bz0 + 3.15)]
    cover = prism_xz(cover_prof, -w + 1.35, w - 1.35)
    if offset_x:
        trig = trig.translate(V(offset_x, 0, 0))
        cover = cover.translate(V(offset_x, 0, 0))
    return trig, cover


def build_button_cap(cfg, pressed=0.0):
    rb = cfg["right_button"]
    cap = rb["cap"]
    x, z = rb["xz"]
    yi = cfg["shell"]["half_width_y"] - cfg["shell"]["wall"]
    top_y = cfg["board"]["top_face_y"]
    tip_y = top_y + rb["plunger_top_above_pcb"] + 0.02
    fw, fh = cap["face_w"] / 2, cap["face_h"] / 2
    flange = box(x - fw - 1.4, x + fw + 1.4, yi - cap["flange"], yi, z - fh - 1.4, z + fh + 1.4)
    body = box(x - fw, x + fw, yi - cap["flange"], 20.85, z - fh, z + fh)
    lip = box(x - fw - 0.8, x + fw + 0.8, 20.85, 22.0, z - fh - 0.8, z + fh + 0.8)
    lip = cq.Workplane().add(lip).faces(">Y").edges().fillet(0.6).val()
    stem = box(x + 0.6 - cap["stem_w"] / 2, x + 0.6 + cap["stem_w"] / 2, tip_y, yi - cap["flange"] + 0.01, z - 2, z + 2)
    solid = fuse(flange, body, lip, stem)
    return solid.translate(V(0, -pressed, 0)) if pressed else solid


def build_knob(cfg, tilt_deg=0.0, tilt_axis=(1, 0, 0), tip_above_pcb=None):
    js = cfg["joystick"]
    k = js["knob"]
    jx, jz = js["shaft_xz"]
    top_y = cfg["board"]["top_face_y"]
    # 以三维模型的轴顶高度装配；实物若为规格书下限，帽子整体低 0.7 毫米，倾斜时仍不碰壳
    tip = top_y + (tip_above_pcb if tip_above_pcb is not None else js["shaft_tip_above_pcb"][1])
    bottom = tip - js["shaft_engage"]
    stem = cyl_y(jx, jz, k["stem_d"] / 2, bottom, k["cap_bottom_y"] + 0.5)
    capd = cyl_y(jx, jz, k["cap_d"] / 2, k["cap_bottom_y"], k["cap_bottom_y"] + k["cap_thickness"])
    knob = fuse(stem, capd)
    knob = cq.Workplane().add(knob).faces(">Y").edges().fillet(1.0).val()
    # D 形孔：Ø(4 + 间隙)，削边距对边 flat + 间隙
    c = k["d_hole_clearance"]
    hole = cyl_y(jx, jz, js["shaft_d"] / 2 + c, bottom - 0.1, tip + 0.2)
    # 双削边孔：Ø(4+间隙) 与 |Z| ≤ 对边距/2 + 间隙 的交集
    flats = box(jx - 5, jx + 5, bottom - 0.2, tip + 0.3, jz - js["shaft_flat"] / 2 - c, jz + js["shaft_flat"] / 2 + c)
    keep = cyl_y(jx, jz, js["shaft_d"] / 2 + c + 0.01, bottom - 0.1, tip + 0.2).intersect(flats)
    knob = knob.cut(keep)
    if tilt_deg:
        pivot = V(jx, top_y + js["pivot_above_pcb_assumed"], jz)
        knob = knob.rotate(pivot, pivot + V(*tilt_axis), tilt_deg)
    return knob


# ---------------------------------------------------------------- 板与参考体

def load_pcb(cfg):
    path = OUTPUT / "pcb-with-parts.step"
    if not path.exists():
        return None, None
    shape = cq.importers.importStep(str(path)).val()
    b = cfg["board"]
    off_y = b["top_face_y"] - b["thickness"]
    main_m = [[-1, 0, 0], [0, 0, 1], [0, 1, 0]]
    d = b["daughter"]
    du, dv = d["panel_origin_uv"]
    # 拼板中的小板区域（PCB 数据坐标毫米）
    a0, a1 = d["outline_local"]["a"]
    b0, b1 = d["outline_local"]["b"]
    u_lo, u_hi = du - b1 - 0.05, du - b0 + 0.05
    v_lo, v_hi = dv + a0 - 0.05, dv + a1 + 0.6
    region = box(u_lo, u_hi, v_lo, v_hi, -30, 40)
    tabs_cut = box(u_lo, u_hi, v_hi - 0.7, dv + a1 + 2.6, -30, 40)
    main_parts, db_parts = [], []
    for solid in shape.Solids():
        bb = solid.BoundingBox()
        cx, cy = (bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2
        if bb.xlen > 60:  # 板体：切成主板与小板
            main_parts.append(solid.cut(region).cut(tabs_cut))
            db_parts.append(solid.intersect(region))
        elif u_lo < cx < u_hi and v_lo < cy < v_hi:
            db_parts.append(solid)
        else:
            main_parts.append(solid)
    main = transformed(cq.Compound.makeCompound(main_parts), main_m, (0, off_y, 0))
    # 小板：(u, v, w) → (X, Y, Z) = (w + xt - 1.6, v - dv, du - u)
    xt = d["assembled_top_face_x"]
    db_m = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
    db = transformed(cq.Compound.makeCompound(db_parts), db_m, (xt - b["thickness"], -dv, du))
    return main, db


def dev_board_model(cfg):
    dv = cfg["dev_board"]
    b = cfg["board"]
    top = b["top_face_y"]
    fx, ln, wd, cz = dv["board_xz"]["front_x"], dv["board_xz"]["length"], dv["board_xz"]["width"], dv["board_xz"]["center_z"]
    y0 = top + dv["female_header_height"] + dv["male_header_plastic"]
    y1 = y0 + dv["board_thickness_assumed"]
    parts = [box(fx - ln, fx, y0, y1, cz - wd / 2, cz + wd / 2),
             box(fx - ln + 1, fx - 1, y1, y1 + dv["component_height_assumed"], cz - wd / 2 + 2.6, cz + wd / 2 - 2.6),
             box(fx, fx + dv["antenna_overhang"], y1, y1 + 0.8, cz - 9, cz + 9)]
    for row in dv["row_z"].values():
        x0 = dv["pin1_x"] - (dv["pins_per_row"] - 1) * dv["pitch"] - 1.27
        x1 = dv["pin1_x"] + 1.27
        parts.append(box(x0, x1, y0 - dv["male_header_plastic"], y0, row - 1.27, row + 1.27))
        parts.append(box(x0, x1, y1, y1 + 3.0, row - 0.4, row + 0.4))
    return cq.Compound.makeCompound(parts)


def battery_model(cfg):
    bt = cfg["battery"]
    b = cfg["board"]
    back = b["top_face_y"] - b["thickness"] - 0.5
    (x0, z0), (x1, z1) = bt["pocket_xz_min"], bt["pocket_xz_max"]
    tmax, wmax, lmax = bt["fits_up_to"]
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    return box(cx - wmax / 2, cx + wmax / 2, back - tmax, back, cz - lmax / 2, cz + lmax / 2)


# ---------------------------------------------------------------- 检查与导出

def overlap(a, b):
    try:
        v = a.intersect(b).Volume()
    except Exception:  # noqa: BLE001 布尔失败按未知记录
        return None
    return round(v, 3)


def export_part(shape, name, print_rot=None):
    step_dir = DELIVER / "打印文件" / "STEP"
    stl_dir = DELIVER / "打印文件" / "STL"
    step_dir.mkdir(parents=True, exist_ok=True)
    stl_dir.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(cq.Workplane().add(shape), str(step_dir / f"{name}.step"))
    s = shape
    if print_rot:
        for axis, ang in print_rot:
            s = s.rotate(V(0, 0, 0), V(*axis), ang)
    bb = s.BoundingBox()
    s = s.translate(V(-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
    cq.exporters.export(cq.Workplane().add(s), str(stl_dir / f"{name}.stl"), tolerance=0.02, angularTolerance=0.1)
    mesh_cleanup = clean_stl(stl_dir / f"{name}.stl")
    bb = s.BoundingBox()
    return {"name": name, "print_size_mm": [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)],
            "volume_cm3": round(shape.Volume() / 1000, 2), "mesh_cleanup": mesh_cleanup}


def main():
    cfg = load_config()
    sh, left, right, info = build_shell(cfg)
    trig_rest, cover_rest = build_trigger(cfg)
    travel = info["trigger_travel"]
    trig_press, _ = build_trigger(cfg, offset_x=-travel)
    cap_rest = build_button_cap(cfg)
    cap_press = build_button_cap(cfg, pressed=0.85)
    knob = build_knob(cfg)
    js = cfg["joystick"]
    knobs_tilted = {f"{ax}{sgn}": build_knob(cfg, sgn * js["stop_angle_deg"], axis)
                    for ax, axis in [("X", (1, 0, 0)), ("Z", (0, 0, 1))] for sgn in (1, -1)}
    main_pcb, db_pcb = load_pcb(cfg)
    dev = dev_board_model(cfg)
    batt = battery_model(cfg)

    checks = {}
    movers = {"扳机(静止)": trig_rest, "扳机(按到底)": trig_press, "右键帽(静止)": cap_rest,
              "右键帽(按到底)": cap_press, "摇杆帽(居中)": knob, "开发板参考体": dev, "电池最大外形": batt}
    movers.update({f"摇杆帽(倾斜20°{k})": v for k, v in knobs_tilted.items()})
    if main_pcb is not None:
        movers["主板及器件"] = main_pcb
        movers["扳机小板及器件"] = db_pcb
    for name, solid in movers.items():
        checks[name] = {"左半壳": overlap(solid, left), "右半壳": overlap(solid, right)}
    if main_pcb is not None:
        checks["扳机(静止)"]["扳机小板及器件"] = overlap(trig_rest, db_pcb)
        checks["扳机(按到底)"]["扳机小板及器件"] = overlap(trig_press, db_pcb)
        checks["开发板参考体"]["主板及器件"] = overlap(dev, main_pcb)
        checks["电池最大外形"]["主板及器件"] = overlap(batt, main_pcb)
        checks["右键帽(静止)"]["主板及器件"] = overlap(cap_rest, main_pcb)
        checks["摇杆帽(居中)"]["主板及器件"] = overlap(knob, main_pcb)
    checks["左右半壳"] = {"互相": overlap(left, right)}
    # 反向验证：超过设计限位时应与外壳产生重叠，证明限位确实由外壳承担
    trig_over, _ = build_trigger(cfg, offset_x=-(travel + 0.5))
    trig_fwd, _ = build_trigger(cfg, offset_x=0.5)
    knob_over = build_knob(cfg, js["max_angle_deg"] + 1, (1, 0, 0))
    cap_over = build_button_cap(cfg, pressed=1.15)
    shell_both = left.fuse(right)
    limits = {
        "扳机多压0.5毫米(应>0，硬限位)": overlap(trig_over, shell_both),
        "扳机向前0.5毫米(应>0，复位限位)": overlap(trig_fwd, shell_both),
        f"摇杆帽倾斜{js['max_angle_deg'] + 1}°(应>0，开口限位)": overlap(knob_over, shell_both),
        "右键帽多压0.3毫米(应>0，帽沿限位)": overlap(cap_over, shell_both),
    }

    parts = [
        export_part(left, "左半壳", [((1, 0, 0), -90)]),
        export_part(right, "右半壳", [((1, 0, 0), 90)]),
        export_part(trig_rest, "扳机", [((1, 0, 0), 90)]),
        export_part(cover_rest, "扳机触摸面盖", [((0, 1, 0), -90 - COVER_TILT)]),
        export_part(cap_rest, "右键帽", [((1, 0, 0), -90)]),
        export_part(knob, "摇杆帽", [((1, 0, 0), -90)]),
    ]
    asm = cq.Assembly(name="枪型飞鼠整机V1")
    asm.add(left, name="左半壳", color=cq.Color(0.55, 0.65, 0.75, 0.6))
    asm.add(right, name="右半壳", color=cq.Color(0.45, 0.55, 0.68, 0.6))
    asm.add(trig_rest, name="扳机", color=cq.Color(0.2, 0.2, 0.22))
    asm.add(cover_rest, name="扳机触摸面盖", color=cq.Color(0.3, 0.55, 0.85))
    asm.add(cap_rest, name="右键帽", color=cq.Color(0.2, 0.2, 0.22))
    asm.add(knob, name="摇杆帽", color=cq.Color(0.15, 0.15, 0.15))
    asm.add(dev, name="开发板参考体", color=cq.Color(0.1, 0.3, 0.7))
    asm.add(batt, name="电池参考体", color=cq.Color(0.8, 0.75, 0.3))
    if main_pcb is not None:
        asm.add(main_pcb, name="主板", color=cq.Color(0.1, 0.5, 0.25))
        asm.add(db_pcb, name="扳机小板", color=cq.Color(0.45, 0.25, 0.6))
    asm_dir = DELIVER / "整机装配"
    asm_dir.mkdir(parents=True, exist_ok=True)
    asm.save(str(asm_dir / "枪型飞鼠整机装配.step"))
    report = {"version": cfg["version"], "info": info, "parts": parts, "interference_mm3": checks,
              "limit_checks_mm3": limits,
              "pcb_included": main_pcb is not None}
    write_json(OUTPUT / "shell-report.json", report)
    # 供预览脚本使用的单件模型
    prev = OUTPUT / "preview-models"
    prev.mkdir(parents=True, exist_ok=True)
    for name, solid in [("left", left), ("right", right), ("trigger", trig_rest), ("cover", cover_rest),
                        ("cap", cap_rest), ("knob", knob), ("dev", dev), ("battery", batt)]:
        cq.exporters.export(cq.Workplane().add(solid), str(prev / f"{name}.step"))
    if main_pcb is not None:
        cq.exporters.export(cq.Workplane().add(main_pcb), str(prev / "pcb.step"))
        cq.exporters.export(cq.Workplane().add(db_pcb), str(prev / "daughter.step"))
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
