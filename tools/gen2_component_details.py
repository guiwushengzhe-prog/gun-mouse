"""第二代实装外形、排针、焊点和七根手焊线；毫米，返回最终装配坐标。

SuperMini 元件采用本地官方 STEP 的参考外形，保留现有 1.6 mm 板体、15.24 mm 排针。
GY 的板尺寸/孔排来自说明书，芯片相对位置按说明书照片作外观参考，非实物扫描。
"""
from pathlib import Path
import math

DETAIL_COLORS = {
    "开发板-USB金属壳": (0.70, 0.72, 0.74),
    "开发板-USB黑色舌片": (0.055, 0.055, 0.055),
    "开发板-主芯片": (0.07, 0.075, 0.08),
    "开发板-陶瓷天线": (0.80, 0.67, 0.57),
    "开发板-元件焊端": (0.68, 0.69, 0.70),
    "开发板-小元件": (0.12, 0.13, 0.14),
    "开发板-按钮外框": (0.62, 0.64, 0.66),
    "开发板-按钮压头": (0.82, 0.82, 0.78),
    "开发板-孔铜圈": (0.77, 0.61, 0.20),
    "陀螺仪板": (0.30, 0.09, 0.44),
    "陀螺仪-孔铜圈": (0.80, 0.65, 0.24),
    "陀螺仪-主控外形参考": (0.09, 0.095, 0.10),
    "陀螺仪-传感器外形参考": (0.10, 0.105, 0.11),
    "陀螺仪-稳压器外形参考": (0.12, 0.12, 0.12),
    "陀螺仪-小元件外形参考": (0.34, 0.29, 0.23),
    "陀螺仪-焊端参考": (0.70, 0.71, 0.72),
}


def _compound(m, shapes):
    return m.cq.Compound.makeCompound(shapes)


def official_mcu_shapes(m, source=None):
    """模块面/USB方向已与当前references最终姿态一致；排针仍由主脚本生成。"""
    cq = m.cq
    source = Path(source or m.ROOT / "pcb" / "3d" / "SuperMini器件外形.step")
    if not source.exists():
        source = m.ROOT / ".logs" / "gen2" / "nologo-official-supermini.step"
    solids = cq.importers.importStep(str(source)).solids().vals()
    # 可读原始55实体（第0为板），也可读已剔除板体的54实体文件。
    if len(solids) == 54:
        original = {i + 1: s for i, s in enumerate(solids)}
    elif len(solids) == 55:
        original = {i: s for i, s in enumerate(solids) if i != 0}
    else:
        raise ValueError(f"官方开发板参考实体数不符: {len(solids)}")

    def final(s):
        # (u,v,w) -> (-u,-w,-v) 后平移；这是刚体旋转，不做镜像。
        return s.rotate((0, 0, 0), (1, 0, 0), -90).rotate(
            (0, 0, 0), (0, 0, 1), 180).translate(
            (m.SM[1], m.FACE_Y_SUM - m.SM[3], (m.SM[4] + m.SM[5]) / 2))

    # 官方 USB 简化体原来是实心；保持壳包络，切通插口并放独立黑舌片。
    usb = original[19]
    cavity = m.box(-1.8, 4.9, -4.08, 4.105, .55, 2.70)
    usb = usb.cut(cavity)
    tongue = m.box(-1.15, 4.85, -3.3, 3.3, 1.38, 1.78)
    # 官方板厚0.624mm。背面器件随当前1.6mm板厚外移，不嵌入板内。
    original[5] = original[5].translate((0, 0, -(m.SM_CFG["board_thickness"] - .624)))
    groups = {
        "开发板-主芯片": [30],
        "开发板-陶瓷天线": [54],
        "开发板-按钮外框": [43, 50],
        "开发板-按钮压头": [44, 49],
        "开发板-元件焊端": [11, 36, 37, 38, 39, 45, 46, 47, 48],
    }
    assigned = {19} | {i for ids in groups.values() for i in ids}
    groups["开发板-小元件"] = sorted(set(original) - assigned)
    out = {name: final(_compound(m, [original[i] for i in ids]))
           for name, ids in groups.items()}
    out["开发板-USB金属壳"] = final(usb)
    out["开发板-USB黑色舌片"] = final(tongue)
    p = next(p for p in m.C["parts"] if p["ref"] == "J_MCU")
    rings = [m.cy(*pad["xz"], 1.03, m.SM[3] + .005, m.SM[3] + .04).cut(
        m.cy(*pad["xz"], .65, m.SM[3] - .01, m.SM[3] + .05))
        for pad in p.get("model_reference_pads", p["pads"])]
    out["开发板-孔铜圈"] = m.flip_about_x(_compound(m, rings), sum(m.SM[4:6]) / 2)
    return out


