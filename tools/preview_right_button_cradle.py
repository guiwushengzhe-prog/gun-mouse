"""快速预览用 SS-01 右键双螺丝支架；只返回实体，不写出文件。"""

from preview_ss01_right import MOUNT_HOLES
from gen2_component_details import WIRE_ROUTES, tube


def move_right_button_cradle(m, base):
    """两颗 M2×10 穿过 SS-01 原侧孔，背面普通 M2 螺母从 +X 滑入。"""
    holes = MOUNT_HOLES
    # 连续背板直接接入原扳机背座和 H4，不依赖外侧折线细梁。
    # 两螺母前面仍只夹 1.7 毫米塑料，M2×10 的有效长度不变。
    additions = [
        m.box(-29.0, -10.8, m.BASE[0], -14.0, -42.9, -1.1),
    ]
    result = m.fuse([base, *additions])
    cuts = [
        m.cx(-10.8, -31, 5, -7.5, 8),
        m.cy(-27, -27, 1.2, -21, m.BACK + .2),
    ]
    for x, z in holes:
        cuts.append(m.cy(x, z, 1.2, -18.3, -13.9))
        # 对边 4 毫米的普通 M2 螺母横向推入，内端留 0.2 毫米杆端余量。
        cuts.append(m.box(x-2.35, -10.7, -17.5, -15.7, z-2.1, z+2.1))
    # 九条焊线中只有黄色触摸线穿过这块背板；圆底开口槽按现有路径避让。
    points = list(next(r[-1] for r in WIRE_ROUTES if r[0] == "触摸铜箔线"))
    points[-1] = (-6.45, -7.8, -3.4)
    wire_slot, _ = tube(m, points, .8)
    cuts.append(wire_slot)
    for cut in cuts:
        result = result.cut(cut)
    return result.clean()
