r"""新增 GY 模块刚性固定结构，不覆盖原外壳、PCB、程序或工程样。

运行：E:\GunMouseCAD\CadQuery\python.exe -B scripts\economy_mechanical.py
输出新增左半壳中间件与模块压框，右半壳/扳机最终改动由整合脚本处理。
"""
import hashlib
import json
import sys
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
from build_shell import box, cyl_y, prism_xz  # noqa: E402
from clean_stl_zero_area import clean as clean_stl  # noqa: E402
from verify_mechanical import mesh_evidence  # noqa: E402

V = cq.Vector
OUT = ROOT / "outputs" / "economy-mechanical"
PRINT = ROOT / "deliverables" / "经济型改版" / "打印文件"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounds(shape):
    b = shape.BoundingBox()
    return [b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax]


def disjoint(a, b):
    return any(a[k + 1] <= b[k] or b[k + 1] <= a[k] for k in (0, 2, 4))


def overlap(a, b):
    if disjoint(bounds(a), bounds(b)):
        return 0.0
    return max(0.0, float(a.intersect(b).Volume()))


def obstruction_volume(a, solids):
    ab = bounds(a)
    total = 0.0
    for solid, bb in solids:
        if not disjoint(ab, bb):
            total += overlap(a, solid)
    return total


def fused(items):
    result = items[0]
    for shape in items[1:]:
        result = result.fuse(shape)
    return result.clean()


def single(shape, name):
    shape = shape.clean()
    if not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError(f"{name}必须为有效单实体")
    return shape


def wire_boxes(points, width):
    shapes = []
    r = width / 2
    for a, b in zip(points, points[1:]):
        delta = [abs(b[i] - a[i]) for i in range(3)]
        if sum(d > 1e-8 for d in delta) != 1:
            raise ValueError("线束包络每段必须沿单一坐标轴")
        ext = [(min(a[i], b[i]) - r, max(a[i], b[i]) + r) for i in range(3)]
        shapes.append(box(*ext[0], *ext[1], *ext[2]))
    return cq.Compound.makeCompound(shapes)


def build_module(e):
    m = e["module"]
    x, z = m["center_xz"]
    hx, hz = m["length_x"] / 2, m["height_z"] / 2
    top = m["component_face_y"]
    back = top - m["board_thickness_assumed"]
    pcb = box(x - hx, x + hx, back, top, z - hz, z + hz)
    # 中央元件用比说明书2.8总高更保守的2.8前向高度；四周0.8裸边用于绝缘定位。
    components = box(x - hx + 0.8, x + hx - 0.8, top, top + m["front_component_allowance"],
                     z - hz + 0.8, z + hz - 0.8)
    front_pins, back_pins = [], []
    for sign in (-1, 1):
        row = z + sign * 7.62
        front_pins.append(box(x - 8.89 - 1.27, x + 8.89 + 1.27,
                              top, top + m["front_pin_allowance"], row - 1.27, row + 1.27))
        for index in range(8):  # 两排均按最多8针检查，比实物8+6针更保守，不猜未标孔位。
            xx = x + 8.89 - 2.54 * index
            back_pins.append(cyl_y(xx, row, m["back_pin_radius"], back - m["back_pin_allowance"], back))
    body = cq.Compound.makeCompound([pcb, components, *front_pins, *back_pins])
    return pcb, body