def gy_photo_shapes(m):
    """含板体/孔/铜圈和参考芯片外观，不加排针；结果已经按X轴翻到背面。"""
    GY = m.GY
    face_y = GY[3]
    centre_z = (GY[4] + GY[5]) / 2
    p = next(p for p in m.C["parts"] if p["ref"] == "J_GY")
    board = m.box(*GY)
    # 说明书末页：安装孔Ø2.5；中心距右边缘5.116，纵距15.242。
    # 上孔距板上边约2.5由图比读，未宣称为厂家标注数值。
    hole_x = GY[0] + 5.116
    hole_zs = [GY[5] - 2.5, GY[5] - 2.5 - 15.242]
    for pad in p.get("model_reference_pads", p["pads"]):
        board = board.cut(m.cy(*pad["xz"], .55, GY[2] - .1, GY[3] + .1))
    for hz in hole_zs:
        board = board.cut(m.cy(hole_x, hz, 1.25, GY[2] - .1, GY[3] + .1))
    rings = []
    for pad in p.get("model_reference_pads", p["pads"]):
        for a, b in [(GY[2] - .035, GY[2] - .005), (GY[3] + .005, GY[3] + .035)]:
            rings.append(m.cy(*pad["xz"], .98, a, b).cut(
                m.cy(*pad["xz"], .55, a - .01, b + .01)))
    for hz in hole_zs:
        rings.append(m.cy(hole_x, hz, 1.9, face_y + .005, face_y + .04).cut(
            m.cy(hole_x, hz, 1.25, face_y - .01, face_y + .05)))

    def component(u, v, width, length, height):
        # 照片的u从左向右，v从上向下；先在原元件面建再刚体翻面。
        x, z = GY[1] - u, GY[5] - v
        return m.box(x - width/2, x + width/2, face_y, face_y + height,
                     z - length/2, z + length/2)

    out = {
        "陀螺仪板": board,
        "陀螺仪-孔铜圈": _compound(m, rings),
        "陀螺仪-主控外形参考": component(9.0, 9.8, 3.6, 4.8, .9),
        # LSM6DSV16X厂家封装标称2.5x3.0；具体板上位置按模块说明书照片近似。
        "陀螺仪-传感器外形参考": component(5.8, 15.3, 2.5, 3.0, .86),
        "陀螺仪-稳压器外形参考": component(5.6, 2.1, 1.6, 2.9, 1.0),
    }
    passives, terminals = [], []
    for u, v, w, h in [(5.5, 4.3, 1.6, .8), (5.5, 5.8, 1.6, .8),
                       (5.4, 7.6, 1.6, .8), (6.0, 9.2, 1.0, .6),
                       (11.4, 7.4, 1.0, .6), (11.6, 11.7, 1.6, .8),
                       (11.6, 14.8, 1.6, .8), (5.5, 18.6, 1.6, .8)]:
        passives.append(component(u, v, w, h, .45))
        for du in (-w/2 + .15, w/2 - .15):
            terminals.append(component(u + du, v, .3, h + .05, .49))
    out["陀螺仪-小元件外形参考"] = _compound(m, passives)
    out["陀螺仪-焊端参考"] = _compound(m, terminals)
    return {name: m.flip_about_x(shape, centre_z) for name, shape in out.items()}


