"""由连续护板、规则直柱和电池托构成主体，不继承早期切削碎片。"""
from preview_straight_frame import outer_cover
from preview_layout import BODY_MOUNT_HOLES, SHARED_SCREW_SEAT_Y
from preview_release_hardware import TRIGGER_SUPPORT_FACE_Y, TRIGGER_NUT_POCKET_Y
from preview_ss01_right import MOUNT_HOLES, NUT_POCKET_Y, BLIND_END_Y


def round_block(m, bounds, radius=.6, axis="Y"):
    return m.cq.Workplane().add(m.box(*bounds)).edges("|"+axis).fillet(radius).val()


def root_ramp(m, x0, x1):
    profile = [(m.BATTERY_FLOOR_Y, -53), (-8.2, -53),
               (m.BACK, -38), (m.BATTERY_FLOOR_Y, -34.8)]
    wire = m.cq.Wire.makePolygon([m.V(x0, y, z) for y, z in profile], close=True)
    ramp = m.cq.Solid.extrudeLinear(m.cq.Face.makeFromWires(wire), m.V(x1-x0, 0, 0))
    return m.cq.Workplane().add(ramp).edges("|X").fillet(.8).val()


def build_body(m):
    floor = m.BATTERY_FLOOR_Y
    parts = [outer_cover(m),
             round_block(m, (-50.5, -24.9, floor, m.BASE[1], -125.8, -42.9), .8),
             # 电池托底挡与侧壁齐高，直接接底板，取消原多层窄台阶。
             m.box(-50.5, -24.9, floor, -8.2, -125.8, -124.3),
             m.box(-29, -10.8, floor, -14.0, -42.9, -1.1),
             # 两个开关均由方正直壁承托，保留原安装面与螺母位置。
             round_block(m, (-17.6, -10.8, floor, TRIGGER_SUPPORT_FACE_Y, -17.5, -1.1), .6),
             root_ramp(m, -50.5, -48.2), root_ramp(m, -27.2, -24.9)]
    for x0, x1 in ((-50.5, -48.2), (-27.2, -24.9)):
        parts.append(round_block(m, (x0, x1, floor, -8.2, -125.8, -42.9), .5, "Z"))
    for x, z in BODY_MOUNT_HOLES.values():
        parts.append(round_block(m, (x-3.2, x+3.2, floor, m.BACK, z-3.2, z+3.2), .6))
    result = m.fuse(parts)
    cuts = []
    for name, (x, z) in BODY_MOUNT_HOLES.items():
        seat = SHARED_SCREW_SEAT_Y if name == "H3" else m.BASE[0]
        cuts += [m.cy(x, z, 1.2, floor-.1, m.BACK+.1), m.cy(x, z, 2.2, -24, seat)]
    for x, z in m.SS_HOLES:
        cuts += [m.cy(x, z, 1.15, -14.0, TRIGGER_SUPPORT_FACE_Y+.1),
                 m.box(-21, -11.7, *TRIGGER_NUT_POCKET_Y, z-2.15, z+2.15)]
    for x, z in MOUNT_HOLES:
        cuts += [m.cy(x, z, 1.2, BLIND_END_Y, -13.9),
                 m.box(x-2.35, -10.7, *NUT_POCKET_Y, z-2.1, z+2.1)]
    for x0, x1 in ((-47.2, -40.4), (-35, -28.2)):
        for z0, z1 in ((-121.3, -113.2), (-106.8, -95), (-92.6, -80.8), (-78.4, -72.2), (-65.8, -53.2)):
            cuts.append(round_block(m, (x0, x1, floor-.1, -16.7, z0, z1), .8))
    # 两组软绑带的必要通道：规则圆角长孔，不增加多余侧窗。
    for z in (-110, -69):
        for x0, x1 in ((-50.6, -48.1), (-27.3, -24.8)):
            cuts.append(round_block(m, (x0, x1, -17.2, -14.4, z-2, z+2), .6, "X"))
    for cut in cuts:
        result = result.cut(cut)
    return result.clean()
