"""摇杆支座根部直接穿板固定，省去远端锚座和绕行长梁。"""

LOCAL_HOLES = [(-39.4, -4.4), (-30.5, -6.2)]


def local_support(m):
    # 不改变承托高度和螺钉承压面；扩大穿板孔座并连成宽底板。
    pieces = [m.box(-46.85, -20.55, *m.JOY_ARM_Y, -5.8, -2.2)]
    for x, old_y in m.JOY_MOUNT_HOLES:
        pieces.append(m.cz(x, m.FACE_Y_SUM-old_y, 3.6, -5.8, m.JOY_BOARD[4]))
    web = m.fuse([
        m.box(-39.4, -30.5, m.TOP, m.JOY_ARM_Y[1], -7.8, -3.1),
        *[m.cy(x, z, 3.7, m.TOP, m.JOY_ARM_Y[1]) for x, z in LOCAL_HOLES],
    ])
    # 侧轮廓圆角延续到整个板厚，不削薄沉孔口。
    web = m.cq.Workplane().add(web).edges("|Y").fillet(.8).val()
    pieces.append(web)
    # 短筋只在两端承托柱根部；中间五针和焊点下方保持敞开。
    for x, old_y in m.JOY_MOUNT_HOLES:
        y = m.FACE_Y_SUM-old_y
        inward = 1 if x < -33.7 else -1
        rib = m.prism([(x, -3.0), (x+inward*5.8, -3.0),
                       (x, .8)], y-1.8, y+1.8)
        rib = m.cq.Workplane().add(rib).edges("|Y").fillet(.8).val()
        pieces.append(rib)
    result = m.fuse(pieces)
    # 加宽底板靠近R_TRIG剪脚，背面留局部焊点凹槽，不改变主板孔。
    resistor = next(p for p in m.C["parts"] if p["ref"] == "R_TRIG")
    for pad in resistor["pads"]:
        result = result.cut(m.cy(*pad["xz"], 1.55, m.TOP-.1, .3))
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