WIRE_ROUTES = [
    ("电池正极线", "BAT_RAW", "红线", .55, .20,
     [(-55.7,-1.03,-36),(-55.7,-4.1,-36),(-55.7,-4.8,-40.5),
      (-53.5,-4.8,-43.5),(-53.5,1.2,-43.5),(-53.5,1.2,-28.8),
      (-39,1.2,-28.8),(-39,7.84,-28.8),(-39,7.84,-31.8)]),
    ("电池负极线", "GND", "黑线", .55, .20,
     [(-55.7,-1.03,-33.46),(-55.7,-4.1,-33.46),(-57.2,-6.2,-35),
      (-54.8,-6.2,-44.8),(-54.8,2.4,-44.8),(-54.8,2.4,-27.6),
      (-36.5,2.4,-27.6),(-36.5,7.84,-27.6),(-36.5,7.84,-31.8)]),
    ("开发板正极短线", "BAT_SW", "红线", .55, .20,
     [(-19,-1.03,35),(-19,-4.35,35),(-19,-4.35,32),(-9,-4.35,32),
      (-9,-4.35,21.2),(-11.7,-5.5,21.2),(-11.7,-6.23,21.2)]),
    ("开发板负极短线", "GND", "黑线", .55, .20,
     [(-21.54,-1.03,35),(-21.54,-5.55,35),(-21.54,-5.55,33),(-8,-5.55,33),
      (-8,-5.55,24.7),(-11.7,-5.5,24.7),(-11.7,-6.23,24.7)]),
    ("扳机公共端线", "GND", "黑线", .40, .125,
     [(-25.5,-1.03,-9),(-25.5,-4.8,-9),(-22.5,-7,-9),(-22.5,-7,1),
      (-19.1,-4.86,1),(-19.1,-4.86,-1.021)]),
    ("扳机常开端线", "TRIG", "蓝线", .40, .125,
     [(-25.5,-1.03,-6.46),(-25.5,-4.8,-6.46),(-23,-8.2,-6.46),
      (-22.5,-8.2,-11.8),(-19.1,-4.86,-11.8),(-19.1,-4.86,-9.821)]),
    ("触摸铜箔线", "TOUCH_ELECTRODE", "黄线", .40, .125,
     [(-25.5,-1.03,-18),(-25.5,-4.8,-18),(-23.5,-14.5,-18),
      (-22.5,-14.5,3.5),(-5.5,-14.5,3.5),(-5.5,-8,3.5),
      (-4.5,-8,1),(-3.1,-7.1,-2)]),
]


def rounded_wire(m, points, radius=1.5):
    """局部圆弧过渡保持路径通道；不使用会越过障碍的整条样条拟合。"""
    V, cq = m.V, m.cq
    p = [V(*v) for v in points]
    edges, start = [], p[0]
    for a, b, c in zip(p, p[1:], p[2:]):
        d1, d2 = (b-a).normalized(), (c-b).normalized()
        angle = math.acos(max(-1., min(1., d1.dot(d2))))
        if angle < 1e-5:
            continue
        distance = min(radius*math.tan(angle/2), (b-a).Length*.30, (c-b).Length*.30)
        actual_radius = distance/math.tan(angle/2)
        entry, exit = b-d1*distance, b+d2*distance
        centre = b+(-d1+d2).normalized()*(distance/math.sin(angle/2))
        mid = centre+(b-centre).normalized()*actual_radius
        if (entry-start).Length > 1e-6:
            edges.append(cq.Edge.makeLine(start, entry))
        edges.append(cq.Edge.makeThreePointArc(entry, mid, exit))
        start = exit
    if (p[-1]-start).Length > 1e-6:
        edges.append(cq.Edge.makeLine(start, p[-1]))
    return cq.Wire.assembleEdges(edges)


def tube(m, points, radius, bend=1.5):
    path = rounded_wire(m, points, bend)
    plane = m.cq.Plane(origin=path.startPoint(), normal=path.Edges()[0].tangentAt(0))
    return m.cq.Workplane(plane).circle(radius).sweep(path, isFrenet=True).val(), path.Length()


def solder(m, x, z, radius=.90, face=None, direction=1):
    face = m.TOP if face is None else face
    return m.cq.Solid.makeCone(radius, .32, .6, m.V(x,face,z), m.V(0,direction,0))


