"""快速预览用 SS-01 右键双螺丝支架；只返回实体，不写出文件。"""

from preview_ss01_right import MOUNT_HOLES


def move_right_button_cradle(m, base):
    """两颗 M2×10 穿过 SS-01 原侧孔，背面普通 M2 螺母从 +X 滑入。"""
    holes = MOUNT_HOLES
    # 背板只接触开关后侧，+X 直压头和 -X 三端子均保持敞开。
    additions = [
        m.beam(holes[0], holes[1], 4.0, -15.8, -14.0),
        m.beam((-27, -27), holes[0], 4.5, m.BASE[0], -14.0),
    ]
    for x, z in holes:
        additions.append(m.cy(x, z, 3.4, -18.4, -14.0))
    result = m.fuse([base, *additions])
    cuts = [
        m.cx(-10.8, -31, 5, -7.5, 8),
        m.cy(-27, -27, 1.2, -21, m.BACK + .2),
    ]
    for x, z in holes:
        cuts.append(m.cy(x, z, 1.2, -18.3, -13.9))
        # 对边 4 毫米的普通 M2 螺母横向推入，内端留 0.2 毫米杆端余量。
        cuts.append(m.box(x-2.35, x+4.0, -17.5, -15.7, z-2.1, z+2.1))
    for cut in cuts:
        result = result.cut(cut)
    return result.clean()
