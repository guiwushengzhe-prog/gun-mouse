"""长方条支座正式预览：同步实板、接线孔和手焊净空，不替换旧交付。"""
from copy import deepcopy
import hashlib
import json

import build_rectangular_support_preview as concept
from preview_layout import BODY_MOUNT_HOLES
from preview_ss01_right import build_right_switch
from preview_ss01_right import MOUNT_HOLES as RIGHT_MOUNT_HOLES

current = concept.current
m = current.m
OUT = m.ROOT / "shell/长方条正式预览"
BOARD = OUT / "pcb/preview-rectangular-mount.kicad_pcb"
MAX_SOLDER_HEIGHT = 4.0
SOLDER_MARGIN = .5
SMALL_BOARD_CLEARANCE = 3.0
CONNECTIONS = {
    "SW2": {"2": (-30.0, -12.0), "1": (-30.0, -14.54)},
    "J_TRIG": {"1": (-25.5, -12.0), "2": (-25.5, -9.46)},
}


def configure():
    # 只改本进程内的布局；保留已交付的原始配置及生成器。
    m.C = deepcopy(m.C)
    current.POWER_TRANSLATION = (-11.5, 0.0, 46.3)
    for part in m.C["parts"]:
        for pad in part.get("pads", []):
            if part["ref"] in CONNECTIONS and pad["number"] in CONNECTIONS[part["ref"]]:
                pad["xz"] = list(CONNECTIONS[part["ref"]][pad["number"]])
    routes = deepcopy(current.detail.WIRE_ROUTES)
    for route in routes:
        if route[0] in {"扳机地线", "扳机信号线"}:
            for i in range(3):
                x, y, z = route[-1][i]
                route[-1][i] = (x, y, z-3)
    current.detail.WIRE_ROUTES = routes


def support_shape():
    result = concept.rectangular_support(m, xmin=-54.7, pocket_left=-48.6)
    ceiling = m.TOP + MAX_SOLDER_HEIGHT + SOLDER_MARGIN
    pocket = m.box(-48.6, -23.45, m.TOP-.1, ceiling, -10, -.5)
    pocket = pocket.cut(m.cy(*concept.PREVIEW_LOCAL, 2.6, m.TOP-.2, ceiling+.1))
    for x, old_y in m.JOY_MOUNT_HOLES:
        # 保留螺丝头上方的完整承力柱，不能用大凹腔把半边承压面挖掉。
        pocket = pocket.cut(m.cz(x+concept.SHIFT_X, m.FACE_Y_SUM-old_y,
                                2.8, -3.8, m.JOY_BOARD[4]+.1))
    result = result.cut(pocket)
    pins = [pad["xz"][0]+concept.SHIFT_X for pad in m.JOYSTICK["pads"]]
    # 原生小板已焊短脚净空3毫米，槽底与内腔相连，避免留下0.2毫米薄片。
    result = result.cut(m.box(min(pins)-1.4, max(pins)+1.4, .04, 2.84,
                             m.JOY_BOARD[4]-SMALL_BOARD_CLEARANCE, m.JOY_BOARD[4]+.1))
    return result.clean()


def body_shape():
    result = concept.preview_body(m)
    # 电池正极背焊点邻近H5柱侧边；将柱的这一面收平0.2毫米，保留高焊点余量。
    return result.cut(m.box(-60, -54.0, m.BACK-4.6, m.BACK+.1, -41.5, -34.5)).clean()


def nominal_solder(module, x, z, radius=.90, face=None, direction=1):
    # 普通手焊约2毫米；最高4毫米另用保守包络核对，不把每处焊点都画高。
    height = 2 if face is None or abs(face-module.BACK) < 1e-6 else .6
    face = module.TOP if face is None else face
    return module.cq.Solid.makeCone(radius, .32, height, module.V(x, face, z),
                                   module.V(0, direction, 0))


