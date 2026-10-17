"""摇杆支座根部直接穿板固定，省去远端锚座和绕行长梁。"""

LOCAL_HOLES = [(-39.4, -4.4), (-30.5, -6.2)]


def local_support(m):
    # 横托靠近小板背面；两端承托面、各孔位和螺钉承压面不动。
    y0, y1 = m.JOY_NEAR_Y-3.6, m.JOY_NEAR_Y+3.6
    pieces = [m.box(-47.05, -20.35, y0, y1, -5.8, 1.1),
              m.box(-43.1, -26.8, m.TOP, m.JOY_ARM_Y[1], -9.9, -.7)]
    for x, old_y in m.JOY_MOUNT_HOLES:
        pieces.append(m.box(x-3.6, x+3.6, y0, y1, 1.1, m.JOY_BOARD[4]))
    result = m.fuse(pieces)
    # 五针已焊短脚共用一个开口浅槽，避免形成针孔间过薄的小隔片。
    pins = [pad["xz"][0] for pad in m.JOYSTICK["pads"]]
    result = result.cut(m.box(min(pins)-1.4, max(pins)+1.4,
                              .04, 2.84, .6, m.JOY_BOARD[4]+.1))
    # 矩形根部的背面凹槽避开电阻剪脚、右键焊点和短线。
    resistor = next(p for p in m.C["parts"] if p["ref"] == "R_TRIG")
    for pad in resistor["pads"]:
        result = result.cut(m.cy(*pad["xz"], 1.55, m.TOP-.1, .3))
    for x in (-33, -27.92):
        result = result.cut(m.cy(x, -2, 1.3, m.TOP-.1, .3))
    for i, (x, old_y) in enumerate(m.JOY_MOUNT_HOLES):
        y = m.FACE_Y_SUM-old_y
        result = result.cut(m.cz(x, y, 2.15, -10, -3.8))
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
        result = result.cut(m.cy(x, z, 2.2, 4.6, y1+.1))
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