def assembled_details(m, refs):
    """返回实装形体、材质和线长；芯片小件及软线弯曲为名义外形。"""
    r = dict(refs)
    colors = dict(DETAIL_COLORS)
    def put(name, shape, rgb):
        r[name], colors[name] = shape, rgb
    def compound(shapes):
        return m.cq.Compound.makeCompound(shapes)
    silver, black, gold = (.69,.71,.73), (.06,.065,.07), (.77,.61,.20)
    for name in list(r):
        if "留空" in name or name in {"开发板元件","USB接口","陀螺仪元件",
                                     "开发板排针","陀螺仪排针","SW1-五针示意",
                                     "SW1-金属本体","SS金属扳机本体","SS金属摆杆示意"}:
            r.pop(name)
        elif any(name.startswith(p["ref"]+"-") for p in m.C["parts"]
                 if p["kind"] in {"wirebank","resistor","capacitor","power_switch","microswitch"}):
            r.pop(name)

    # 54个官方器件实体取代开发板大盒；板孔按当前15.24毫米两排孔建。
    r.update(official_mcu_shapes(m))
    r.update(gy_photo_shapes(m))
    board = refs["开发板"]
    for pad in next(p for p in m.C["parts"] if p["ref"]=="J_MCU")["pads"]:
        board = board.cut(m.cy(*pad["xz"], .65, -8, -6.1))
    put("开发板", board, (.035,.04,.045))
    for ref, label, back_y in [("J_MCU","开发板",m.FACE_Y_SUM-m.SM[3]),
                                ("J_GY","陀螺仪",m.FACE_Y_SUM-m.GY[3])]:
        p = next(p for p in m.C["parts"] if p["ref"]==ref)
        pins, spacers, joints = [], [], []
        for pad in p["pads"]:
            x,z = pad["xz"]
            pins.append(m.box(x-.32,x+.32,back_y-.6,m.TOP+.8,z-.32,z+.32))
            spacers.append(m.box(x-1.15,x+1.15,-6.13,-3.43,z-1.15,z+1.15))
            joints += [solder(m,x,z), solder(m,x,z,.85,back_y,-1)]
        put(label+"-双排直插针", compound(pins), gold)
        put(label+"-排针绝缘座", compound(spacers), black)
        put(label+"-上下焊点", compound(joints), silver)

    # 少量手焊电阻、电容，金属脚穿过真实板孔；保留八颗的现有电路。
    for p in m.C["parts"]:
        if p["kind"] not in {"resistor","capacitor"} or not p.get("populate",True):
            continue
        x,z = p["position_xz"]
        leads=[]
        if p["kind"]=="resistor":
            put(p["ref"]+"-电阻本体",m.cx(m.BACK-1.35,z,1.15,x-3.2,x+3.2),(.20,.45,.62))
            for pad in p["pads"]:
                px,pz=pad["xz"]
                inner=x+math.copysign(2.8,px-x)
                lead,_=tube(m,[(inner,m.BACK-1.35,z),(px,m.BACK-1.35,z),
                               (px,m.TOP+.8,pz)],.25,.35)
                leads.append(lead)
        else:
            put(p["ref"]+"-陶瓷电容",m.cz(x,m.BACK-4,2.7,z-.75,z+.75),(.69,.37,.15))
            for pad in p["pads"]:
                px,pz=pad["xz"]
                leads.append(m.cy(px,pz,.25,m.BACK-4,m.TOP+.8))
        put(p["ref"]+"-金属脚",compound(leads),silver)
        put(p["ref"]+"-焊点",compound([solder(m,*pad["xz"],1.05) for pad in p["pads"]]),silver)

    # 原生右键壳、压头与扁引脚分离。
    p=next(p for p in m.C["parts"] if p["ref"]=="SW2")
    put("右键-黑色外壳",m.box(-39.4,-26.6,m.BACK-6.5,m.BACK,-4.9,.9),black)
    put("右键-原生按钮",m.box(-31.65,-30.45,m.BACK-7.45,m.BACK-6.5,-3.45,-.55),(.82,.82,.78))
    put("右键-扁脚",compound([m.box(q["xz"][0]-.6,q["xz"][0]+.6,m.BACK-.1,m.TOP+.8,
                                      q["xz"][1]-.2,q["xz"][1]+.2) for q in p["pads"]]),silver)
    put("右键-焊点",compound([solder(m,*q["xz"],.70) for q in p["pads"]]),silver)

    p=next(p for p in m.C["parts"] if p["ref"]=="J_SWITCH")
    put("电源开关-绝缘座",m.box(-47.85,-35.15,m.BACK-6.4,m.BACK,-41.6,-35.0),black)
    # 薄金属壳，留出拨柄中央槽。
    case=m.box(-47.95,-35.05,m.BACK-6.55,m.BACK-6.25,-41.7,-34.9)
    case=case.cut(m.box(-45.1,-37.9,m.BACK-6.7,m.BACK-6.1,-40.3,-36.3))
    put("电源开关-金属盖",case,silver)
    put("电源开关-拨柄",m.box(-44.9,-41.0,m.BACK-11.55,m.BACK-6.3,-40.2,-36.4),black)
    put("电源开关-三扁脚",compound([m.box(q["xz"][0]-.65,q["xz"][0]+.65,m.BACK,m.TOP+.8,
                                           q["xz"][1]-.4,q["xz"][1]+.4) for q in p["pads"]]),silver)
    put("电源开关-焊点",compound([solder(m,*q["xz"],1.3) for q in p["pads"]]),silver)

    # 水平HW504：板在Z=6.2以上，排针Z=5水平进入，随后90度上折穿黑板。
    x=m.JOY_AXIS[0]; y=m.FACE_Y_SUM-m.JOY_AXIS[1]; floor=m.JOY_BOARD[5]
    cage=m.box(x-9.8,x+9.8,y-9.8,y+9.8,floor,floor+11)
    cage=cage.cut(m.box(x-8.8,x+8.8,y-8.8,y+8.8,floor-.1,floor+10))
    cage=cage.cut(m.cz(x,y,5.6,floor+9.5,floor+11.1))
    put("摇杆-金属框架",cage,silver)
    put("摇杆-双轴电位器",compound([m.box(x-11.5,x-8.8,y-6,y+6,floor+.3,floor+9.5),
                                         m.box(x-6,x+6,y+8.8,y+11.5,floor+.3,floor+9.5)]),(.13,.42,.28))
    put("摇杆-按下微动",m.box(x+7,x+12,y-9,y-3,floor+.1,floor+3.5),(.48,.50,.51))
    b=r["SW1-模块黑板"]
    bends, joints, rings=[],[],[]
    for q in m.JOYSTICK["pads"]:
        px,pz=q["xz"]
        hy=1.44
        b=b.cut(m.cz(px,hy,.55,m.JOY_BOARD[4]-.1,floor+.1))
        metal,_=tube(m,[(px,m.BACK-.8,pz),(px,hy,pz),(px,hy,floor+.65)],.32,.6)
        bends.append(metal)
        joints.append(solder(m,px,pz,.8,face=m.BACK,direction=-1))
        joints.append(m.cq.Solid.makeCone(.85,.32,.5,m.V(px,hy,floor),m.V(0,0,1)))
        rings.append(m.cz(px,hy,.95,floor+.005,floor+.04).cut(m.cz(px,hy,.55,floor-.01,floor+.05)))
    put("SW1-模块黑板",b,black)
    put("摇杆-五根弯排针",compound(bends),gold)
    put("摇杆-排针塑料条",m.box(-40.05,-27.35,-.5,1.1,3.9,6.1),black)
    put("摇杆-五针铜圈",compound(rings),gold)
    put("摇杆-五针焊点",compound(joints),silver)

    # SS外壳与金属焊耳分开；金属摆杆接回本体铰链，避免旧示意图悬空。
    case=m.box(-17.1,-7.6,-8.06,-1.66,-19.221,.579)
    for hx,hz in m.SS_HOLES:
        case=case.cut(m.cy(hx,hz,1.175,-8.2,-1.5))
    put("扳机-SS黑色壳",case,black)
    tabs=[]
    for off in (1.6,10.4,17.7):
        zz=.579-off
        tab=m.box(-20.6,-17.09,-6.46,-3.26,zz-.25,zz+.25)
        tab=tab.cut(m.cz(-19.1,-4.86,.8,zz-.4,zz+.4))
        tabs.append(tab)
    put("扳机-COM_NO_NC焊耳",compound(tabs),silver)
    # 沿自由端逐渐抬离壳体的钢片；摆杆外形属名义参考，保持原操作区。
    lever=m.prism([(-7.65,-.2),(-7.35,-.2),(-3.3,-19.5),(-3.6,-19.5)],-6.66,-3.06)
    put("扳机-金属摆杆",lever,silver)
    put("扳机-铰链",m.cy(-7.65,-.2,.8,-6.8,-2.9),silver)
    # 与钢片分离的绝缘铜箔贴面，铰链侧引线尾从侧边伸出。
    def outside_x(zz):
        return -7.35+(-zz-.2)*4.05/19.3
    top,bottom=-3.,-17.5
    foil_base=m.prism([(outside_x(top)+.02,top),(outside_x(top)+.17,top),
                        (outside_x(bottom)+.17,bottom),(outside_x(bottom)+.02,bottom)],-8.,-2.9)
    put("触摸-底层绝缘胶带",foil_base,(.70,.44,.08))
    top,bottom=-3.2,-17.1
    foil=m.prism([(outside_x(top)+.18,top),(outside_x(top)+.23,top),
                  (outside_x(bottom)+.23,bottom),(outside_x(bottom)+.18,bottom)],-6.65,-3.05)
    put("触摸-铜箔电极",foil,(.80,.42,.16))
    tail=m.box(-6.48,-6.43,-8.,-5.7,-3.6,-3.2)
    put("触摸-铜箔焊线尾",tail,(.80,.42,.16))
    put("触摸-表层绝缘胶带",foil.translate((.07,0,0)),(.73,.49,.14))

    # 602060电芯与保护/出线余量分段表示，仍在20x80x8的已接受包络内。
    r.pop("电池",None)
    cell=m.box(-47.7,-27.7,4.84,10.84,-112,-52)
    put("电池-602060软包",m.cq.Workplane().add(cell).edges("|Z").fillet(.7).val(),(.72,.74,.77))
    put("电池-保护端绝缘包",m.box(-47.5,-27.9,3.94,11.74,-52,-32),(.78,.57,.14))
    # 两条软带跨过侧梁而不是勒在软电芯上，侧窗口穿回底面。
    for zz in (-98,-57):
        outer=m.box(-50.8,-24.6,2.9,14.85,zz-1.6,zz+1.6)
        inner=m.box(-50.55,-24.85,3.25,14.5,zz-1.7,zz+1.7)
        put(f"电池-软绑带{abs(zz)}",outer.cut(inner),(.07,.075,.08))

    # 七线为建议实装路径，端点按当前孔表；模块B焊盘/铜箔尾位置为图比值。
    routes=[]
    wirecolors={"红线":(.68,.035,.025),"黑线":(.025,.027,.03),
                "蓝线":(.035,.18,.65),"黄线":(.91,.68,.025)}
    for name,net,color,ins_r,core_r,raw_points in WIRE_ROUTES:
        points=list(raw_points)
        if name=="触摸铜箔线":
            points[-1]=(-6.45,-7.8,-3.4)
        core,length=tube(m,points,core_r)
        # 板端露铜3.1毫米，另一端露铜0.8毫米；避免绝缘层穿过电路板。
        def strip_end(path, distance):
            path=list(path)
            while len(path)>2:
                a,b=m.V(*path[0]),m.V(*path[1])
                length=(b-a).Length
                if length>distance:
                    break
                distance-=length
                path.pop(0)
            a,b=m.V(*path[0]),m.V(*path[1])
            path[0]=(a+(b-a).normalized()*distance).toTuple()
            return path
        trimmed=strip_end(points,3.1)
        trimmed=list(reversed(strip_end(list(reversed(trimmed)),.8)))
        insulated,_=tube(m,trimmed,ins_r)
        put(name+"-铜芯",core,(.72,.39,.16))
        put(name+"-绝缘皮",insulated,wirecolors[color])
        px,_,pz=points[0]
        put(name+"-载板焊点",solder(m,px,pz,.80),silver)
        end=m.cq.Solid.makeSphere(.4 if name=="触摸铜箔线" else .65,m.V(*points[-1]))
        put(name+"-另一端焊锡",end,silver)
        routes.append({"name":name,"net":net,"centreline_length_mm":round(length,2),
                       "insulation_diameter_mm":2*ins_r,"endpoints_xyz_mm":[points[0],points[-1]],
                       "path_xyz_mm":points})
    # 实际B+/B-背面铜焊盘，无额外接线端子。
    for zz in (21.2,24.7):
        put(f"开发板-电池背焊盘{zz}",m.box(-12.7,-10.7,-6.24,-6.18,zz-.75,zz+.75),gold)
    return r,colors,routes