def details(module, refs):
    refs, colors, wires = current.preview_details(module, refs)
    refs["载板"] = concept.preview_board(m)
    for name in refs:
        if name.startswith(("SW1-", "摇杆-")):
            refs[name] = refs[name].translate((concept.SHIFT_X, 0, 0))
    # 覆盖区的电阻脚用最高4毫米表示，让预览能直接看到真实的避让深度。
    pads = next(p for p in m.C["parts"] if p["ref"] == "R_TRIG")["pads"]
    refs["R_TRIG-焊点"] = m.cq.Compound.makeCompound([
        m.cq.Solid.makeCone(1.05, .32, MAX_SOLDER_HEIGHT,
                           m.V(p["xz"][0], m.TOP, p["xz"][1]), m.V(0, 1, 0))
        for p in pads])
    _, _, terminals = build_right_switch(m)
    signal_end = (*terminals["NO"][:2], terminals["NO"][2]-.4)
    ground_end = (*terminals["COM"][:2], terminals["COM"][2]-.4)
    routes = [
        ("右键信号短线", "BTN_R", (.16, .55, .18), [
            (-30, m.TOP+.6, -12), (-30, -7, -12), (-33, -10.8, -14),
            (-33, -10.8, -31.6), (-24, -10.8, -31.6),
            (-22, -10.8, -32.5), signal_end]),
        ("右键地线短线", "GND", (.025, .027, .03), [
            (-30, m.TOP+.6, -14.54), (-30, -7, -14.54), (-31, -7, -17),
            (-31, -7, -21.5), (-24, -7, -21.5), (-24, -10.8, -21.5),
            (-22, -10.8, -23.7), ground_end]),
    ]
    wires = [wire for wire in wires if not wire["name"].startswith("右键")]
    for name, net, rgb, points in routes:
        core, length = current.detail.tube(m, points, .125, .8)
        insulated = list(points)
        insulated[0] = (points[0][0], -4.5, points[0][2])
        end, before = m.V(*points[-1]), m.V(*points[-2])
        insulated[-1] = (end+(before-end).normalized()*1.2).toTuple()
        jacket, _ = current.detail.tube(m, insulated, .4, .8)
        refs[name+"-铜芯"], refs[name+"-绝缘皮"] = core, jacket
        colors[name+"-铜芯"], colors[name+"-绝缘皮"] = (.72, .39, .16), rgb
        wires.append({"name": name, "net": net, "centreline_length_mm": round(length, 2),
                      "insulation_diameter_mm": .8, "endpoints_xyz_mm": [points[0], points[-1]],
                      "path_xyz_mm": points})
    return refs, colors, wires


