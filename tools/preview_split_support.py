"""首版预览：从现有底座拆出由两个穿板孔固定的摇杆支座。"""


def split_support(m, base):
    """保留现有孔位和开槽，以装配坐标返回两个打印件。"""
    front = [
        m.box(-19.4, -15.8, m.BASE[0], m.JOY_ARM_Y[1], 2, 4.2),
        m.box(-19.4, -15.8, *m.JOY_ARM_Y, -5.8, 4.2),
        m.box(-46.85, -15.8, *m.JOY_ARM_Y, -8.8, -2.2),
    ]
    for x, original_y in m.JOY_MOUNT_HOLES:
        front.append(m.cz(x, m.FACE_Y_SUM-original_y, 3.4,
                          -5.8, m.JOY_BOARD[4]))

    rear = []
    for _, x, z in m.JOY_SHARED_HOLES:
        rear.extend([
            m.cy(x, z, 3.4, -12.8, m.BACK),
            m.beam((x, z), (-37.5, 35), 4.5, -10, m.BACK),
        ])
    rear.extend([
        m.box(-39.75, -35.25, -10, m.BACK, 6.7, 35),
        m.box(-39.75, -15.8, -10, m.BACK, 6.7, 9.5),
        m.box(-19.4, -15.8, -10, m.BACK, 2, 9.5),
    ])

    front_mask = m.fuse(front)
    rear_mask = m.fuse(rear)
    # 原来的长臂不再连到主体后框；穿板锚座仍保留完整深度。
    detached_front = front_mask.intersect(
        m.box(-100, 100, -10, 100, -200, 100))
    support_mask = m.fuse([detached_front, rear_mask])
    removal_mask = m.fuse([front_mask, rear_mask])
    return {
        "主体底座": base.cut(removal_mask).clean(),
        "独立摇杆支座": base.intersect(support_mask).clean(),
    }
