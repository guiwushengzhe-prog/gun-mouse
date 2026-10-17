"""本轮装配预览共用孔位和电源开关位置，单位毫米。"""

# 保持板焊式安装，把拨动开关从底部移到惯性传感器下方空位。
POWER_TRANSLATION = (-11.5, 0.0, 42.3)
POWER_CENTER_XZ = (-53.0, 4.0)

# 模块上移后给直插摇杆备用孔的螺丝头和螺母留出空间。
IMU_TRANSLATION_Z = 2.2

# 由当前GY-601N1模型的两个2.5毫米安装孔投影到主板。
# 长向15.242毫米来自模块图，板端距约2.5毫米来自图比读。
IMU_MOUNT_HOLES = ((-53.849, 14.2+IMU_TRANSLATION_Z),
                   (-53.849, 29.442+IMU_TRANSLATION_Z))

# 电源开关移走后，在原位置增加第三个下部主板固定点。
BODY_MOUNT_HOLE = (-43.5, -38.0)


def body_hardware(m):
    """新增下部固定点使用已有M2×20螺丝和普通M2螺母。"""
    x, z = BODY_MOUNT_HOLE
    head = m.cy(x, z, 2, m.BASE[0]-2.1, m.BASE[0]).cut(
        m.hex_y(x, z, 1.5, m.BASE[0]-2.2, m.BASE[0]-1.1))
    return {
        "H5-螺钉": head.fuse(m.cy(x, z, 1, m.BASE[0], m.BASE[0]+20)),
        "H5-螺母": m.hex_y(x, z, 4, m.TOP, m.TOP+1.6).cut(
            m.cy(x, z, 1.05, m.TOP-.1, m.TOP+1.7)),
    }