def verify(base, support, refs):
    report = {"单位": "毫米", "主板焊点上限": MAX_SOLDER_HEIGHT,
              "额外高度余量": SOLDER_MARGIN, "摇杆已焊短脚净空": SMALL_BOARD_CLEARANCE,
              "实体": {}, "主板焊点包络交叠": {}, "螺丝工具通道交叠": {}}
    all_shapes = {**refs, "主体底座": base}
    for name, shape in (("主体底座", base), ("独立摇杆支座", support)):
        hits = {}
        for other, component in all_shapes.items():
            if other == name or "留空" in other:
                continue
            volume = shape.intersect(component).Volume()
            if volume > .001:
                hits[other] = round(volume, 5)
        valid = shape.isValid() and len(shape.Solids()) == 1
        report["实体"][name] = {"有效单体": valid, "交叠": hits,
                                "体积立方毫米": round(shape.Volume(), 3)}
        if not valid or hits:
            raise RuntimeError((name, valid, hits))
    hardware = {name: shape for name, shape in refs.items() if name.endswith(("螺钉", "螺母"))}
    for part in m.C["parts"]:
        if not part.get("populate", True):
            continue
        for pad in part.get("pads", []):
            if not pad.get("drill") or (part["ref"] == "SW2" and pad["number"] == "3"):
                continue
            x, z = pad["xz"]
            if part["ref"] == "SW1":
                x += concept.SHIFT_X
            elif part["ref"] == "J_GY":
                z += current.IMU_TRANSLATION_Z
            elif part["ref"] == "J_SWITCH":
                x += current.POWER_TRANSLATION[0]
                z += current.POWER_TRANSLATION[2]
            # 包络半径包括横向余量；只核对主板焊点与结构/五金。
            radius = max(1.3, min(pad.get("size", [2.1, 2.1]))/2)+.3
            shapes = {"主体底座": base, "支座": support, **hardware}
            envelopes = {"正面": m.cy(x, z, radius, m.TOP+.01, m.TOP+MAX_SOLDER_HEIGHT+SOLDER_MARGIN),
                         "背面": m.cy(x, z, radius, m.BACK-MAX_SOLDER_HEIGHT-SOLDER_MARGIN, m.BACK-.01)}
            for face, envelope in envelopes.items():
                hits = {name: round(envelope.intersect(shape).Volume(), 5)
                        for name, shape in shapes.items() if envelope.intersect(shape).Volume() > .001}
                if hits:
                    raise RuntimeError((part["ref"], pad["number"], face, "高焊点遮挡", hits))
                report["主板焊点包络交叠"][part["ref"]+"."+pad["number"]+face] = hits
    for pad in m.JOYSTICK["pads"]:
        x = pad["xz"][0]+concept.SHIFT_X
        envelope = m.cz(x, 1.44, 1.3, m.JOY_BOARD[4]-SMALL_BOARD_CLEARANCE+.01, m.JOY_BOARD[4]-.01)
        if any(envelope.intersect(shape).Volume() > .001 for shape in (base, support, *hardware.values())):
            raise RuntimeError((pad["number"], "原生小板短脚空间被遮挡"))
    report["摇杆小板五处短脚空间"] = "3毫米包络与主体、支座及五金无交叠"
    tools = {"共用H3": m.cy(*BODY_MOUNT_HOLES["H3"], .9, 7.45, 35),
             "支座固定": m.cy(*concept.PREVIEW_LOCAL, .9, 6.8, 35)}
    for name in ("H4", "H5"):
        tools[name] = m.cy(*BODY_MOUNT_HOLES[name], .9, -35, m.BASE[0]-2.11)
    for i, (x, z) in enumerate(m.SS_HOLES, 1):
        tools[f"扳机{i}"] = m.cy(x, z, .9, .45, 30)
    for i, (x, z) in enumerate(RIGHT_MOUNT_HOLES, 1):
        tools[f"右键{i}"] = m.cy(x, z, .9, -5.49, 30)
    for i, (x, y) in enumerate(m.JOY_MOUNT_HOLES, 1):
        tools[f"摇杆{i}"] = m.cz(x+concept.SHIFT_X, m.FACE_Y_SUM-y, .9, -35, -6)
    for name, tool in tools.items():
        hits = {other: round(tool.intersect(shape).Volume(), 5) for other, shape in all_shapes.items()
                if "留空" not in other and tool.intersect(shape).Volume() > .001}
        if hits:
            raise RuntimeError((name, "工具入口阻挡", hits))
        report["螺丝工具通道交叠"][name] = hits
    for i, (x, old_y) in enumerate(m.JOY_MOUNT_HOLES):
        # 前一步深凹腔必须保留两处承压平面，不能仅看是否仍是单体。
        x, y = x+concept.SHIFT_X, m.FACE_Y_SUM-old_y
        seat = m.cz(x, y, 2.75, -3.799, -3.789)
        before = concept.rectangular_support(m).intersect(seat).Volume()
        after = support.intersect(seat).Volume()
        if after < before-.00001:
            raise RuntimeError((i+1, "摇杆螺丝承力面减少", before, after))
    report["摇杆螺丝承力面"] = "两处原承力截面完整保留"
    names = ["H3-螺钉", "支座固定-螺钉", "摇杆1-螺钉", "摇杆2-螺钉"]
    for i, name in enumerate(names):
        for other in names[i+1:]:
            if refs[name].intersect(refs[other]).Volume() > .001:
                raise RuntimeError((name, other, "螺丝交叠"))
    nut_path = m.swept_box(refs["H3-螺母"], (-8, 0, 0))
    if any(nut_path.intersect(shape).Volume() > .001 for shape in (base, support)):
        raise RuntimeError("共用螺母侧面入口被遮挡")
    report["共用螺母入口"] = "侧向装入无结构遮挡"
    for name, nut in refs.items():
        if not name.endswith("螺母") or not name.startswith(("SS", "右键")):
            continue
        path = m.swept_box(nut, (-12, 0, 0) if name.startswith("SS") else (12, 0, 0))
        if any(path.intersect(shape).Volume() > .001 for shape in (base, support)):
            raise RuntimeError((name, "按键螺母侧入口遮挡"))
    report["按键螺母入口"] = "四处侧向装入无结构遮挡"
    raw = m.references()
    spaces = {"摇杆保守运动包络": raw["摇杆全角度留空"].translate((concept.SHIFT_X, 0, 0)),
              "USB插头通道": raw["USB插头留空"]}
    for name, space in spaces.items():
        excluded = ("SW1-", "摇杆-") if name.startswith("摇杆") else ("开发板-USB", "USB")
        hits = {other: round(space.intersect(shape).Volume(), 5) for other, shape in all_shapes.items()
                if not other.startswith(excluded) and "留空" not in other
                and space.intersect(shape).Volume() > .001}
        if hits:
            raise RuntimeError((name, hits))
    report["操作空间"] = "名义摇杆运动包络和USB插头通道均无其他实体交叠"
    return report