def build_support(left, e, shell_cfg):
    m, c = e["module"], e["clamp"]
    x, z = m["center_xz"]
    x0, x1 = x - m["length_x"] / 2, x + m["length_x"] / 2
    z0, z1 = z - m["height_z"] / 2, z + m["height_z"] / 2
    front = m["component_face_y"]
    end = shell_cfg["shell"]["half_width_y"] - shell_cfg["shell"]["wall"] + 0.3
    grip, gap = m["edge_grip"], m["xy_edge_clearance"]
    # 两条前向限位轨只压PCB两端裸边的中段，避开排针行，不使用未标注的模块孔位。
    features = [box(x0 - 1.1, x0 + grip, front, end, z - 5.0, z + 5.0),
                box(x1 - grip, x1 + 1.4, front, end, z - 5.0, z + 5.0),
                box(x0 - 1.1, x0 - gap, front - 0.8, end, z - 5.0, z + 5.0),
                box(x1 + gap, x1 + 1.4, front - 0.8, end, z - 5.0, z + 5.0),
                box(x - 4.3, x + 4.3, front - 0.8, end, z0 - gap - 0.5, z0 - gap),
                box(x - 4.3, x + 4.3, front - 0.8, end, z1 + gap, z1 + gap + 0.8)]
    for xx, zz in c["mounts_xz"]:
        features.append(cyl_y(xx, zz, c["boss_radius"], c["boss_start_y"], end))
    # 横梁为2毫米小扎带提供穿带通道，线束夹在梁的背面，不靠胶固定。
    anchor = box(-0.6, 0.6, 9.6, end, 12.0, 18.0)
    anchor = anchor.cut(box(-0.7, 0.7, 10.8, 13.0, 13.6, 16.4))
    features.append(anchor)
    additions = cq.Compound.makeCompound(features)
    # 上定位轨/螺柱可能跨入顶壁，只允许保留在原壳外轮廓内的新增塑料。
    from build_shell import Shell
    envelope = Shell(shell_cfg).outer
    features = [feature.intersect(envelope) for feature in features]
    modified = fused([left, *features])
    for xx, zz in c["mounts_xz"]:
        modified = modified.cut(cyl_y(xx, zz, c["screw_pilot_d"] / 2,
                                      c["boss_start_y"] - 0.1, end - 0.3))
    return single(modified, "GY适配左半壳"), additions


def build_clamp(e, board_thickness=None):
    m, c = e["module"], e["clamp"]
    x, z = m["center_xz"]
    x0, x1 = x - m["length_x"] / 2, x + m["length_x"] / 2
    z0, z1 = z - m["height_z"] / 2, z + m["height_z"] / 2
    board_thickness = board_thickness or m["board_thickness_assumed"]
    front = m["component_face_y"] - board_thickness
    back = front - c["thickness"]
    # 窗口完全让开两排焊针；仅0.6毫米两端裸边承受压框，芯片/主处理器均不受压。
    frame = fused([
        box(x0 - 1.1, x0 - m["xy_edge_clearance"], back, front, z0 - 0.4, z1 + 1.8),
        box(x1 + m["xy_edge_clearance"], x1 + 1.2, back, front, z0 - 0.4, z1 + 1.8),
        box(x0 - 1.1, x0 + m["edge_grip"], back, front, z - 5.0, z + 5.0),
        box(x1 - m["edge_grip"], x1 + 1.2, back, front, z - 5.0, z + 5.0),
        box(x0 - 1.1, x1 + 1.2, back, front, z0 - 0.8, z0),
        box(x0 - 1.1, x1 + 1.2, back, front, z1 + 0.2, z1 + 1.8),
        *[cyl_y(xx, zz, c["mount_pad_radius"], back, front) for xx, zz in c["mounts_xz"]],
    ])
    for xx, zz in c["mounts_xz"]:
        frame = frame.cut(cyl_y(xx, zz, c["screw_clearance_d"] / 2, back - 0.1, front + 0.1))
    # 压框背面凸箭头指向枪前(+X)；前下角缺口标记Pin1所在端，安装图同时注明芯片朝+Y。
    arrow = prism_xz([(x - 2.6, z0 - 0.55), (x + 0.8, z0 - 0.55),
                       (x + 0.8, z0 - 0.7), (x + 2.0, z0 - 0.4),
                       (x + 0.8, z0 - 0.1), (x + 0.8, z0 - 0.25),
                       (x - 2.6, z0 - 0.25)], back - 0.4, back + 0.01)
    frame = frame.fuse(arrow)
    frame = frame.cut(box(x1 - 2.0, x1 - 1.2, back - 0.5, front + 0.1, z0 - 0.9, z0 - 0.5))
    return single(frame, "GY模块压框")


