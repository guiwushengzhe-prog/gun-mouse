"""取消扳机小板：SS-01GL 由用户焊两根线后，用 M2 螺钉固定在打印支架上，支架卡入原小板槽位。

运行：E:\\GunMouseCAD\\CadQuery\\python.exe -B scripts\\economy_holder.py
支架卡板沿用原小板 1.6 毫米卡板轮廓和原槽位（不移槽），2 毫米托条把开关底面垫到与工厂代焊小板版
相同的 X=-17.1，因此扳机、调节螺栓、设定片与工厂版几何一致。检查项与 economy_trigger.py 对应，
另加尾线通道检查。输出独立件，不覆盖其他版本。

扳机调节触点由 M2×10 外六角螺栓（电商难买）改为市售 M2×10 内六角圆柱头螺钉（ISO 4762/DIN 912）：
头径 3.8 毫米小于原六角头外接圆 4.62 毫米，原有避让全部够用；头高 2.0 毫米比原 1.4 毫米高，
扳机头槽向里加深、导孔加长，调节范围不变。头部端面仍是触点，端面的 1.5 毫米内六角孔用于调节。
"""
import json
import sys
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
import economy_trigger as et  # noqa: E402
from build_shell import box, cyl_x  # noqa: E402
from evt_a.build_evt_a_parts import build_fork, hex_prism_x, modify_trigger, single  # noqa: E402
from verify_mechanical import solid_contacts, volume_overlap  # noqa: E402

V = cq.Vector
OUT = ROOT / "outputs" / "economy-holder"
PRINT = ROOT / "deliverables" / "经济型单板自焊版" / "打印文件"
et.PRINT = PRINT
zero = et.zero
WIRE_OD = 1.0  # PH2.0 成品线 26AWG 外径约 0.9～1.0 毫米，按 1.0 检查
# 相对共享配置 config/economy-trigger.json 的支架修正（只在本脚本内覆盖，不改工厂版输入）：
HOLDER_FIX = {
    # 原焊片窗 Z≥-19.6 与出线口 Z≤-20.0 之间留有 0.4 毫米细桥，挡住两根尾线下行；改为连通。
    "wire_exit_z": [-35.0, -19.6],
    # 焊片宽 3.2 毫米，原窗宽 3.8 毫米；先焊线再装开关时焊点要穿过窗口，加宽到 4.6 毫米。
    "terminal_port_y_half": 2.3,
    # 全机螺丝统一为 M2×10/M2×20 杯头内六角：支架两颗由 M2×16 盘头改 M2×20 杯头（头按4.0×2.1检查）。
    "screw": "M2×20 杯头内六角（GB70.1/DIN912）两枚；M2 六角螺母两枚",
    "screw_length": 20.0, "head_d": 4.0, "head_height": 2.1,
}
# 相对 config/evt-a.json 的调节螺钉修正（同样只在本脚本内覆盖）：
SCREW_FIX = {
    "screw": "M2×10 内六角圆柱头螺钉（ISO 4762 / DIN 912），用 1.5 毫米内六角扳手调节",
    "head_d": 4.0,        # 标准头径 dk≤3.8，滚花头≤3.98，按 4.0 检查
    "head_height": 2.0,   # k≤2.0，比原外六角头高 0.6
    "socket_af": 1.5, "socket_depth": 1.0,
}
SLOT_X_MAX = 1.7     # 头槽内端由 0.9 加深到 1.7：δ=-1.5 时头尾在 X=1.5，留 0.2 间隙
PILOT_X_END = 11.8   # 导孔由 11.2 加长到 11.8：δ=-1.5 时螺钉尖在 X=11.5


def screw_head(ta, delta):
    """内六角圆柱头，端面即扳机触点；delta 为触点相对名义端面压向开关的量。"""
    face = ta["nominal_face_x"] - delta
    head = cyl_x(ta["axis_y"], ta["axis_z"], ta["head_d"] / 2, face, face + ta["head_height"])
    socket = hex_prism_x(ta["axis_y"], ta["axis_z"], ta["socket_af"], face - 0.01, face + ta["socket_depth"], 90)
    return head.cut(socket)


def screw(ta, delta):
    """整颗螺钉；杆径 2.0 大于 1.7 导孔，与扳机的重叠是自攻螺纹咬合，不作干涉判断。"""
    under = ta["nominal_face_x"] - delta + ta["head_height"]
    shank = cyl_x(ta["axis_y"], ta["axis_z"], 1.0, under, under + ta["screw_length"])
    return screw_head(ta, delta).fuse(shank).clean()


