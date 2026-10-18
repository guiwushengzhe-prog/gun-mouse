"""最终规则版：小元件分区、两处主体柱共同承托摇杆，导出独立打印件。"""
import hashlib
import json
import shutil
import zipfile

import build_formal_rectangular_preview as formal
from final_regular_layout import OUT, RELEASE, PASSIVE_CENTERS, LOCAL, SEAT_Y, NUT_Y, move_passives
from preview_clean_body import round_block

m = formal.m
BASE_BODY = formal.body_shape
BASE_VERIFY = formal.verify
BASE_VERIFY_BOARD = formal.verify_board
BASE_HARDWARE = formal.concept.preview_hardware


def support_shape():
    # 安装带已无小元件焊点，内侧用一道规则开口腔，保留三条承力竖带。
    result = formal.concept.rectangular_support(m, xmin=-55.2, pocket_left=-48.1, xmax=-23.2)
    x, z = LOCAL
    # 还原旧10毫米短螺丝的较深头座，两处统一改为20毫米螺丝的承压深度。
    seat = m.cy(x, z, 2.2, 4.6, SEAT_Y).cut(m.cy(x, z, 1.2, 4.5, SEAT_Y+.1))
    result = result.fuse(seat)
    for x, old_y in m.JOY_MOUNT_HOLES:
        result = result.cut(m.cz(x+formal.concept.SHIFT_X, m.FACE_Y_SUM-old_y, 2.25, -10, -3.8))
    pins = [p["xz"][0]+formal.concept.SHIFT_X for p in m.JOYSTICK["pads"]]
    result = result.cut(m.box(min(pins)-1.4, max(pins)+1.4, .04, 2.84,
                             m.JOY_BOARD[4]-formal.SMALL_BOARD_CLEARANCE, m.JOY_BOARD[4]+.1))
    return result.clean()


def body_shape():
    result = BASE_BODY()
    x, z = LOCAL
    post = round_block(m, (x-3.2, x+3.2, m.BATTERY_FLOOR_Y, m.BACK, z-3.2, z+3.2), .6)
    result = result.fuse(post)
    result = result.cut(m.cy(x, z, 1.2, m.BATTERY_FLOOR_Y-.1, m.BACK+.1))
    for x, z in ((-51, -4), LOCAL):
        result = result.cut(m.box(x-6, x+2.5, NUT_Y[0]-.4, NUT_Y[1], z-2.3, z+2.3))
    return result.clean()


def hardware():
    refs, seats = BASE_HARDWARE()
    x, z = LOCAL
    head = m.cy(x, z, 2, SEAT_Y, SEAT_Y+2.1).cut(m.hex_y(x, z, 1.5, SEAT_Y+.9, SEAT_Y+2.2))
    refs["支座固定-螺钉"] = head.fuse(m.cy(x, z, 1, SEAT_Y-20, SEAT_Y))
    refs["支座固定-螺母"] = m.hex_y(x, z, 4, *NUT_Y).cut(m.cy(x, z, 1.05, NUT_Y[0]-.1, NUT_Y[1]+.1))
    return refs, seats


def verify(base, support, refs):
    report = BASE_VERIFY(base, support, refs)
    path = m.swept_box(refs["支座固定-螺母"], (-8, 0, 0))
    if any(path.intersect(shape).Volume() > .001 for shape in (base, support)):
        raise RuntimeError("新增主体柱的螺母入口被遮挡")
    x, z = LOCAL
    seat = base.intersect(m.cy(x, z, 3, m.BACK-.1, m.BACK))
    if seat.Volume() < 2:
        raise RuntimeError("新增固定柱未托到主板背面")
    report["新增主体固定柱"] = {"坐标毫米": list(LOCAL), "螺丝长度毫米": 20,
                              "螺杆超出螺母毫米": round(NUT_Y[0]-(SEAT_Y-20), 3),
                              "螺母入口": "侧面畅通", "支承截面平方毫米": round(seat.Volume()/.1, 3)}
    report["八颗小元件中心毫米"] = PASSIVE_CENTERS
    return report


