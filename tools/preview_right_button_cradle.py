"""快速预览用 SS-01 右键双螺丝支架；只返回实体，不写出文件。"""

from preview_ss01_right import MOUNT_HOLES, NUT_POCKET_Y, BLIND_END_Y
from gen2_component_details import WIRE_ROUTES, tube


def move_right_button_cradle(m, base):
    """两颗 M2×10 穿过 SS-01 原侧孔，背面普通 M2 螺母从 +X 滑入。"""
    holes = MOUNT_HOLES
    # 连续背板直接接入原扳机背座和 H4，不依赖外侧折线细梁。
    # 螺母向开关侧靠近0.4毫米：夹持塑料1.3毫米，M2×10穿出螺母0.7毫米。
    additions = [
        m.box(-29.0, -10.8, m.BASE[0], -14.0, -42.9, -1.1),
    ]
    result = m.fuse([base, *additions])
    cuts = [
        m.cx(-10.8, -31, 5, -7.5, 8),
        m.cy(-27, -27, 1.2, -21, m.BACK + .2),
    ]
    for x, z in holes:
        cuts.append(m.cy(x, z, 1.2, BLIND_END_Y, -13.9))
        # 对边4毫米的普通M2螺母由+X推入，槽厚1.8毫米含0.2毫米装配余量。
        cuts.append(m.box(x-2.35, -10.7, *NUT_POCKET_Y, z-2.1, z+2.1))
    # 九条焊线中只有黄色触摸线穿过这块背板；圆底开口槽按现有路径避让。
    points = list(next(r[-1] for r in WIRE_ROUTES if r[0] == "触摸铜箔线"))
    points[-1] = (-6.45, -7.8, -3.4)
    wire_slot, _ = tube(m, points, .8)
    cuts.append(wire_slot)
    for cut in cuts:
        result = result.cut(cut)
    return result.clean()