def wire_bundle(cfg):
    """两根尾线：从常开端、公共端焊片沿中央窗口下行，经卡板底部开口离开支架。"""
    h, s = cfg["holder"], cfg["switch"]
    x = (h["card_x"][0] + h["card_x"][1]) / 2
    # 焊片区内导线直接贴焊片走；从最低焊片以下开始检查汇合后的线束通道。
    z_top = s["body_left_z"] - s["terminal_from_left"][2] - s["terminal_thickness"] / 2 - WIRE_OD / 2
    z_bottom = h["card_z"][0] - 3.0
    r = WIRE_OD / 2
    wires = [cq.Solid.makeCylinder(r, z_top - z_bottom, V(x, y, z_bottom), V(0, 0, 1)) for y in (-0.6, 0.6)]
    for wire in wires:
        if not wire.isValid():
            raise ValueError("尾线名义包络无效")
    return cq.Compound.makeCompound(wires)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg_path = ROOT / "config" / "economy-trigger.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    original_holder = {key: cfg["holder"][key] for key in HOLDER_FIX}
    cfg["holder"].update(HOLDER_FIX)
    ev = et.load_ev(cfg)
    ta = ev["trigger_adjust"]
    original_screw = {"screw": ta["screw"], "head_across_flats": ta["head_across_flats"],
                      "head_height": ta["head_height"], "head_slot_x": list(ta["head_slot"]["x"]),
                      "pilot_x": list(ta["pilot_x"])}
    ta.update(SCREW_FIX)
    ta["head_slot"]["x"][1] = SLOT_X_MAX
    ta["pilot_x"][1] = PILOT_X_END
    paths = {name: ROOT / path for name, path in cfg["source_shells"].items()}
    paths["trigger"] = ROOT / ev["base"]["trigger"]
    paths["board"] = Path(cfg["source_board"])
    before = {name: {"path": str(path), "sha256": et.digest(path)} for name, path in paths.items()}
    left_source, right_source, trig_base = (cq.importers.importStep(str(paths[n])).val()
                                          for n in ("left", "right", "trigger"))
    # 原槽位不移动；只在右壳保留与工厂版相同的调节螺栓六角头避让。
    left = single(left_source, "左半壳-单板自焊")
    relief = cfg["right_shell_relief"]
    right = single(right_source.cut(box(*relief["x"], *relief["y"], *relief["z"])), "右半壳-单板自焊")
    trigger = modify_trigger(trig_base, ev)
    # 加长后的导孔外侧仍须保留至少 1 毫米实体壁，螺钉尖到导孔底不得顶死。
    pilot_r = ta["pilot_d"] / 2
    tube = cyl_x(ta["axis_y"], ta["axis_z"], pilot_r + 1.0, ta["pilot_x"][0] + 1.0, PILOT_X_END + 1.0).cut(
        cyl_x(ta["axis_y"], ta["axis_z"], pilot_r, ta["pilot_x"][0], PILOT_X_END))
    wall_fraction = trigger.intersect(tube).Volume() / tube.Volume()
    if wall_fraction < 0.999:
        raise ValueError(f"加长导孔周围实体壁不足：{wall_fraction:.4f}")
    lo_check, hi_check = ta["adjust_range_mm"]
    tip_at_lo = ta["nominal_face_x"] - lo_check + ta["head_height"] + ta["screw_length"]
    if tip_at_lo > PILOT_X_END:
        raise ValueError("最大退出位置时螺钉尖超出导孔底")
    engaged_at_hi = ta["nominal_face_x"] - hi_check + ta["head_height"] + ta["screw_length"] - SLOT_X_MAX
    rigid, lever, holes = et.switch_models(cfg)
    holder = et.build_holder(cfg, holes)
    bolts, nuts = et.mount_screws(cfg, holes)
    hardware = cq.Compound.makeCompound([*bolts, *nuts])
    wires = wire_bundle(cfg)

    stationary = {"开关支架": holder, "SS01GL本体及焊片": rigid, "M2螺钉螺母": hardware}
    internal = {"支架与开关本体": volume_overlap(holder, rigid),
                "支架与螺钉螺母": sum(volume_overlap(holder, p) for p in [*bolts, *nuts]),
                "开关与螺钉螺母": sum(volume_overlap(rigid, p) for p in [*bolts, *nuts]),
                "尾线与支架": volume_overlap(wires, holder), "尾线与开关本体": volume_overlap(wires, rigid)}
    for name, amount in internal.items():
        zero(name, amount)
    hole_fit = {f"安装孔{i + 1}": {"开关孔径": d, "螺钉直径": 2.0, "支架孔径": cfg["holder"]["screw_clearance_d"]}
                for i, d in enumerate(cfg["switch"]["hole_diameter"])}
    mount_checks = {name: {"左壳": volume_overlap(part, left), "右壳": volume_overlap(part, right)}
                    for name, part in {**stationary, "尾线": wires}.items()}
    for name, checks in mount_checks.items():
        for shell_name, amount in checks.items():
            zero(name + "与" + shell_name, amount)
    # 开关底面落在托条上；只允许名义贴面接触，不允许穿透。
    xb = cfg["switch"]["body_bottom_x"]
    seat = rigid.intersect(holder)
    if seat.Volume() > 1e-6:
        bb = seat.BoundingBox()
        if bb.xmin < xb - 1e-7 or bb.xmax > xb + 0.0001:
            raise ValueError("开关本体与支架托条出现超出贴面容差的穿透")
    print("支架、开关、螺钉螺母、尾线与左右壳检查完成", flush=True)

    ta, travel = ev["trigger_adjust"], cfg["trigger"]["travel_mm"]
    lo, hi = ta["adjust_range_mm"]
    checks = {}
    for delta in (lo, 0.0, hi):
        zero("调节头与扳机槽", volume_overlap(screw_head(ta, delta), trigger))
        for state, x in (("静止", 0.0), ("半程", -travel / 2), ("按到底", -travel)):
            moving = trigger.fuse(screw(ta, delta)).translate(V(x, 0, 0))
            checks[f"调节{delta:+.1f}_{state}"] = {
                name: volume_overlap(moving, part) for name, part in
                {"左壳": left, "右壳": right, "尾线": wires, **stationary}.items()}
            for name, amount in checks[f"调节{delta:+.1f}_{state}"].items():
                zero(state + name, amount)
            checks[f"调节{delta:+.1f}_{state}"]["名义自由摆杆_允许按压重叠"] = volume_overlap(moving, lever)
    continuous = et.continuous_translation_check(trigger, {"左壳": left, "右壳": right, "尾线": wires,
                                                           **stationary}, travel)
    head_radius = ta["head_d"] / 2
    head_sweep = cyl_x(ta["axis_y"], ta["axis_z"], head_radius,
                       ta["nominal_face_x"] - hi - travel, ta["nominal_face_x"] - lo + ta["head_height"])
    shaft_sweep = cyl_x(ta["axis_y"], ta["axis_z"], 1,
                        ta["nominal_face_x"] - hi + ta["head_height"] - travel,
                        ta["nominal_face_x"] - lo + ta["head_height"] + ta["screw_length"])
    screw_envelope = head_sweep.fuse(shaft_sweep)
    screw_checks = {name: volume_overlap(screw_envelope, part)
                    for name, part in {"左壳": left, "右壳": right, "尾线": wires, **stationary}.items()}
    for name, amount in screw_checks.items():
        zero("螺栓全调节量和全行程包络与" + name, amount)
    local_head_envelope = cyl_x(ta["axis_y"], ta["axis_z"], head_radius,
                                ta["nominal_face_x"] - hi, ta["nominal_face_x"] - lo + ta["head_height"])
    zero("圆柱头全调节区间与扳机槽", volume_overlap(local_head_envelope, trigger))
    print("扳机连续全行程、螺钉全调整区间完成检查", flush=True)

    pcb = cq.importers.importStep(str(paths["board"])).val()
    pcb_contacts = {name: solid_contacts(part, pcb) for name, part in {**stationary, "尾线": wires}.items()}
    pcb_contacts["螺栓完整包络"] = solid_contacts(screw_envelope, pcb)
    if any(pcb_contacts.values()):
        raise ValueError("支架、开关、尾线或螺栓与主板实体干涉：" + json.dumps(pcb_contacts, ensure_ascii=False))
    continuous["主板及元件"] = et.continuous_translation_check(trigger, {"主板及元件": pcb}, travel)["主板及元件"]
    print("主板参考模型检查完成", flush=True)

    # 合壳后支架整体（连同开关）在六个方向都应被壳体实体挡住。
    retention = {}
    assembly_solid = holder.fuse(rigid)
    for axis, step in (("X", 0.4), ("Y", 1.1), ("Z", 0.6)):
        for sign in (-1, 1):
            v = {"X": (sign * step, 0, 0), "Y": (0, sign * step, 0), "Z": (0, 0, sign * step)}[axis]
            moved = assembly_solid.translate(V(*v))
            contacts = {"左壳": volume_overlap(moved, left), "右壳": volume_overlap(moved, right)}
            retention[f"{axis}{sign * step:+.1f}"] = contacts
            if max(contacts.values()) < 0.001:
                raise ValueError(f"合壳后支架缺少{axis}{sign:+d}方向实体限位")
    stop = {"多压0.5_右壳": volume_overlap(trigger.translate(V(-travel - 0.5, 0, 0)), right),
            "多压0.5_左壳": volume_overlap(trigger.translate(V(-travel - 0.5, 0, 0)), left)}
    if stop["多压0.5_右壳"] < 0.001 or stop["多压0.5_左壳"] > 0.001:
        raise ValueError("原右壳独立硬止挡检查失败")
    forks, fork_checks = {}, {}
    stop_face = ev["single_stop_datum"]["block"]["x"][1]
    spring = cyl_x(0, ev["setting_fork"]["spring_model"]["axis_z"],
                   ev["setting_fork"]["spring_model"]["od"] / 2, stop_face, stop_face + 13.1)
    for thickness in ev["setting_fork"]["thickness_mm"]:
        fork = build_fork(ev, thickness, stop_face)
        fork = single(fork.cut(box(stop_face - 0.1, stop_face + thickness + 0.1,
                                   *relief["y"], *relief["z"])), f"设定片{thickness}")
        forks[thickness] = fork
        check = {"压簧包络": volume_overlap(fork, spring), "尾线": volume_overlap(fork, wires),
                 **{n: volume_overlap(fork, p) for n, p in stationary.items()}}
        check["右壳"] = volume_overlap(fork, right)
        for delta in (lo, 0.0, hi):
            moving = trigger.fuse(screw(ta, delta)).translate(V(-travel + thickness, 0, 0))
            check[f"扳机及螺栓_调节{delta:+.1f}"] = volume_overlap(fork, moving)
        for name, amount in check.items():
            zero(f"{thickness}毫米设定片与" + name, amount)
        fork_checks[str(thickness)] = check

    op_min, op_max = [xb + h for h in cfg["switch"]["operating_height_from_bottom"]]
    needed_delta = [ta["nominal_face_x"] - travel + 1.0 - op_max, ta["nominal_face_x"] - travel + 1.0 - op_min]
    if needed_delta[0] < lo or needed_delta[1] > hi:
        raise ValueError("设定片校准范围未覆盖原厂动作位置公差")
    calibration = {"method": ["开关焊好两根线、用两颗M2×16螺钉和螺母固定到支架，支架插入右壳原小板卡槽；装压簧和扳机，暂不合左壳；放入1.0毫米设定片",
                               "先完全松开，再按扳机至设定片；旋转M2调节螺栓，调到公共端与常开端刚刚导通",
                               "换0.8毫米片：先完全松开再按至片，应导通；换1.2毫米片：先完全松开再按至片，应不导通",
                               "撤片，按到底应导通；完全松手必须断开；合壳后重复检查"],
                   "required_delta_for_OP_range_mm": needed_delta,
                   "overtravel_at_full_press_after_1mm_setting_mm": 1.0,
                   "note": "开关底面X与工厂代焊小板版相同，调节范围和设定片沿用；调节螺钉没有防无限退出的挡圈"}

    holder_print = export_holder(holder)
    parts = {"扳机开关支架-SS01GL": holder_print,
             "扳机-经济型": et.export_part(trigger, "扳机-经济型", [((1, 0, 0), 90)]),
             "左半壳-单板自焊": et.export_part(left, "左半壳-单板自焊", [((1, 0, 0), -90)]),
             "右半壳-单板自焊": et.export_part(right, "右半壳-单板自焊", [((1, 0, 0), 90)])}
    for thickness, fork in forks.items():
        name = f"扳机设定片-经济型-{thickness:.1f}mm"
        parts[name] = et.export_part(fork, name, [((0, 1, 0), -90)])
    for name, part in (("left", left), ("right", right), ("trigger", trigger), ("holder", holder),
                       ("switch-rigid-nominal", rigid), ("switch-lever-fp-limit-nominal", lever),
                       ("m2-hardware", hardware), ("wires-nominal", wires)):
        cq.exporters.export(cq.Workplane().add(part), str(OUT / f"{name}.step"))
    assembly = cq.Assembly()
    for name, part, color in (("左半壳原槽", left, (0.8, 0.8, 0.8, 0.3)),
                              ("右半壳原槽及触点避让", right, (0.7, 0.7, 0.7, 0.3)),
                              ("扳机", trigger, (0.9, 0.5, 0.2, 1)),
                              ("SS01GL打印支架", holder, (0.2, 0.5, 0.8, 1)),
                              ("SS01GL本体名义模型", rigid, (0.1, 0.1, 0.1, 1)),
                              ("SS01GL自由位置上限摆杆示意", lever, (0.7, 0.7, 0.7, 1)),
                              ("M2螺钉螺母", hardware, (0.6, 0.6, 0.6, 1)),
                              ("尾线名义包络", wires, (0.8, 0.1, 0.1, 1)),
                              ("调节螺栓", screw(ta, 0), (0.6, 0.6, 0.6, 1))):
        assembly.add(part, name=name, color=cq.Color(*color))
    assembly.save(str(OUT / "SS01GL-打印支架与扳机装壳参考.step"))
    after = {name: et.digest(path) for name, path in paths.items()}
    if any(after[name] != before[name]["sha256"] for name in paths):
        raise ValueError("读取的源文件在生成期间改变")
    report = {"manufacturing_finalized": False,
              "scope": "单板自焊开关方案的实体连续行程、支架限位、尾线通道及网格检查；未打印、未装实物",
              "source_files": before, "config_sha256": et.digest(cfg_path),
              "switch_model_boundary": cfg["switch"]["model_boundary"],
              "switch_coordinates_mm": {"hole_axes_XZ": holes, "body_bottom_X": xb,
                                        "action_Z": cfg["switch"]["body_left_z"] - cfg["switch"]["action_from_left"],
                                        "operating_X_range": [op_min, op_max]},
              "same_switch_position_as_factory_daughter": xb == cfg["factory_daughter"]["top_face_x"],
              "holder_slot": {"card_x": cfg["holder"]["card_x"], "original_slot_x": cfg["factory_daughter"]["slot_original_x"],
                              "note": "支架卡板进入原槽，不使用工厂版的+1.9毫米移槽"},
              "holder_changes_vs_shared_config": {key: {"原值": original_holder[key], "本版": HOLDER_FIX[key]}
                                                  for key in HOLDER_FIX},
              "wire_envelope_boundary": "两根外径1.0毫米尾线从最低焊片以下沿卡板中面下行并穿出支架底部；焊片区内贴焊片走线不单独建模",
              "internal_contacts_mm3": internal, "hole_fit_mm": hole_fit,
              "installed_stationary_contacts_mm3": mount_checks, "wire_od_checked_mm": WIRE_OD,
              "trigger_with_screw_contacts_mm3": checks, "continuous_trigger_translation_evidence": continuous,
              "screw_full_adjustment_and_motion_envelope_contacts_mm3": screw_checks,
              "board_contacts": pcb_contacts, "holder_closed_shell_displacement_stops_mm3": retention,
              "independent_hard_stop_mm3": stop, "trigger_adjust_range_mm": [lo, hi],
              "setting_fork_contacts_mm3": fork_checks, "calibration": calibration,
              "parts": parts, "preserved_features": cfg["trigger"]["preserved"],
              "shell_modification": {"slots": "原槽位不变", "right_head_relief": relief},
              "adjust_screw": {"本版": SCREW_FIX, "原外六角": original_screw,
                               "扳机头槽X": ta["head_slot"]["x"], "导孔X": ta["pilot_x"],
                               "导孔外1毫米壁实体占比": wall_fraction,
                               "最大退出时螺钉尖X": tip_at_lo, "最大伸出时塑料内螺纹啮合长度mm": engaged_at_hi,
                               "螺距mm": 0.4, "四分之一圈调节量mm": 0.1},
              "adjustment_is_mechanically_captive": False}
    (OUT / "几何检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(OUT / "几何检查.json"), "parts": list(parts)}, ensure_ascii=False), flush=True)


def export_holder(holder):
    """卡板背面（X 最小面）朝下打印：两侧墙与凸台向上生长，安装孔为水平小孔。"""
    result = et.export_part(holder, "扳机开关支架-SS01GL", [((0, 1, 0), -90)])
    pb, ab = result["print_bounds_mm"], result["bounds_assembled_mm"]
    if abs((pb[5] - pb[4]) - (ab[1] - ab[0])) > 1e-3:
        raise ValueError("支架打印姿态不是卡板背面朝下")
    return result


if __name__ == "__main__":
    main()
