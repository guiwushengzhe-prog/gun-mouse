"""工厂代焊 SS-01GL 小板与扳机，读取工程样壳体做实体装配检查。

运行：E:\\GunMouseCAD\\CadQuery\\python.exe -B scripts\\economy_trigger.py
输出独立件，不覆盖原工程样或其他代理正在修改的壳体。
"""
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
from build_shell import box, cyl_x, cyl_y, prism_xz  # noqa: E402
from clean_stl_zero_area import clean as clean_stl  # noqa: E402
from evt_a.build_evt_a_parts import build_fork, modify_trigger, screw, screw_head, single  # noqa: E402
from verify_mechanical import mesh_evidence, solid_contacts, volume_overlap  # noqa: E402

V = cq.Vector
OUT = ROOT / "outputs" / "economy-trigger"
PRINT = ROOT / "deliverables" / "经济型工厂代焊版" / "打印文件"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounds(shape):
    b = shape.BoundingBox()
    return [round(v, 4) for v in (b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax)]


def hex_y(x, z, across_flats, y0, y1):
    r = across_flats / math.sqrt(3)
    return prism_xz([(x + r * math.cos(math.radians(60 * i)),
                      z + r * math.sin(math.radians(60 * i))) for i in range(6)], y0, y1)


def load_ev(cfg):
    ev = copy.deepcopy(json.loads((ROOT / cfg["source_evt_config"]).read_text(encoding="utf-8")))
    ta = ev["trigger_adjust"]
    ta["axis_z"] = cfg["trigger"]["axis_z"]
    shift = cfg["trigger"]["head_slot_z_shift"]
    ta["head_slot"]["z"] = [z + shift for z in ta["head_slot"]["z"]]
    ta["head_slot"]["side_open_z_top"] += shift
    ta["adjust_range_mm"] = cfg["trigger"]["adjust_range_mm"]
    ta["adjust_note"] = cfg["trigger"]["range_note"]
    return ev


def switch_models(cfg):
    """拆分刚性本体与可按压杠杆，杠杆交集不能冒充本体干涉。"""
    s = cfg["switch"]
    xb, zl = s["body_bottom_x"], s["body_left_z"]
    zr = zl - s["body_length"]
    half = s["body_width"] / 2
    rigid = box(xb, xb + s["body_flat_height"], -half, half, zr, zl)
    rigid = rigid.fuse(box(xb + s["body_flat_height"], xb + s["body_envelope_height"],
                          -half, half, zl - s["cap_left_length_model"], zl))
    xh = xb + s["hole_axis_height"]
    holes = [(xh, zl - offset) for offset in s["hole_from_left"]]
    for (x, z), d in zip(holes, s["hole_diameter"]):
        rigid = rigid.cut(cyl_y(x, z, d / 2, -half - 0.1, half + 0.1))
    terminals = []
    for offset in s["terminal_from_left"]:
        z = zl - offset
        pin = box(xb - s["terminal_below_bottom"], xb + 0.01,
                  -s["terminal_width_model"] / 2, s["terminal_width_model"] / 2,
                  z - s["terminal_thickness"] / 2, z + s["terminal_thickness"] / 2)
        # 焊片孔的轴沿Z；三维端接仅作原厂尺寸名义示意。
        bore = cq.Solid.makeCylinder(0.8, 0.8, V(xb - 2.1, 0, z - 0.4), V(0, 0, 1))
        terminals.append(pin.cut(bore))
    rigid = single(rigid.fuse(*terminals), "开关本体及焊片名义模型")
    za = zl - s["action_from_left"]
    xp = xb + s["body_envelope_height"]
    xf = xb + s["free_height_max_from_bottom"]
    zp = zl - 3.4  # 未注铰链位置只作摆杆示意，不用于安装孔/动作点计算。
    lever = prism_xz([(xp, zp), (xf, za), (xf - s["lever_thickness"], za),
                       (xp - s["lever_thickness"], zp)],
                      -s["lever_width"] / 2, s["lever_width"] / 2)
    return rigid, lever, holes


