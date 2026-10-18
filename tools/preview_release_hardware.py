"""定版装配的扳机螺丝；不改早期名义底座和硬件生成器。"""

TRIGGER_NUT_Y = (-11.06, -9.46)
TRIGGER_NUT_POCKET_Y = (-11.26, -9.36)
TRIGGER_SUPPORT_FACE_Y = -8.06
TRIGGER_SCREW_LENGTH = 10.0
TRIGGER_SCREW_SEAT_Y = -1.66
TRIGGER_SCREW_TIP_Y = TRIGGER_SCREW_SEAT_Y - TRIGGER_SCREW_LENGTH


def release_hardware(m):
    """扳机两颗M2×10直接夹壳体与背座，不加垫片，槽前保留1.3毫米前壁。"""
    refs = {}
    for i, (x, z) in enumerate(m.SS_HOLES, 1):
        name = f"SS{i}"
        head = m.cy(x, z, 2, TRIGGER_SCREW_SEAT_Y,
                    TRIGGER_SCREW_SEAT_Y+2.1).cut(
            m.hex_y(x, z, 1.5, TRIGGER_SCREW_SEAT_Y+.9,
                    TRIGGER_SCREW_SEAT_Y+2.21))
        refs[name+"-螺钉"] = head.fuse(
            m.cy(x, z, 1, TRIGGER_SCREW_TIP_Y, TRIGGER_SCREW_SEAT_Y))
        refs[name+"-螺母"] = m.hex_y(x, z, 4, *TRIGGER_NUT_Y).cut(
            m.cy(x, z, 1.05, TRIGGER_NUT_Y[0]-.1, TRIGGER_NUT_Y[1]+.1))
    return refs