def verify_board():
    result = BASE_VERIFY_BOARD()
    report = json.loads((OUT/"pcb/孔位与布线核对.json").read_text(encoding="utf-8"))
    checked = 0
    for part in m.C["parts"]:
        actual = {p["焊盘号"]: p for p in report["实际孔位核对"][part["ref"]] if p["焊盘号"]}
        for pad in part["pads"]:
            if part["ref"] == "SW2" and pad["number"] == "3":
                continue
            x, z = pad["xz"]
            if part["ref"] == "SW1":
                x += formal.concept.SHIFT_X
            elif part["ref"] == "J_GY":
                z += formal.current.IMU_TRANSLATION_Z
            elif part["ref"] == "J_SWITCH":
                x += formal.current.POWER_TRANSLATION[0]
                z += formal.current.POWER_TRANSLATION[2]
            item = actual[pad["number"]]
            if any(abs(a-b) > 1e-5 for a, b in zip((x, z), item["装配坐标毫米"])) or item["网络"] != pad["net"]:
                raise RuntimeError((part["ref"], pad["number"], "最终主板孔位或网络不符", item))
            checked += 1
    result["全板焊孔与网络交叉核对数"] = checked
    return result


def export_print_parts():
    destination = RELEASE/"三维打印"
    destination.mkdir(parents=True, exist_ok=True)
    report = {}
    for name, source in (("主体底座", "engineering_mount"), ("摇杆支座", "独立摇杆支座")):
        original = OUT/"step"/(source+".step")
        shape = m.cq.importers.importStep(str(original)).val()
        # 主体外侧大平面朝下；支座平整外侧朝下，所有内腔从上方可进入。
        printed = shape.rotate((0, 0, 0), (1, 0, 0), 90 if name == "主体底座" else -90)
        bounds = printed.BoundingBox()
        printed = printed.translate((-bounds.xmin, -bounds.ymin, -bounds.zmin))
        target = destination/(name+".stl")
        m.cq.exporters.export(printed, str(target), tolerance=.03, angularTolerance=.1)
        mesh = m.verify_mesh(target, shape.Volume())
        if not mesh["pass"]:
            raise RuntimeError((name, mesh))
        b = printed.BoundingBox()
        report[name] = {"数量": 1, "单位": "毫米", "尺寸毫米": [round(b.xlen, 3), round(b.ylen, 3), round(b.zlen, 3)],
                        "封闭网格": mesh, "SHA256": hashlib.sha256(target.read_bytes()).hexdigest()}
        shutil.copy2(original, destination/(name+".step"))
    (destination/"打印件核对.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    archive = RELEASE/"枪型飞鼠_最终版_上传打印.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name in report:
            z.write(destination/(name+".stl"), name+".stl")
    return report


def main():
    # 复用已核对的装配、焊点和操作空间检查，只替换本次落实的部分。
    formal.OUT, formal.BOARD = OUT, OUT/"pcb/gunmouse-final.kicad_pcb"
    formal.configure = configure_final
    formal.support_shape, formal.body_shape = support_shape, body_shape
    formal.concept.preview_hardware = hardware
    formal.verify = verify
    formal.verify_board = verify_board
    formal.main()
    result = export_print_parts()
    source_dir = RELEASE/"工程源文件"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir/"模型基准配置.json").write_text(json.dumps(m.C, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (source_dir/"布局与固定点.json").write_text(json.dumps({"小元件中心": PASSIVE_CENTERS, "新增固定柱": LOCAL}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


ORIGINAL_CONFIGURE = formal.configure
def configure_final():
    ORIGINAL_CONFIGURE()
    m.C = move_passives(m.C)
    for route in formal.current.detail.WIRE_ROUTES:
        dz = -2.54 if route[0] in {"扳机地线", "扳机信号线"} else -4 if route[0] == "触摸铜箔线" else 0
        if dz:
            for i in range(3):
                x, y, z = route[-1][i]
                route[-1][i] = (x, y, z+dz)
        if route[0] == "触摸铜箔线":
            # 先绕过右键地线的横向通道，再进入背侧走线层。
            route[-1][2:3] = [(-25.5, -4.8, -24), (-25.5, -13.2, -24)]


if __name__ == "__main__":
    main()
