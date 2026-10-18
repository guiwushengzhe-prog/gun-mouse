"""快速预览：去掉上部框架，主体仅保留下部三个穿板固定点。"""

from preview_layout import BODY_MOUNT_HOLE
from preview_release_hardware import TRIGGER_NUT_POCKET_Y, TRIGGER_SUPPORT_FACE_Y


def outer_cover(m):
    """规整的薄护板：直边主体、圆角收肩，不侵占内部走线空间。"""
    outline = [(-54.5, -.8), (-10.8, -.8), (-10.8, -42.9),
               (-24.9, -49), (-24.9, -52), (-50.5, -52),
               (-50.5, -49), (-54.5, -42.5)]
    plate = m.prism(outline, m.BATTERY_FLOOR_Y, m.BASE[1])
    # 收肩用较大圆角，主体外角用小圆角；不滚圆打印接触面。
    shoulders = [e for e in plate.Edges() if e.geomType() == "LINE"
                 and abs(e.tangentAt().y) > .99
                 and any(abs(e.Center().z-z) < .001 for z in (-42.9, -42.5, -49))]
    plate = m.cq.Workplane().add(plate).newObject(shoulders).fillet(1.5).val()
    corners = [e for e in plate.Edges() if e.geomType() == "LINE"
               and abs(e.tangentAt().y) > .99
               and any(abs(e.Center().z-z) < .001 for z in (-.8, -52))]
    return m.cq.Workplane().add(plate).newObject(corners).fillet(1.0).val()


def reshape_frame(m, base):
    """去掉H1/H2上部支承；H3/H4与新增H5承接下部主体。"""
    # 原中横筋、上横框与MCU外侧长梁全部删除，不再换成另一根梁。
    old = [
        m.beam((-12, 36), (-12, 45), 3.6),
        m.beam((-12, 36), (-15, 0), 3.6),
        m.beam((-15, 0), (-27, -27), 3.6),
        m.beam((-51, -4), (m.JOY_MOUNT_HOLES[0][0], 0), 3.6),
        m.beam((m.JOY_MOUNT_HOLES[0][0], 0), (-15, 0), 3.6),
        m.beam((-56, 45), (-12, 45), 3.6, -6.8, -3.8),
        m.beam((-56, 36), (-58, 45), 3.6, -6.8, -3.8),
        m.beam((-58, 45), (-56, 45), 3.6, -6.8, -3.8),
        m.box(-13.8, -10.2, m.BASE[0], -3.8, 43.2, 46.8),
        m.cy(-12, 36, 3.2, m.BASE[0], m.BACK),
        m.cy(-56, 36, 3.2, m.SHORT_POST_Y, m.BACK),
        # 该上伸筋原本连到已删除的外侧长梁，SS下根筋仍保留。
        m.beam((-14.2, -5), (-12, 12), 4.5),
    ]
    result = base.cut(m.fuse(old))
    x5, z5 = BODY_MOUNT_HOLE
    additions = [
        # 恢复与旧梁相交的下部支承，保留护板、电池托和SS背座。
        m.beam((-51, -4), (-27, -27), 3.6),
        m.box(-17.6, -10.8, -17.2, TRIGGER_SUPPORT_FACE_Y, -17.4, -1.1),
        m.beam((-14.2, -14), (-27, -27), 4.5),
        m.cy(x5, z5, 3.2, m.BASE[0], m.BACK),
        m.beam((x5, z5), (x5, -31), 4.0),
        # H3周围凹折角和左侧短台阶统一补平，再圆滑收至电池托。
        # 仅补2.4毫米薄护板，电池引线仍从内侧空腔通过。
        outer_cover(m),
    ]
    for x, z in m.SS_HOLES:
        additions.append(m.cy(x, z, 3.4, -17.2, TRIGGER_SUPPORT_FACE_Y))
    for hole in m.P["mount_holes"]:
        if hole["id"] not in {"H3", "H4"}:
            continue
        x, z = hole["xz"]
        additions.append(m.cy(x, z, 3.2, m.BASE[0], m.BACK))
    result = m.fuse([result, *additions])

    cuts = [m.cy(x5, z5, 1.2, -21, m.BACK+.2),
            m.cy(x5, z5, 2.2, -24, m.BASE[0])]
    for hole in m.P["mount_holes"]:
        if hole["id"] not in {"H3", "H4"}:
            continue
        x, z = hole["xz"]
        cuts.append(m.cy(x, z, 1.2, -21, m.BACK + .2))
    # 重建SS背座时同步恢复原孔、侧面螺母槽和工具入口。
    for x, z in m.SS_HOLES:
        cuts += [m.cy(x, z, 1.15, -17.3, TRIGGER_SUPPORT_FACE_Y+.1),
                 # 支座直接托住开关，M2×10无垫片；槽前承力壁保留1.3毫米。
                 m.box(-21, -11.7, *TRIGGER_NUT_POCKET_Y, z-2.15, z+2.15),
                 m.cy(x, z, 2.2, -1.5, .95)]
    cuts.append(m.cy(-27, -27, 2.2, -21, m.BASE[0]))
    for cut in cuts:
        result = result.cut(cut)
    return result.clean()


def level_outer_face(m, base):
    """外表面统一到电池托底面；内腔、螺钉承压面和孔位保持原位。"""
    extra = m.BASE[0] - m.BATTERY_FLOOR_Y
    # 沿原外形向外补0.5毫米，保留原有开窗与外轮廓，不填充内腔。
    skin = base.translate((0, -extra, 0)).intersect(
        m.box(-100, 100, m.BATTERY_FLOOR_Y, m.BASE[0]+.01, -200, 100))
    result = m.fuse([base, skin])
    # 清除旧拼接块伸出规整轮廓的薄边；内腔与深支承保持原形。
    outer_layer = m.box(-100, 100, m.BATTERY_FLOOR_Y, m.BASE[1], -50, 0)
    result = result.cut(outer_layer.cut(outer_cover(m)))
    holes = [h["xz"] for h in m.P["mount_holes"] if h["id"] in {"H3", "H4"}]
    for x, z in [*holes, BODY_MOUNT_HOLE]:
        # 螺丝头在新表面内浅沉0.5毫米，螺杆有效长度仍与上一版相同。
        result = result.cut(m.cy(x, z, 2.2, -24, m.BASE[0]))
    return result.clean()