def build_holder(cfg, holes):
    h = cfg["holder"]
    holder = box(*h["card_x"], *h["card_y"], *h["card_z"])
    holder = holder.fuse(box(*h["floor_x"], -h["inner_y"], h["inner_y"], *h["frame_z"]))
    for sign in (-1, 1):
        holder = holder.fuse(box(*h["wall_x"], sign * h["inner_y"], sign * h["outer_y"], *h["frame_z"]))
    # 两端定位挡边，安装孔螺钉约束Y方向，本体底面由平面托条定位X。
    holder = holder.fuse(box(*h["floor_x"], -h["outer_y"], h["outer_y"], -21.2, -19.6))
    holder = holder.fuse(box(*h["floor_x"], -h["outer_y"], h["outer_y"], 1.0, 2.5))
    for x, z in holes:
        holder = holder.fuse(cyl_y(x, z, h["boss_radius"], h["boss_y"][0], -h["inner_y"]))
        holder = holder.fuse(cyl_y(x, z, h["boss_radius"], h["inner_y"], h["boss_y"][1]))
        holder = holder.cut(cyl_y(x, z, h["screw_clearance_d"] / 2,
                                 h["boss_y"][0] - 0.1, h["boss_y"][1] + 0.1))
        holder = holder.cut(hex_y(x, z, h["nut_pocket_across_flats"], *h["nut_pocket_y"]))
    holder = holder.cut(box(h["card_x"][0] - 1, h["floor_x"][1] + 0.05,
                            -h["terminal_port_y_half"], h["terminal_port_y_half"], *h["terminal_port_z"]))
    # 中央焊线窗向底部延伸；保留两侧卡边与端部连接，不靠线束夹紧定位。
    holder = holder.cut(box(h["card_x"][0] - 0.1, h["card_x"][1] + 0.1,
                            -h["wire_exit_y_half"], h["wire_exit_y_half"], *h["wire_exit_z"]))
    return single(holder, "SS-01GL槽装固定支架")


def mount_screws(cfg, holes):
    h = cfg["holder"]
    bolts, nuts = [], []
    seat = h["boss_y"][1]
    for x, z in holes:
        shaft = cyl_y(x, z, 1, seat - h["screw_length"], seat)
        head = cyl_y(x, z, h["head_d"] / 2, seat, seat + h["head_height"])
        bolts.append(shaft.fuse(head))
        nut = hex_y(x, z, h["nut_across_flats"], h["boss_y"][0], h["boss_y"][0] + h["nut_height"])
        nuts.append(nut.cut(cyl_y(x, z, 1, h["boss_y"][0] - 0.1,
                                 h["boss_y"][0] + h["nut_height"] + 0.1)))
    return bolts, nuts


def export_part(shape, name, rotations):
    PRINT.mkdir(parents=True, exist_ok=True)
    step = PRINT / f"{name}.step"
    cq.exporters.export(cq.Workplane().add(shape), str(step))
    printed = shape
    for axis, angle in rotations:
        printed = printed.rotate((0, 0, 0), axis, angle)
    bb = printed.BoundingBox()
    printed = printed.translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
    stl = PRINT / f"{name}.stl"
    cq.exporters.export(cq.Workplane().add(printed), str(stl), tolerance=0.02, angularTolerance=0.1)
    clean_stl(stl)
    mesh = mesh_evidence(stl)
    if (mesh["connected_regions"] != 1 or mesh["boundary"]["count"]
            or mesh["non_manifold"]["count"] or mesh.get("zero_area_triangles")):
        raise ValueError(f"打印网格有缺陷：{name}")
    return {"volume_mm3": round(shape.Volume(), 3), "bounds_assembled_mm": bounds(shape),
            "step_sha256": digest(step), "stl_sha256": digest(stl),
            "mesh_regions": mesh["connected_regions"], "mesh_open_edges": mesh["boundary"]["count"],
            "mesh_non_manifold": mesh["non_manifold"]["count"],
            "print_bounds_mm": bounds(printed)}


def zero(name, amount):
    if amount > 0.001:
        raise ValueError(f"{name}存在实体干涉：{amount:.6f}立方毫米")