def screw_heads(e, board_thickness):
    m, c = e["module"], e["clamp"]
    front = m["component_face_y"] - board_thickness - c["thickness"]
    return cq.Compound.makeCompound([cyl_y(x, z, c["screw_head_radius"],
                                           front - c["screw_head_height"], front)
                                     for x, z in c["mounts_xz"]])


def export_print(shape, name, angle):
    PRINT.mkdir(parents=True, exist_ok=True)
    step, stl = PRINT / f"{name}.step", PRINT / f"{name}.stl"
    cq.exporters.export(shape, str(step))
    printed = shape.rotate((0, 0, 0), (1, 0, 0), angle)
    bb = printed.BoundingBox()
    printed = printed.translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
    cq.exporters.export(printed, str(stl), tolerance=0.02, angularTolerance=0.1)
    clean_stl(stl)
    mesh = mesh_evidence(stl)
    if (mesh["connected_regions"] != 1 or mesh["boundary"]["count"] or
            mesh["non_manifold"]["count"] or mesh.get("zero_area_triangles")):
        raise ValueError(f"{name}打印网格有缺陷")
    bb = printed.BoundingBox()
    return {"step": str(step.relative_to(ROOT)), "stl": str(stl.relative_to(ROOT)),
            "step_sha256": digest(step), "stl_sha256": digest(stl),
            "valid_solid": bool(shape.isValid()), "solid_count": len(shape.Solids()),
            "mesh_connected_regions": mesh["connected_regions"],
            "mesh_open_edges": mesh["boundary"]["count"],
            "mesh_non_manifold_edges": mesh["non_manifold"]["count"],
            "print_size_mm": [round(bb.xlen, 3), round(bb.ylen, 3), round(bb.zlen, 3)]}


def render_preview(items, name, focal, position, scale, lines):
    # 只渲染新生成的CAD实体，未截取用户屏幕。
    from io import BytesIO
    import vtk
    from PIL import Image, ImageDraw, ImageFont
    ren = vtk.vtkRenderer()
    ren.SetBackground(0.97, 0.97, 0.98)
    ren.SetUseDepthPeeling(True)
    ren.SetMaximumNumberOfPeels(60)
    for shape, color, opacity in items:
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(shape.toVtkPolyData(tolerance=0.05, angularTolerance=0.2, normals=True))
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetOpacity(opacity)
        ren.AddActor(actor)
    camera = ren.GetActiveCamera()
    camera.SetFocalPoint(*focal)
    camera.SetPosition(*position)
    camera.SetViewUp(0, 0, 1)
    camera.ParallelProjectionOn()
    camera.SetParallelScale(scale)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetAlphaBitPlanes(1)
    win.SetMultiSamples(0)
    win.SetSize(1400, 1000)
    win.AddRenderer(ren)
    win.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetWriteToMemory(1)
    writer.SetInputConnection(grab.GetOutputPort())
    writer.Write()
    image = Image.open(BytesIO(bytes(writer.GetResult()))).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("msyh.ttc", 24)
    draw.rectangle((10, 10, 1390, 24 + 34 * len(lines)), fill="white")
    for i, text in enumerate(lines):
        draw.text((24, 17 + 34 * i), text, font=font, fill=(35, 35, 35))
    path = OUT / name
    image.save(path)
    win.Finalize()
    return str(path.relative_to(ROOT))


