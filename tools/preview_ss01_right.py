"""SS-01 直压右键的名义装配外形，单位毫米。

采用用户提供的尺寸图：主壳 19.8×6.4×9.5，局部高 10.2；
侧面安装孔直径 2.35、中心距 9.5，沿 Y 贯穿。
直压头高度、壳体小台阶轮廓及端子外缘是外观近似，不是原厂扫描模型。
"""

BODY_BOUNDS = (-18.5, -9.0, -14.0, -7.6, -43.7, -23.9)
MOUNT_HOLES = ((-15.6, -29.0), (-15.6, -38.5))
PLUNGER_CENTER = (-7.9, -10.8, -31.0)


def right_hardware(m):
    """两颗M2×10直接穿开关，普通M2螺母坐入背侧支架的侧向螺母槽。"""
    refs = {}
    for i, (x, z) in enumerate(MOUNT_HOLES, 1):
        name = f"右键固定{i}"
        head = m.cy(x, z, 2, -7.6, -5.5).cut(
            m.hex_y(x, z, 1.5, -6.6, -5.4))
        refs[name+"-螺钉"] = head.fuse(m.cy(x, z, 1, -17.6, -7.6))
        refs[name+"-螺母"] = m.hex_y(x, z, 4, -17.3, -15.7).cut(
            m.cy(x, z, 1.05, -17.4, -15.6))
    return refs


def build_right_switch(m):
    """返回（分组实体、颜色、COM/NO/NC 焊孔中心），均为最终装配坐标。"""
    cq, V = m.cq, m.V
    # 侧面轮廓：右键长轴向 -Z，直压方向 +X。
    # 10.2 高的局部凸缘与 9.5 高主体之间作短斜面。
    profile = [(-18.5, -23.9), (-8.3, -23.9), (-8.3, -32.0),
               (-9.0, -33.0), (-9.0, -43.7), (-18.5, -43.7)]
    wire = cq.Wire.makePolygon([V(x, -14, z) for x, z in profile], close=True)
    body = cq.Solid.extrudeLinear(wire, [], V(0, 6.4, 0))
    for x, z in MOUNT_HOLES:
        body = body.cut(m.cy(x, z, 1.175, -14.1, -7.5))
    # 按图直压头宽 3.2、长向宽约 2；突出量 0.8 是未按下状态的外观预留。
    plunger = m.box(-8.3, -7.5, -12.4, -9.2, -32, -30)

    # 图中端子沿长向偏移 1.6、10.4、17.7。
    # 焊孔直径 1.6，与侧面两个 2.35 安装孔用途不同。
    terminals, pins = {}, []
    for name, offset in (("COM", 1.6), ("NO", 10.4), ("NC", 17.7)):
        z = -23.9 - offset
        pin = m.box(-23.2, -18.4, -12.4, -9.2, z - .25, z + .25)
        pin = pin.cut(m.cz(-22.0, -10.8, .8, z - .35, z + .35))
        pins.append(pin)
        terminals[name] = (-22.0, -10.8, z)

    refs = {
        "右键-黑色外壳": body.clean(),
        "右键-原生按钮": plunger,
        "右键-扁脚": cq.Compound.makeCompound(pins),
    }
    colors = {
        "右键-黑色外壳": (.055, .055, .06),
        "右键-原生按钮": (.91, .57, .12),
        "右键-扁脚": (.74, .72, .65),
    }
    return refs, colors, terminals
