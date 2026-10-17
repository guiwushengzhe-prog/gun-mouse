"""摇杆支座根部直接穿板固定，省去远端锚座和绕行长梁。"""

LOCAL_HOLES = [(-39.4, -4.4), (-30.5, -6.2)]


def local_support(m):
    # 横条恢复原3.6毫米高度；仅在穿板孔周围保留局部圆柱。
    pieces = [m.box(-46.85, -20.55, *m.JOY_ARM_Y, -5.8, -2.2)]
    for x, old_y in m.JOY_MOUNT_HOLES:
        pieces.append(m.cz(x, m.FACE_Y_SUM-old_y, 3.4, -5.8, m.JOY_BOARD[4]))
    for x, z in LOCAL_HOLES:
        pieces.append(m.cy(x, z, 2.6, m.TOP, m.JOY_ARM_Y[1]))
    result = m.fuse(pieces)
    for i, (x, old_y) in enumerate(m.JOY_MOUNT_HOLES):
        y = m.FACE_Y_SUM-old_y
        result = result.cut(m.cz(x, y, 2.15, -8.9, -3.8))
        if i == 0:
            result = result.cut(m.cz(x, y, 1.2, -6.0, m.JOY_BOARD[4]+.1))
        else:
            result = result.cut(m.fuse([
                m.cz(x-.6, y, 1.2, -6, m.JOY_BOARD[4]+.1),
                m.cz(x+.6, y, 1.2, -6, m.JOY_BOARD[4]+.1),
                m.box(x-.6, x+.6, y-1.2, y+1.2, -6, m.JOY_BOARD[4]+.1),
            ]))
    for x, z in LOCAL_HOLES:
        result = result.cut(m.cy(x, z, 1.2, m.TOP-.1, m.JOY_ARM_Y[1]+.1))
        # M2×10螺钉头下沉1.04毫米，穿过塑料和板后可完整咬合普通螺母。
        result = result.cut(m.cy(x, z, 2.2, 4.6, 7.4))
    return result.clean()


def local_hardware(m):
    result = {}
    for i, (x, z) in enumerate(LOCAL_HOLES, 1):
        name = f"摇杆就近固定{i}"
        head = m.cy(x, z, 2, 4.6, 6.7).cut(m.hex_y(x, z, 1.5, 5.6, 6.8))
        result[name+"-螺钉"] = head.fuse(m.cy(x, z, 1, -5.4, 4.6))
        result[name+"-螺母"] = m.hex_y(x, z, 4, m.BACK-1.6, m.BACK).cut(
            m.cy(x, z, 1.05, m.BACK-1.7, m.BACK+.1))
    return result