def wiring_diagram():
    """新绘工程接线示意，不编辑资料照片；真实孔位以实物丝印为准。"""
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1400, 1040), (248, 249, 252))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("msyh.ttc", 25)
    small = ImageFont.truetype("msyh.ttc", 22)
    title = ImageFont.truetype("msyh.ttc", 33)
    draw.text((40, 24), "GY模块：固定朝向与四线接法", font=title, fill=(25, 32, 40))
    draw.text((40, 77), "从元件面看：芯片面朝枪左侧 +Y；枪前 +X 在图左，枪上 +Z 在图上", font=font, fill=(35, 45, 60))
    draw.text((40, 112), "接线图的孔位仅示意，焊接认实物丝印；压框从另一面看时箭头朝图右", font=small, fill=(65, 75, 90))
    draw.line((260, 188, 100, 188), fill=(45, 83, 120), width=6)
    draw.polygon([(100, 188), (125, 172), (125, 204)], fill=(45, 83, 120))
    draw.text((280, 167), "枪前 +X", font=font, fill=(45, 83, 120))
    draw.rounded_rectangle((160, 255, 1240, 620), radius=15, fill=(121, 70, 158), outline=(65, 31, 93), width=3)
    draw.rounded_rectangle((485, 365, 820, 486), radius=10, fill=(45, 45, 48), outline=(220, 220, 225), width=2)
    draw.text((520, 389), "芯片元件面朝 +Y", font=font, fill="white")
    draw.text((190, 282), "PS 悬空：读原芯片接口", font=font, fill="white")
    draw.text((190, 322), "不接模块板上处理器的数据接口", font=small, fill=(238, 224, 248))
    names = ["1 VCC", "2 GND", "3 SCL", "4 SDA", "5 SA0", "6 CS", "7 INT1", "8 INT2"]
    colors = [(210, 55, 45), (45, 45, 45), (184, 132, 12), (45, 103, 205), (35, 147, 85), (115, 115, 125), (115, 115, 125), (115, 115, 125)]
    xs = [215 + 140 * i for i in range(8)]
    for xx, name, color in zip(xs, names, colors):
        draw.ellipse((xx - 17, 560, xx + 17, 594), fill=(244, 206, 100), outline=(65, 45, 10), width=2)
        draw.ellipse((xx - 8, 569, xx + 8, 585), fill=(50, 50, 60))
        draw.text((xx - 44, 629), name, font=small, fill=color)
    draw.line([(xs[1], 593), (xs[1], 705), (xs[4], 705), (xs[4], 593)], fill=colors[4], width=5)
    draw.text((405, 720), "短线：5 SA0 → 2 GND，地址 0x6A", font=font, fill=colors[4])
    labels = ["J1-1  → 1 VCC（3.3V）", "J1-22 → 2 GND（地）", "J1-15 → 3 SCL（GPIO9）", "J1-12 → 4 SDA（GPIO8）"]
    for i, (text, color) in enumerate(zip(labels, colors[:4])):
        draw.text((70 + (i % 2) * 690, 785 + (i // 2) * 45), text, font=font, fill=color)
    draw.text((70, 900), "CS已自带上拉；INT1/INT2不用接。四线及SA0短线先在壳外焊好。", font=font, fill=(40, 45, 55))
    draw.text((70, 945), "模块长边沿枪前后；1号电源脚（VCC）在枪前下角。元件面朝左壳内壁。", font=font, fill=(40, 45, 55))
    draw.text((70, 985), "配套主板的 U1、R10、R11 留空；模块已自带数据线与时钟线的上拉电阻。", font=small, fill=(40, 45, 55))
    path = OUT / "GY模块朝向与接线.png"
    image.save(path)
    return str(path.relative_to(ROOT))


def installation_note():
    note = """GY模块固定与接线装配步骤（与经济型左半壳配套）

配套主板的U1传感器及R10、R11上拉电阻必须不装元件；模块内部已有总线上拉电阻，原U1与模块不能同时接入。

1. 先核对模块实物：GY-601N1、芯片LSM6DSV16X；板面20.6×17.8毫米，板厚0.8～1.6毫米。模块元件前突出不超过2.8毫米，前方排针/塑料座突出不超过6毫米，背针不超过4毫米，背面焊点最大直径2毫米。不使用杜邦插头；超出尺寸应先改配置，不能强塞。
2. 模块先在壳外接四根外径不大于0.6毫米的绝缘多股线：J1-1→电源VCC、J1-22→地GND、J1-12→原芯片串行数据线SDA（4号脚）、J1-15→原芯片串行时钟线SCL（3号脚）。模块5号地址脚SA0用绝缘短线接2号地GND。模式选择脚PS悬空，不焊模式选择跳线；片选脚CS已有上拉，中断不用接。对针脚只认模块实物丝印，不凭示意图左右焊线。
3. 模块芯片和板上处理器朝左半壳内壁，即整机左侧+Y。长边沿枪前后，1号电源脚VCC在枪前下角(+X,-Z)。放入左壳四向定位轨，模块两端裸边靠住前向限位轨；不用模块两大孔，也不用胶粘。
4. 压框从模块背面装上。框上箭头指枪前(+X)，前下角缺口对应电源VCC端。用两颗PA2×10盘头自攻螺丝；头径不大于4毫米。两颗交替轻拧，直到电路板不晃动；不需把压框拧到螺柱端面，夹框随0.8～1.6板厚锁紧。
5. J1四线只焊排母背面的大通孔焊点，不碰裸传感器小焊盘，也不塞进排母插口。电路板背面在排母下方沿z=12.3汇线，到x=0处再降到z=8绕过主板下缘，不能在枪前沿z=8绕线（会碰下壳壁）。绕过板边后抬到模块接口，留适量拆壳弯线；用2毫米小扎带锁到左壳横梁，不经过触摸铜箔或天线区正面。
6. 先完成模块固定和接线，再装主板、插入开发板、装右壳。合壳前检查线不在螺柱、接缝及摇杆活动区；模块芯片面不能翻转，压框必须确实夹住电路板裸边，元件和焊针不能承受夹框压力。
7. 该打印件和规定包络已做静态实体与闭合网格检查，尚未打印和装实物。通电后必须验证模块地址0x6A、芯片标识0x70、静置校准、抬头光标上移及右转光标右移。俯仰方向来自芯片Z朝+Y，偏航来自重力投影，故平面内旋转不需改原程序。

几何依据：模块说明书第1、2页；LSM6DSV16X芯片手册第9页；原程序imu_logic.h中的pitch=g.z和yaw=dot(g,up)。针高/焊线实物仍需按上述尺寸核对。模型背针按两行最多8针作保守检查，真实模块8+6针以丝印为准。
"""
    path = OUT / "GY模块安装核对.txt"
    path.write_text(note, encoding="utf-8")
    return str(path.relative_to(ROOT))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    config_path = ROOT / "config" / "economy-mechanical.json"
    e = json.loads(config_path.read_text(encoding="utf-8"))
    shell_cfg = json.loads((ROOT / "config" / "pcb-shell-v1.json").read_text(encoding="utf-8"))
    base_paths = {"left": ROOT / e["base_left"], "right": ROOT / e["base_right"]}
    model_dir = Path(e["source_models"])
    refs = {name: model_dir / f"{name}.step" for name in ("pcb", "dev", "knob", "battery")}
    all_sources = {**base_paths, **refs}
    before = {str(p): digest(p) for p in all_sources.values()}
    load = lambda path: cq.importers.importStep(str(path)).val()
    left0, right = load(base_paths["left"]), load(base_paths["right"])
    print("读取原壳与装配参考体", flush=True)
    models = {name: load(path) for name, path in refs.items()}
    board_solids = [(s, bounds(s)) for s in models["pcb"].Solids()]
    print(f"主板参考实体数量：{len(board_solids)}", flush=True)
    left, additions = build_support(left0, e, shell_cfg)
    clamp = build_clamp(e)
    module_pcb, module_envelope = build_module(e)
    wires = wire_boxes(e["wires"]["route_global"], e["wires"]["bundle_envelope_side"])
    refs_simple = {"左壳": left, "右壳": right, "开发板": models["dev"], "电池": models["battery"]}
    checks = {}
    for name, part in (("模块及允许针脚包络", module_envelope), ("压框", clamp), ("规定线束包络", wires)):
        row = {key: round(overlap(part, obstacle), 6) for key, obstacle in refs_simple.items()}
        row["主板含原器件保守模型"] = round(obstruction_volume(part, board_solids), 6)
        checks[name] = row
    checks["新增左壳结构"] = {
        "主板含原器件保守模型": round(obstruction_volume(additions, board_solids), 6),
        "开发板": round(overlap(additions, models["dev"]), 6),
        "右壳": round(overlap(additions, right), 6)}
    # 支撑接触PCB边缘应为共面接触，没有实体交叠。夹框按0.8~1.6板厚可整体前后移动锁紧。
    checks["模块PCB与压框"] = round(overlap(module_pcb, clamp), 6)
    thickness_checks = {}
    for thickness in e["module"]["board_thickness_supported"]:
        moved = build_clamp(e, thickness)
        heads = screw_heads(e, thickness)
        variant = {**e, "module": {**e["module"], "board_thickness_assumed": thickness}}
        _, variant_envelope = build_module(variant)
        thickness_checks[str(thickness)] = {
            "压框与左壳": round(overlap(moved, left), 6),
            "螺丝头与左壳": round(overlap(heads, left), 6),
            "螺丝头与开发板": round(overlap(heads, models["dev"]), 6),
            "螺丝头与主板": round(obstruction_volume(heads, board_solids), 6),
            "压框与主板": round(obstruction_volume(moved, board_solids), 6),
            "压框与开发板": round(overlap(moved, models["dev"]), 6),
            "模块包络与左壳": round(overlap(variant_envelope, left), 6),
            "模块包络与右壳": round(overlap(variant_envelope, right), 6),
            "模块包络与主板": round(obstruction_volume(variant_envelope, board_solids), 6),
            "模块包络与开发板": round(overlap(variant_envelope, models["dev"]), 6),
            "模块包络与压框": round(overlap(variant_envelope, moved), 6)}
    joystick = shell_cfg["joystick"]
    pivot = V(joystick["shaft_xz"][0], shell_cfg["board"]["top_face_y"] + joystick["pivot_above_pcb_assumed"],
              joystick["shaft_xz"][1])
    knob_checks = {}
    for axis_name, axis in (("X", V(1, 0, 0)), ("Z", V(0, 0, 1))):
        for angle in (-20, 20):
            moved = models["knob"].rotate(pivot, pivot + axis, angle)
            knob_checks[f"{axis_name}轴{angle}度"] = {
                "模块包络": round(overlap(moved, module_envelope), 6),
                "压框": round(overlap(moved, clamp), 6),
                "新增支撑": round(overlap(moved, additions), 6)}
    report = {
        "manufacturing_finalized": False,
        "scope": "原壳实体+原主板和器件实体+开发板参考体+模块规格及针脚包络+实际新增压框的静态几何检查；尚未打印和装实物",
        "module_model_note": "使用说明书板外形，不猜两大孔中心；元件前向留2.8毫米，前针留6、背针留4及焊点直径2毫米。压框只在中段压裸边，两排针所在高度退让。开发板厚度/元件高度沿原工程假设。主板参考体仍含原U1等留空器件，作为更保守的障碍检查，不代表候选实际安装清单。",
        "config_sha256": digest(config_path), "source_sha256": before,
        "module_bounds": bounds(module_envelope), "clamp_bounds": bounds(clamp),
        "collision_mm3": checks, "board_thickness_checks_mm3": thickness_checks,
        "joystick_tilt_checks_mm3": knob_checks,
        "axis_evidence": e["module"]["orientation"],
        "wire_route": e["wires"],
        "source_unchanged": before == {str(p): digest(p) for p in all_sources.values()},
    }
    (OUT / "几何检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    values = [v for row in checks.values() if isinstance(row, dict) for v in row.values()]
    values += [v for row in thickness_checks.values() for v in row.values()]
    values += [v for row in knob_checks.values() for v in row.values()]
    values += [checks["模块PCB与压框"]]
    if max(values) > 1e-3:
        raise ValueError(f"几何检查发现交叠，见{OUT / '几何检查.json'}")
    report["print_parts"] = {
        "左半壳-经济型": export_print(left, "左半壳-经济型", -90),
        "GY模块压框": export_print(clamp, "GY模块压框", -90)}
    for name, shape in (("left-gy", left), ("gy-clamp", clamp), ("gy-module-envelope", module_envelope), ("gy-wire-route", wires)):
        cq.exporters.export(shape, str(OUT / f"{name}.step"))
    assembly = cq.Assembly()
    for name, shape, color in (("left_gy", left, (0.72, 0.79, 0.89)), ("right", right, (0.6, 0.65, 0.72)),
                                ("main", models["pcb"], (0.1, 0.45, 0.2)), ("dev", models["dev"], (0.25, 0.25, 0.25)),
                                ("module_envelope", module_envelope, (0.48, 0.22, 0.72)),
                                ("module_clamp", clamp, (0.98, 0.59, 0.12)), ("wire_route", wires, (0.9, 0.2, 0.18))):
        assembly.add(shape, name=name, color=cq.Color(*color))
    assembly.save(str(OUT / "GY固定装配.step"))
    print("几何通过，正在渲染局部装配图", flush=True)
    clip = box(-48, 10, -25, 25, 5, 45)
    local_pcb = cq.Compound.makeCompound([s for s, bb in board_solids if not disjoint(bb, bounds(clip))])
    local_left = left.intersect(clip)
    items = [(local_left, (0.6, 0.73, 0.87), 0.28), (local_pcb, (0.13, 0.44, 0.2), 0.18),
             (models["dev"], (0.24, 0.24, 0.27), 0.3),
             (module_envelope, (0.52, 0.24, 0.7), 0.7), (clamp, (0.96, 0.61, 0.12), 1.0),
             (wires, (0.84, 0.15, 0.12), 0.75)]
    report["previews"] = [render_preview(items, "GY模块局部装配.png", (-11.7, 7, 28), (-80, -140, 75), 26,
                                         ["已有 GY 模块：紫色为板、元件及最大允许针脚包络",
                                          "橙色压框从主板一侧装入，两颗 PA2×10 螺丝固定；蓝色为适配左壳",
                                          "芯片元件面朝整机左侧 +Y；Pin1在枪前下角；红色是线束路线包络"])]
    report["previews"].append(render_preview([(local_left, (0.6, 0.73, 0.87), 0.45),
                                             (module_envelope, (0.52, 0.24, 0.7), 0.65),
                                             (clamp, (0.96, 0.61, 0.12), 1.0)],
                                            "GY模块压框与左壳.png", (-11.7, 11, 28), (-11.7, -160, 28), 20,
                                            ["从开壳面看模块背面；压框窗口让开焊针，靠PCB裸边固定",
                                             "箭头指向枪前 +X；前下角缺口标Pin1；实际芯片应在压框另一面朝+Y",
                                             "不依赖未标注模块孔位；板厚0.8～1.6可通过拧紧压框适应"] ))
    report["previews"].append(wiring_diagram())
    report["installation_steps"] = installation_note()
    (OUT / "几何检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(OUT / "几何检查.json"), "print_parts": report["print_parts"],
                      "all_static_collisions_zero": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
