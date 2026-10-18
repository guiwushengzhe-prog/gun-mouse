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
BODY_MOUNT_HOLE = (-51.0, -38.0)
BODY_MOUNT_HOLES = {"H3": (-51.0, -4.0), "H4": (-27.0, -38.0), "H5": BODY_MOUNT_HOLE}
SHARED_SCREW_SEAT_Y = -18.0
SHARED_EAR_THICKNESS = 1.3


def body_hardware(m):
    """三个主体点均用M2×20；H3同时夹紧摇杆支座的薄连接耳。"""
    result = {}
    for name, (x, z) in BODY_MOUNT_HOLES.items():
        seat = SHARED_SCREW_SEAT_Y if name == "H3" else m.BASE[0]
        nut = m.TOP + (SHARED_EAR_THICKNESS if name == "H3" else 0)
        head = m.cy(x, z, 2, seat-2.1, seat).cut(m.hex_y(x, z, 1.5, seat-2.2, seat-1.1))
        result[name+"-螺钉"] = head.fuse(m.cy(x, z, 1, seat, seat+20))
        result[name+"-螺母"] = m.hex_y(x, z, 4, nut, nut+1.6).cut(m.cy(x, z, 1.05, nut-.1, nut+1.7))
    return result