def verify_board():
    audit = json.loads((BOARD.parent/"孔位与布线核对.json").read_text(encoding="utf-8"))
    if audit["错误"] or audit["未连接"]:
        raise RuntimeError("主板规则检查尚未通过")
    expected = {}
    for part in m.C["parts"]:
        if part["ref"] not in {"SW1", "SW2", "J_TRIG", "J_SWITCH"}:
            continue
        expected[part["ref"]] = {}
        for pad in part["pads"]:
            if part["ref"] == "SW2" and pad["number"] == "3":
                continue
            x, z = pad["xz"]
            if part["ref"] == "SW1":
                x += concept.SHIFT_X
            elif part["ref"] == "J_SWITCH":
                x += current.POWER_TRANSLATION[0]
                z += current.POWER_TRANSLATION[2]
            expected[part["ref"]][pad["number"]] = [x, z]
    expected["H_JOY_LOCAL_2"] = {"": list(concept.PREVIEW_LOCAL)}
    for name, point in BODY_MOUNT_HOLES.items():
        expected["H_BODY_5" if name == "H5" else name] = {"": list(point)}
    for name, pads in expected.items():
        actual = {pad["焊盘号"]: pad["装配坐标毫米"] for pad in audit["实际孔位核对"][name]}
        if set(actual) != set(pads) or any(abs(v-w) > .00001 for number, point in pads.items()
                                          for v, w in zip(point, actual[number])):
            raise RuntimeError((name, "主板与装配模型孔位不一致", pads, actual))
    return {"核对孔组": list(expected), "错误": audit["错误"], "未连接": audit["未连接"],
            "警告": audit["警告"]}


def main():
    configure()
    current.detail.solder = nominal_solder
    support = support_shape()
    current.SUPPORT = support
    base = body_shape()
    refs, _, _ = details(m, m.references())
    refs.update(concept.preview_hardware()[0])
    report = verify(base, support, refs)
    for folder in ("step", "stl"):
        (OUT/folder).mkdir(parents=True, exist_ok=True)
    m.cq.exporters.export(base, str(OUT/"step/engineering_mount.step"))
    m.cq.exporters.export(support, str(OUT/"step/独立摇杆支座.step"))
    for name, shape in (("主体底座", base), ("独立摇杆支座", support)):
        target = OUT/"stl"/(name+"_装配坐标.stl")
        m.cq.exporters.export(shape, str(target), tolerance=.03, angularTolerance=.1)
        mesh = m.verify_mesh(target, shape.Volume())
        if not mesh["pass"]:
            raise RuntimeError((name, "单件网格未封闭", mesh))
        report["实体"][name]["单件网格"] = mesh
    if not BOARD.exists() or not BOARD.with_suffix(".obj").exists():
        raise RuntimeError("等待本方案主板布线及三维板模型同步完成")
    report["主板装配孔位交叉核对"] = verify_board()
    m.OUT = OUT
    current.detail.assembled_details = details
    m.hardware = concept.preview_hardware
    m.routed_pcb_meshes = lambda bounds: current.ORIGINAL_BOARD_MESHES(bounds, BOARD.with_suffix(".obj"))
    report_path = OUT/"assembly-check.json"
    report_path.write_text("{}", encoding="utf-8")
    m.export_assembled_stl(render_preview=False)
    assembly = json.loads(report_path.read_text(encoding="utf-8"))["assembled_model"]
    if any(value > .001 for value in assembly["wire_insulation_vs_mount_mm3"].values()) or assembly["wire_insulation_pair_overlaps_mm3"]:
        raise RuntimeError(("导线交叠", assembly["wire_insulation_vs_mount_mm3"],
                            assembly["wire_insulation_pair_overlaps_mm3"]))
    assembly["pcb_sha256"] = hashlib.sha256(BOARD.read_bytes()).hexdigest()
    report["完整装配"] = assembly
    report["检查边界"] = "模型几何、焊点包络和主板静态规则检查；未完成实物装配与通电。"
    report_path.unlink()
    (OUT/"模型核对.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("正式预览完成：主板焊点4毫米上限加0.5毫米余量，原生摇杆短脚净空3毫米。", flush=True)


if __name__ == "__main__":
    main()
