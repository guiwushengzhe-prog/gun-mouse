"""快速预览：去掉上部框架，主体仅保留下部三个穿板固定点。"""

from preview_layout import BODY_MOUNT_HOLE


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
        m.box(-17.6, -10.8, -17.2, -8.66, -17.4, -1.1),
        m.beam((-14.2, -14), (-27, -27), 4.5),
        m.cy(x5, z5, 3.2, m.BASE[0], m.BACK),
        m.beam((x5, z5), (x5, -31), 4.0),
        # 原开关窗口封成连续护板；1.9毫米厚度沿用上方护板。
        # 电池引线在内侧空腔通过，H5穿孔在下方统一重新切出。
        m.box(-50.5, -24.9, *m.BASE, -42.9, -33.8),
    ]
    for x, z in m.SS_HOLES:
        additions.append(m.cy(x, z, 3.4, -17.2, -8.66))
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
        cuts += [m.cy(x, z, 1.15, -17.3, -8.5),
                 # 螺母位置不变，仅收回槽前壁0.1毫米，薄壁由0.79增至0.89。
                 m.box(-21, -11.7, -11.45, -9.55, z-2.15, z+2.15),
                 m.cy(x, z, 2.2, -1.5, .95)]
    cuts.append(m.cy(-27, -27, 2.2, -21, m.BASE[0]))
    for cut in cuts:
        result = result.cut(cut)
    return result.clean()