def move_daughter_slot(shell, cfg, side):
    """只替换壳内的小板卡槽肋；外侧壳壁、GY支架和扳机导向均保留。"""
    d = cfg["factory_daughter"]
    sign = 1 if side == "left" else -1
    z = d[f"rib_z_{side}"]
    yr = [sign * y for y in d["rib_y"]]
    ys = [sign * y for y in d["slot_y"]]
    old_rib = box(*d["rib_original_x"], *yr, *z)
    # 只删旧内肋的实际实体，不以大范围清空挖掉周围结构。
    removed = shell.intersect(old_rib)
    result = shell.cut(old_rib)
    offset = d["translation_x"]
    new_rib = box(*(x + offset for x in d["rib_original_x"]), *yr, *z)
    result = result.fuse(new_rib)
    slot = box(*(x + offset for x in d["slot_original_x"]), *ys, *d[f"slot_z_{side}"])
    result = single(result.cut(slot), side + "小板槽移位壳")
    return result, {"old_rib_removed_mm3": removed.Volume(),
                    "old_rib_roi_bounds": bounds(old_rib), "new_rib_bounds": bounds(new_rib),
                    "new_slot_bounds": bounds(slot), "source_switch_board_translation_x_mm": offset}


def continuous_translation_check(moving, stationary, travel):
    """距离界限证明连续平移区间：中点净距≥半区间长度即整区间不穿透。

    刚体沿X移动，任意点从区间中点移动的距离不超过半区间长度。
    端点的预期面接触允许；计算容差1e-7毫米。不是抽几个姿态冒充全行程。
    """
    bb = moving.BoundingBox()
    envelope = [bb.xmin - travel, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax]
    result = {}
    for name, other in stationary.items():
        ob = bounds(other)
        if any(envelope[k + 1] < ob[k] or ob[k + 1] < envelope[k] for k in (0, 2, 4)):
            result[name] = {"method": "完整行程包围盒不相交", "intervals": 1, "contacts_mm3": 0.0}
            continue
        stack = [(0.0, travel)]
        certified, minimum_margin, samples = [], float("inf"), 0
        for t in (0.0, travel):
            zero(name + "端点", volume_overlap(moving.translate(V(-t, 0, 0)), other))
        while stack:
            a, b = stack.pop()
            midpoint, radius = (a + b) / 2, (b - a) / 2
            posed = moving.translate(V(-midpoint, 0, 0))
            distance = float(posed.distance(other))
            samples += 1
            if distance + 1e-7 >= radius:
                certified.append([a, b, distance])
                minimum_margin = min(minimum_margin, distance - radius)
            else:
                zero(name + f"行程{midpoint:.6f}", volume_overlap(posed, other))
                if b - a < 1e-5:
                    raise ValueError(name + "连续位移检查未能取得足够净距界限，不能声称全行程通过")
                stack.extend([(a, midpoint), (midpoint, b)])
        result[name] = {"method": "中点实体距离界限覆盖整个平移区间", "intervals": len(certified),
                        "distance_evaluations": samples, "minimum_distance_bound_margin_mm": minimum_margin,
                        "arithmetic_tolerance_mm": 1e-7, "contacts_mm3": 0.0,
                        "certified_intervals_start_end_mid_distance_mm": sorted(certified)}
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg_path = ROOT / "config" / "economy-trigger.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    ev = load_ev(cfg)
    paths = {name: ROOT / path for name, path in cfg["source_shells"].items()}
    paths["trigger"] = ROOT / ev["base"]["trigger"]
    paths["board"] = Path(cfg["source_board"])
    paths["daughter"] = Path(cfg["source_daughter"])
    before = {name: {"path": str(path), "sha256": digest(path)} for name, path in paths.items()}
    left_source, right_source, trig_base = (cq.importers.importStep(str(paths[n])).val()
                                          for n in ("left", "right", "trigger"))
    left, left_shift = move_daughter_slot(left_source, cfg, "left")
    right, right_shift = move_daughter_slot(right_source, cfg, "right")
    relief = cfg["right_shell_relief"]
    right = single(right.cut(box(*relief["x"], *relief["y"], *relief["z"])), "右半壳-经济型")
    trigger = modify_trigger(trig_base, ev)
    rigid, lever, holes = switch_models(cfg)

    daughter_source = cq.importers.importStep(str(paths["daughter"])).val()
    daughter_solids = daughter_source.Solids()
    if len(daughter_solids) != 6:
        raise ValueError("原小板参考模型实体数改变，需重新识别板、连接器与旧开关")
    # 已逐实体读取原模型边界：0为实际PCB，1..3为J6，4为旧杠杆，5为旧本体。
    if not (bounds(daughter_solids[0])[:2] == [-20.6, -19.0]
            and bounds(daughter_solids[3])[4:] == [-34.0, -25.4]
            and bounds(daughter_solids[5])[4] > -20):
        raise ValueError("原小板实体边界改变，不能依旧索引替换开关")
    dx = cfg["factory_daughter"]["translation_x"]
    daughter_parts = [s.translate(V(dx, 0, 0)) for s in daughter_solids[:4]]
    daughter = cq.Compound.makeCompound(daughter_parts)
    card = box(cfg["factory_daughter"]["top_face_x"] - cfg["factory_daughter"]["thickness"],
               cfg["factory_daughter"]["top_face_x"], *cfg["factory_daughter"]["card_y"],
               *cfg["factory_daughter"]["card_z"])
    stationary = {"工厂焊接小板及J6": daughter, "SS01GL本体及焊片": rigid}
    mount_checks = {name: {"左壳": volume_overlap(part, left), "右壳": volume_overlap(part, right)}
                    for name, part in stationary.items()}
    for name, checks in mount_checks.items():
        for shell_name, amount in checks.items():
            zero(name + "与" + shell_name, amount)
    xb = cfg["switch"]["body_bottom_x"]
    pins_only = rigid.intersect(box(xb - 3.6, xb - 0.0001, -3.3, 3.3, -20.0, 1.0))
    pins_to_daughter = solid_contacts(pins_only, daughter)
    if pins_to_daughter:
        raise ValueError("名义开关焊片与原小板槽孔有穿透：" + json.dumps(pins_to_daughter, ensure_ascii=False))
    body_board_contact = rigid.intersect(daughter_parts[0])
    if body_board_contact.Volume() > 1e-6:
        bbc = body_board_contact.BoundingBox()
        if bbc.xmin < xb - 1e-7 or bbc.xmax > xb + 0.0001:
            raise ValueError("开关本体与小板出现超出名义贴面容差的穿透")
    print("两侧卡槽已移动；原小板、J6、SS01GL本体和三焊片检查完成", flush=True)

    ta, travel = ev["trigger_adjust"], cfg["trigger"]["travel_mm"]
    lo, hi = ta["adjust_range_mm"]
    checks = {}
    for delta in (lo, 0.0, hi):
        for angle in (0, 15, 30, 45, 60, 75, 90):
            zero("调节头与扳机槽", volume_overlap(screw_head(ta, delta, angle), trigger))
        for state, x in (("静止", 0.0), ("半程", -travel / 2), ("按到底", -travel)):
            moving = trigger.fuse(screw(ta, delta)).translate(V(x, 0, 0))
            checks[f"调节{delta:+.1f}_{state}"] = {
                name: volume_overlap(moving, part) for name, part in
                {"左壳": left, "右壳": right, **stationary}.items()}
            for name, amount in checks[f"调节{delta:+.1f}_{state}"].items():
                zero(state + name, amount)
            checks[f"调节{delta:+.1f}_{state}"]["名义自由摆杆_允许按压重叠"] = volume_overlap(moving, lever)
    continuous = continuous_translation_check(trigger, {"左壳": left, "右壳": right, **stationary}, travel)
    # 圆柱覆盖六角头所有旋转角度，以及行程与螺栓调整量的所有组合。
    head_radius = ta["head_across_flats"] / math.sqrt(3)
    head_sweep = cyl_x(ta["axis_y"], ta["axis_z"], head_radius,
                      ta["nominal_face_x"] - hi - travel,
                      ta["nominal_face_x"] - lo + ta["head_height"])
    shaft_sweep = cyl_x(ta["axis_y"], ta["axis_z"], 1,
                       ta["nominal_face_x"] - hi + ta["head_height"] - travel,
                       ta["nominal_face_x"] - lo + ta["head_height"] + ta["screw_length"])
    screw_envelope = head_sweep.fuse(shaft_sweep)
    screw_checks = {name: volume_overlap(screw_envelope, part)
                    for name, part in {"左壳": left, "右壳": right, **stationary}.items()}
    for name, amount in screw_checks.items():
        zero("螺栓全调节量和全行程包络与" + name, amount)
    local_head_envelope = cyl_x(ta["axis_y"], ta["axis_z"], head_radius,
                                ta["nominal_face_x"] - hi,
                                ta["nominal_face_x"] - lo + ta["head_height"])
    zero("六角头所有角度与扳机槽", volume_overlap(local_head_envelope, trigger))
    print("扳机连续全行程、螺栓全调整区间及所有头部转角完成检查", flush=True)

    pcb = cq.importers.importStep(str(paths["board"])).val()
    pcb_contacts = {name: solid_contacts(part, pcb) for name, part in stationary.items()}
    pcb_contacts["螺栓完整包络"] = solid_contacts(screw_envelope, pcb)
    if any(pcb_contacts.values()):
        raise ValueError("新开关小板或螺栓与原主板实体干涉：" + json.dumps(pcb_contacts, ensure_ascii=False))
    continuous["原主板及元件"] = continuous_translation_check(trigger, {"原主板及元件": pcb}, travel)["原主板及元件"]
    print("原主板参考模型检查完成", flush=True)

    retention = {}
    for axis, step in (("X", 0.4), ("Y", 1.1), ("Z", 0.6)):
        for sign in (-1, 1):
            v = {"X": (sign * step, 0, 0), "Y": (0, sign * step, 0), "Z": (0, 0, sign * step)}[axis]
            moved = card.translate(V(*v))
            contacts = {"左壳": volume_overlap(moved, left), "右壳": volume_overlap(moved, right)}
            retention[f"{axis}{sign*step:+.1f}"] = contacts
            if max(contacts.values()) < 0.001:
                raise ValueError(f"合壳后小板缺少{axis}{sign:+d}方向实体限位")
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
        check = {"压簧包络": volume_overlap(fork, spring),
                 **{n: volume_overlap(fork, p) for n, p in stationary.items()}}
        # 手柄伸出开壳面，片只在右壳单独装配时使用；合壳后必须撤片。
        check["右壳"] = volume_overlap(fork, right)
        for delta in (lo, 0.0, hi):
            moving = trigger.fuse(screw(ta, delta)).translate(V(-travel + thickness, 0, 0))
            check[f"扳机及螺栓_调节{delta:+.1f}"] = volume_overlap(fork, moving)
        for name, amount in check.items():
            zero(f"{thickness}毫米设定片与" + name, amount)
        fork_checks[str(thickness)] = check

    op_min, op_max = [cfg["switch"]["body_bottom_x"] + h
                      for h in cfg["switch"]["operating_height_from_bottom"]]
    needed_delta = [ta["nominal_face_x"] - travel + 1.0 - op_max,
                    ta["nominal_face_x"] - travel + 1.0 - op_min]
    if needed_delta[0] < lo or needed_delta[1] > hi:
        raise ValueError("设定片校准范围未覆盖原厂动作位置公差")
    calibration = {"method": ["工厂焊好小板放进右壳卡槽，装压簧和扳机，暂不合左壳；放入1.0毫米设定片",
                               "先完全松开，再按扳机至设定片；旋转M2螺栓，调到公共端与常开端刚刚导通",
                               "换0.8毫米片：先完全松开再按至片，应导通；换1.2毫米片：先完全松开再按至片，应不导通",
                               "撤片，按到底应导通；完全松手必须断开；合壳后重复检查"],
                   "required_delta_for_factory_OP_range_mm": needed_delta,
                   "overtravel_at_full_press_after_1mm_setting_mm": 1.0,
                   "body_gap_at_factory_lowest_OP_mm": op_min - 1.0 -
                       (cfg["switch"]["body_bottom_x"] + cfg["switch"]["body_flat_height"]),
                   "note": "每次设定片检查均从完全松开重新按下，避免开关回差；螺栓范围需人工校准，本机构没有防无限退出的挡圈"}
    parts = {"扳机-经济型": export_part(trigger, "扳机-经济型", [((1, 0, 0), 90)]),
             "左半壳-经济型": export_part(left, "左半壳-经济型", [((1, 0, 0), -90)]),
             "右半壳-经济型": export_part(right, "右半壳-经济型", [((1, 0, 0), 90)])}
    for thickness, fork in forks.items():
        name = f"扳机设定片-经济型-{thickness:.1f}mm"
        parts[name] = export_part(fork, name, [((0, 1, 0), -90)])
    for name, part in (("left", left), ("right", right), ("trigger", trigger), ("daughter-reference", daughter),
                       ("switch-rigid-nominal", rigid), ("switch-lever-fp-limit-nominal", lever)):
        cq.exporters.export(cq.Workplane().add(part), str(OUT / f"{name}.step"))
    assembly = cq.Assembly()
    for name, part, color in (("左半壳GY及SS槽改版", left, (0.8, 0.8, 0.8, 0.3)),
                              ("右半壳SS槽及触点避让", right, (0.7, 0.7, 0.7, 0.3)),
                              ("新扳机", trigger, (0.9, 0.5, 0.2, 1)),
                              ("工厂代焊小板及J6", daughter, (0.2, 0.6, 0.3, 1)),
                              ("SS01GL本体名义模型", rigid, (0.1, 0.1, 0.1, 1)),
                              ("SS01GL自由位置上限摆杆示意", lever, (0.7, 0.7, 0.7, 1)),
                              ("调节螺栓", screw(ta, 0), (0.6, 0.6, 0.6, 1))):
        assembly.add(part, name=name, color=cq.Color(*color))
    assembly.save(str(OUT / "SS01GL-工厂代焊小板与新扳机装壳参考.step"))
    after = {name: digest(path) for name, path in paths.items()}
    if any(after[name] != before[name]["sha256"] for name in paths):
        raise ValueError("读取的源文件在生成期间改变")
    report = {"manufacturing_finalized": False,
              "scope": "工厂代焊小板方案的实体连续行程、卡槽及网格检查；未打印、未装实物，实际SMT供货与代焊仍待下单审核",
              "source_files": before, "config_sha256": digest(cfg_path),
              "switch_model_boundary": cfg["switch"]["model_boundary"],
              "switch_coordinates_mm": {"hole_axes_XZ": holes,
                                          "action_Z": cfg["switch"]["body_left_z"] - cfg["switch"]["action_from_left"],
                                          "operating_X_range": [op_min, op_max]},
              "daughter_source_model_identification": {"PCB": 0, "J6": [1, 2, 3], "removed_original_lever": 4, "removed_original_switch": 5},
              "terminal_fit": {"protrusion_below_body_mm": 3.5, "PCB_thickness_mm": 1.6,
                               "protrusion_beyond_PCB_mm": 1.9, "nominal_terminal_thickness_width_mm": [0.5, 3.2],
                               "original_slot_thickness_width_mm": [1.0, 4.0], "terminal_to_actual_PCB_contacts": pins_to_daughter,
                               "body_board_nominal_face_contact_mm3": body_board_contact.Volume(),
                               "body_board_nominal_face_contact_tolerance_mm": 0.0001,
                               "note": "槽孔几何可穿入不等于工厂自动插件及焊接已接受；需SMT工厂审核"},
              "installed_stationary_contacts_mm3": mount_checks,
              "trigger_with_screw_contacts_mm3": checks, "continuous_trigger_translation_evidence": continuous,
              "screw_full_adjustment_and_motion_envelope_contacts_mm3": screw_checks,
              "board_contacts": pcb_contacts, "daughter_closed_shell_displacement_stops_mm3": retention,
              "independent_hard_stop_mm3": stop, "trigger_adjust_range_mm": [lo, hi],
              "setting_fork_contacts_mm3": fork_checks, "calibration": calibration,
              "old_positive_2mm_body_overlap_mm3": volume_overlap(trigger.fuse(screw(ta, 2.0)).translate(V(-travel, 0, 0)), rigid),
              "parts": parts, "preserved_features": cfg["trigger"]["preserved"],
              "shell_modification": {"left_slot": left_shift, "right_slot": right_shift, "right_head_relief": relief},
              "adjustment_is_mechanically_captive": False,
              "adjustment_boundary": "壳体实体硬止挡限制扳机行程；调节螺栓由设定片和导通测试校准，没有防无限退出的机械挡圈"}
    (OUT / "几何检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(OUT / "几何检查.json"), "parts": parts}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
