"""Create a separate Blender preview with individually named parts and labels.

Run with Blender 5.2:
  blender.exe --background shell/第二版外壳_三色预览.blend --python tools/create_labeled_assembly_preview.py

This edits only the generated preview file. The original and three-color preview
remain untouched. Model-space transforms follow tools/build_gen2_mount.py.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shell" / "第二版外壳_三色预览.blend"
OUTPUT = ROOT / "shell" / "第二版外壳_器件标注预览.blend"
CONFIG_PATH = ROOT / "pcb" / "carrier-config.json"
CHECK_PATH = ROOT / "shell" / "assembly-check.json"
FONT_PATH = Path(r"C:\Windows\Fonts\simhei.ttf")

PART_LABELS = {
    "SW1": ("摇杆", "SW1", "RKJXV1224005", "摇杆视角输入", "控制视角"),
    "SW2": ("右键微动开关", "SW2", "D2FC-F-7N(20M)", "鼠标右键", "右键触发"),
    "J_MCU": ("主控焊线组", "J_MCU", "焊接导线", "连接到ESP32-S3主控", "主控信号连接"),
    "J_GY": ("陀螺仪焊线组", "J_GY", "焊接导线", "连接陀螺仪模块", "传感器信号连接"),
    "J_TRIG": ("扳机焊线组", "J_TRIG", "焊接导线", "连接SS-01GL扳机开关", "扳机信号连接"),
    "J_TOUCH": ("触摸箔焊线组", "J_TOUCH", "焊接导线", "连接绝缘触摸箔", "触摸输入"),
    "J_BAT": ("电池输入线", "J_BAT", "焊接导线", "单节保护锂电池输入", "电池供电"),
    "J_SWITCH": ("电源拨动开关", "J_SWITCH", "SS-12D01-G030", "电池正极总开关", "整机电源开关"),
    "J_MODULE_BAT": ("主控电池线", "J_MODULE_BAT", "焊接导线", "连接主控B+与B-焊盘", "主控供电"),
    "J_MODULE_RAIL": ("主控5V检测线", "J_MODULE_RAIL", "焊接导线", "检测主控5V共用电源轨", "电源状态检测"),
    "R_JOY": ("3.3kΩ电阻", "R_JOY", "3.3kΩ", "摇杆按键上拉", "摇杆按键上拉"),
    "R_RIGHT": ("3.3kΩ电阻", "R_RIGHT", "3.3kΩ", "右键上拉", "右键上拉"),
    "R_TRIG": ("3.3kΩ电阻", "R_TRIG", "3.3kΩ", "扳机回路限流", "扳机输入"),
    "R_TOUCH": ("510Ω电阻", "R_TOUCH", "510Ω", "触摸输入串联限流", "触摸输入保护"),
    "R_BAT_H": ("100kΩ电阻", "R_BAT_H", "100kΩ", "电池电压分压上臂", "电池电压采样"),
    "R_BAT_L": ("100kΩ电阻", "R_BAT_L", "100kΩ", "电池电压分压下臂", "电池电压采样"),
    "R_RAIL_H": ("100kΩ电阻", "R_RAIL_H", "100kΩ", "5V电源分压上臂", "共用电源轨检测"),
    "R_RAIL_L": ("100kΩ电阻", "R_RAIL_L", "100kΩ", "5V电源分压下臂", "共用电源轨检测"),
    "C_JOY_X": ("100nF电容", "C_JOY_X", "100nF（0.1µF）", "摇杆X轴滤波", "摇杆X轴滤波"),
    "C_JOY_Y": ("100nF电容", "C_JOY_Y", "100nF（0.1µF）", "摇杆Y轴滤波", "摇杆Y轴滤波"),
    "C_JOY_SW": ("100nF电容", "C_JOY_SW", "100nF（0.1µF）", "摇杆按键滤波", "摇杆按键滤波"),
    "C_RIGHT": ("100nF电容", "C_RIGHT", "100nF（0.1µF）", "右键滤波", "右键滤波"),
    "C_TRIG": ("100nF电容", "C_TRIG", "100nF（0.1µF）", "扳机输入滤波", "扳机输入滤波"),
    "C_BAT": ("100nF电容", "C_BAT", "100nF（0.1µF）", "电池电压采样滤波", "电池采样滤波"),
    "C_RAIL": ("100nF电容", "C_RAIL", "100nF（0.1µF）", "5V电源检测滤波", "电源检测滤波"),
}

PALETTE = {
    "capacitor": ((0.02, 0.36, 0.96, 1), "light"),
    "resistor": ((0.93, 0.25, 0.08, 1), "light"),
    "switch": ((0.58, 0.23, 0.82, 1), "light"),
    "wire": ((1.0, 0.74, 0.08, 1), "dark"),
    "module": ((0.04, 0.68, 0.58, 1), "dark"),
    "battery": ((0.86, 0.12, 0.17, 1), "light"),
    "hardware": ((0.69, 0.76, 0.83, 1), "dark"),
}


def world_bounds(obj):
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    mins = [min(point[i] for point in points) for i in range(3)]
    maxs = [max(point[i] for point in points) for i in range(3)]
    dims = tuple(maxs[i] - mins[i] for i in range(3))
    center = tuple((maxs[i] + mins[i]) * 0.5 for i in range(3))
    return dims, center, tuple(mins), tuple(maxs)


def move_to_collection(obj, collection):
    for old in list(obj.users_collection):
        old.objects.unlink(obj)
    collection.objects.link(obj)


def board_envelope(envelope, x_offset, z_flip_max, board_top_y, base_y):
    above = envelope.get("y_above_board", 0)
    low, high = above if isinstance(above, list) else (0, above)
    if envelope.get("kind") == "cylinder_y":
        x, z = envelope["xz"]
        radius = envelope["radius"]
        dims = (radius * 2, radius * 2, high - low)
        center_x, center_z = x, z
    else:
        x0, x1 = envelope["x"]
        z0, z1 = envelope["z"]
        dims = (x1 - x0, z1 - z0, high - low)
        center_x, center_z = (x0 + x1) / 2, (z0 + z1) / 2
    center = (
        center_x + x_offset,
        z_flip_max - center_z,
        board_top_y + (low + high) / 2 - base_y,
    )
    return dims, center


def assembly_box(box, x_offset, z_flip_max, base_y):
    x0, x1, y0, y1, z0, z1 = box
    dims = (x1 - x0, z1 - z0, y1 - y0)
    center = (
        (x0 + x1) / 2 + x_offset,
        z_flip_max - (z0 + z1) / 2,
        (y0 + y1) / 2 - base_y,
    )
    return dims, center


def assembly_cylinder(x, z, radius, y0, y1, x_offset, z_flip_max, base_y):
    return (
        (radius * 2, radius * 2, y1 - y0),
        (x + x_offset, z_flip_max - z, (y0 + y1) / 2 - base_y),
    )


def assembly_hex_nut(x, z, y0, y1, x_offset, z_flip_max, base_y):
    across_corners = 4 / math.sqrt(3) * 2
    return (
        (across_corners, 4, y1 - y0),
        (x + x_offset, z_flip_max - z, (y0 + y1) / 2 - base_y),
    )


def expected_for_part(part, x_offset, z_flip_max, board_top_y, base_y):
    envelopes = part.get("envelopes")
    if envelopes is None:
        envelope = part.get("envelope")
        envelopes = [envelope] if envelope else []
    return [
        board_envelope(env, x_offset, z_flip_max, board_top_y, base_y)
        for env in envelopes
    ]


def find_mesh(candidates, target, dim_tolerance=0.2, center_tolerance=0.25):
    target_dims, target_center = target
    ranked = []
    for obj in candidates:
        dims, center, _, _ = world_bounds(obj)
        dim_error = tuple(abs(dims[i] - target_dims[i]) for i in range(3))
        center_error = tuple(abs(center[i] - target_center[i]) for i in range(3))
        score = sum(dim_error) + sum(center_error)
        ranked.append((score, obj, dim_error, center_error))
    if not ranked:
        return None
    _, obj, dim_error, center_error = min(ranked, key=lambda item: item[0])
    if max(dim_error) > dim_tolerance or max(center_error) > center_tolerance:
        return None
    candidates.remove(obj)
    return obj


def make_dark_material():
    material = bpy.data.materials.new("器件文字_深色")
    material.diffuse_color = (0.012, 0.018, 0.03, 1)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader:
        shader.inputs["Base Color"].default_value = material.diffuse_color
        shader.inputs["Roughness"].default_value = 0.72
    return material


def make_surface_material(name, color, metallic=0.0):
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader:
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Metallic"].default_value = metallic
        shader.inputs["Roughness"].default_value = 0.38 if metallic == 0 else 0.24
    return material


def assign_material(obj, material):
    if obj.type == "MESH":
        obj.data.materials.clear()
        obj.data.materials.append(material)


def category_for_ref(ref):
    if ref.startswith("C_"):
        return "capacitor"
    if ref.startswith("R_"):
        return "resistor"
    if ref in {"SW1", "SW2", "J_SWITCH"}:
        return "switch"
    return "wire"


def add_label(collection, font, material, text, name, center, target_dims, body_ref=""):
    curve = bpy.data.curves.new(name + "_文字", "FONT")
    curve.body = text
    curve.font = font
    curve.size = 0.8
    curve.space_line = 0.9
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.extrude = 0.012
    curve.bevel_depth = 0.004
    curve.bevel_resolution = 1
    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    obj.location = center
    obj.data.materials.append(material)
    if body_ref:
        obj["对应器件位号"] = body_ref

    bpy.context.view_layer.update()
    # Keep small labels within the component's top face where possible.
    max_width = max(1.2, target_dims[0] - 0.3)
    max_height = max(0.8, target_dims[1] - 0.25)
    factor = min(1.0, max_width / max(obj.dimensions.x, 0.01), max_height / max(obj.dimensions.y, 0.01))
    obj.scale = (factor, factor, factor)
    return obj


def main():
    if bpy.data.filepath and Path(bpy.data.filepath).resolve() != SOURCE.resolve():
        raise RuntimeError(f"输入工程不匹配：{bpy.data.filepath}")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    check = json.loads(CHECK_PATH.read_text(encoding="utf-8"))
    bounds = check["bounds_assembly_mm"]
    x_offset = -bounds[0]
    z_flip_max = bounds[5]
    base_y = -18.8
    top_y = config["pcb"]["top_face_y"]
    board_top_world_z = top_y - base_y

    original = bpy.data.objects.get("装配零件")
    if original is None or original.type != "MESH":
        raise RuntimeError("没有找到原预览中的装配零件网格")

    parts_collection = bpy.data.collections.new("逐件命名器件与五金件")
    bpy.context.scene.collection.children.link(parts_collection)
    source_name = original.name
    bpy.ops.object.select_all(action="DESELECT")
    original.select_set(True)
    bpy.context.view_layer.objects.active = original
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    loose = [
        obj for obj in bpy.context.scene.objects
        if obj.type == "MESH" and (obj.name == source_name or obj.name.startswith(source_name + "."))
    ]
    for obj in loose:
        move_to_collection(obj, parts_collection)

    surface_materials = {
        category: make_surface_material("器件类别_" + category, color, 0.48 if category == "hardware" else 0.0)
        for category, (color, _) in PALETTE.items()
    }
    remaining = list(loose)
    body_objects = {}
    unmatched_components = []
    for part in config["parts"]:
        ref = part["ref"]
        if ref not in PART_LABELS:
            continue
        expectations = expected_for_part(part, x_offset, z_flip_max, top_y, base_y)
        matched = []
        for index, expected in enumerate(expectations, 1):
            obj = find_mesh(remaining, expected)
            if obj is not None:
                title, ref_name, value, purpose, _ = PART_LABELS[ref]
                obj.name = f"{ref_name}_{title}_{value}_本体{index}"
                obj["器件位号"] = ref
                obj["中文名称"] = title
                obj["规格"] = value
                obj["用途"] = purpose
                category = category_for_ref(ref)
                assign_material(obj, surface_materials[category])
                matched.append(obj)
        if matched:
            body_objects[ref] = matched
        else:
            unmatched_components.append(ref)

    # The assembly model includes these major modules as simple dimensional
    # representations; their envelopes are taken from build_gen2_mount.py.
    sm = (-7.5, 16.0, -14.6, -13.0, 14.0, 32.0)
    gy_board = (-22.0, -1.4, 7.8, 9.0, 20.1, 37.9)
    special_specs = [
        ("主控板_ESP32-S3 SuperMini", assembly_box(sm, x_offset, z_flip_max, base_y), "ESP32-S3 SuperMini主控板", "主控板"),
        ("主控板元件示意", assembly_box((-6.5, 15, -13, -9.5, 15, 31), x_offset, z_flip_max, base_y), "主控元件区", "主控板"),
        ("主控板背面焊线示意", assembly_box((-6.5, 15, -16.6, -14.6, 15.6, 30.4), x_offset, z_flip_max, base_y), "主控板背面焊线", "主控板"),
        ("USB-C接口", assembly_box((16, 18.5, -13, -9.5, 18.5, 27.5), x_offset, z_flip_max, base_y), "USB-C接口", "主控板"),
        ("陀螺仪板_GY-601N1", assembly_box(gy_board, x_offset, z_flip_max, base_y), "GY-601N1惯性测量模块", "陀螺仪板"),
        ("陀螺仪芯片示意", assembly_box((-21, -2.4, 9, 11.8, 21.1, 36.9), x_offset, z_flip_max, base_y), "LSM6DSV16X陀螺仪芯片示意", "陀螺仪板"),
        ("陀螺仪焊线示意", assembly_box((-12, -3, 11.8, 14, 20.1, 23.1), x_offset, z_flip_max, base_y), "陀螺仪连接线", "陀螺仪板"),
        ("单节锂电池_尺寸示意", assembly_box((-53.2, -22.2, -16.7, -8.7, -84.25, -31.75), x_offset, z_flip_max, base_y), "单节保护锂电池（约600–700mAh）", "电池"),
        ("SS-01GL金属扳机开关", ((13.7, 19.8, 6.4), (45.4, 53.1, 18.8)), "SS-01GL金属扳机开关", "扳机"),
        ("SS-01GL扳机摆杆示意", assembly_box((-3.6, -3.3, -2.5, 2.5, -20, -1), x_offset, z_flip_max, base_y), "SS-01GL扳机摆杆示意", "扳机"),
    ]
    special_objects = {}
    for name, expected, label, ref in special_specs:
        dim_tol = 0.3 if ref == "扳机" else 0.25
        center_tol = 1.0 if ref == "扳机" else 0.3
        obj = find_mesh(remaining, expected, dim_tolerance=dim_tol, center_tolerance=center_tol)
        if obj is None:
            continue
        obj.name = name
        obj["中文名称"] = label
        obj["规格说明"] = ref
        category = "battery" if ref == "电池" else ("switch" if ref == "扳机" else "module")
        assign_material(obj, surface_materials[category])
        special_objects[name] = obj

    # Individually name the six M2x20 fastener sets and their hardware pieces.
    fastener_objects = {}
    for hole in config["pcb"]["mount_holes"]:
        hid = hole["id"]
        x, z = hole["xz"]
        targets = [
            (f"{hid}_M2x20螺钉", assembly_cylinder(x, z, 2, -20.9, 1.2, x_offset, z_flip_max, base_y), 0.2),
            (f"{hid}_M2螺母", assembly_hex_nut(x, z, top_y, top_y + 1.6, x_offset, z_flip_max, base_y), 0.2),
        ]
        for name, expected, tolerance in targets:
            obj = find_mesh(remaining, expected, dim_tolerance=tolerance, center_tolerance=0.25)
            if obj is not None:
                obj.name = name
                obj["规格"] = "M2×20螺钉" if "螺钉" in name else "M2螺母"
                assign_material(obj, surface_materials["hardware"])
                fastener_objects[name] = obj
    for index, (x, z) in enumerate([(-14.2, -4.521), (-14.2, -14.021)], 1):
        targets = [
            (f"SS{index}_M2x20螺钉", assembly_cylinder(x, z, 2, -16.5, 5.6, x_offset, z_flip_max, base_y), 0.2),
            (f"SS{index}_螺钉头垫片", assembly_cylinder(x, z, 2.5, 3.2, 3.5, x_offset, z_flip_max, base_y), 0.2),
            (f"SS{index}_支承垫片", assembly_cylinder(x, z, 2.5, -3.8, -3.2, x_offset, z_flip_max, base_y), 0.2),
            (f"SS{index}_M2螺母", assembly_hex_nut(x, z, -7.6, -6, x_offset, z_flip_max, base_y), 0.25),
        ]
        for name, expected, tolerance in targets:
            obj = find_mesh(remaining, expected, dim_tolerance=tolerance, center_tolerance=0.25)
            if obj is not None:
                obj.name = name
                obj["规格"] = "M2×20螺钉" if "螺钉" in name else ("M2螺母" if "螺母" in name else "垫片")
                assign_material(obj, surface_materials["hardware"])
                fastener_objects[name] = obj

    # Merge only the remaining tiny plated pads, leads and mesh fragments.
    # Their surrounding named component bodies and labels remain separate.
    if remaining:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in remaining:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = remaining[0]
        bpy.ops.object.join()
        remaining[0].name = "未逐件拆分的焊盘与连接细节"
        remaining[0]["说明"] = "按物料清单逐件命名的器件本体已单独拆出；此处为板级焊盘、焊脚和小型连接细节。"

    # Human-readable names and visible 3D labels for every BOM entry.
    label_collection = bpy.data.collections.new("器件文字标注（可整组隐藏）")
    bpy.context.scene.collection.children.link(label_collection)
    if not FONT_PATH.is_file():
        raise RuntimeError(f"找不到中文字体：{FONT_PATH}")
    font = bpy.data.fonts.load(str(FONT_PATH))
    dark = make_dark_material()
    light_text = make_surface_material("器件文字_浅色", (0.98, 0.99, 1.0, 1))
    text_materials = {"dark": dark, "light": light_text}
    labels_created = 0
    for part in config["parts"]:
        ref = part["ref"]
        if ref not in PART_LABELS:
            continue
        title, ref_name, value, purpose, visible_purpose = PART_LABELS[ref]
        expected = expected_for_part(part, x_offset, z_flip_max, top_y, base_y)
        if not expected:
            continue
        dims, center = expected[0]
        top_z = center[2] + dims[2] / 2 + 0.08
        tag = f"{title}\n{ref_name}"
        name = f"标签_{ref_name}_{title}_{value}"
        category = category_for_ref(ref)
        text_material = text_materials[PALETTE[category][1]]
        add_label(label_collection, font, text_material, tag, name, (center[0], center[1], top_z), dims, ref)
        labels_created += 1

    # Put readable labels on the larger assemblies and reserve their geometry
    # object names in the Outliner as well.
    major_labels = [
        ("PCB", "第二代控制载板\nPCB", (25.2, 4.4, board_top_world_z + 0.12), (50.0, 2.4, 1.6), "载板"),
        ("主控板_ESP32-S3 SuperMini", "ESP32-S3 SuperMini\n主控开发板", (63.45, 20.8, 9.5), (21.0, 15.5, 2.0), "主控板"),
        ("陀螺仪板_GY-601N1", "GY-601N1\n陀螺仪模块", (47.5, 14.8, 31.0), (18.0, 15.0, 1.2), "陀螺仪板"),
        ("单节锂电池_尺寸示意", "单节保护锂电池\n约600–700mAh（尺寸示意）", (21.5, 101.75, 10.2), (28.0, 48.0, 8.0), "电池"),
    ]
    for object_name, label, center, dims, ref in major_labels:
        target = bpy.data.objects.get(object_name)
        if target is not None:
            target["标注"] = label.replace("\n", " ")
        category = "battery" if ref == "电池" else "module"
        text_material = text_materials[PALETTE[category][1]]
        add_label(label_collection, font, text_material, label, "总成标签_" + ref, center, dims, ref)

    # Name and tag the six M2x20 fastener positions without changing geometry.
    for hole in config["pcb"]["mount_holes"]:
        hid = hole["id"]
        x, z = hole["xz"]
        center = (x + x_offset, z_flip_max - z, board_top_world_z + 1.72)
        add_label(label_collection, font, dark, f"{hid} M2×20\n螺钉+螺母", f"标签_{hid}_M2x20固定件", center, (5.8, 4.2, 1.6), hid)
        labels_created += 1
    for index, (x, z) in enumerate([(-14.2, -4.521), (-14.2, -14.021)], 1):
        center = (x + x_offset, z_flip_max - z, 22.35)
        add_label(label_collection, font, dark, f"扳机固定件SS{index}\nM2×20螺钉与垫片", f"标签_SS{index}_扳机固定件", center, (7.0, 5.4, 1.0), f"SS{index}")
        labels_created += 1

    # The visible callout marks the external trigger switch, separate from SW2.
    add_label(label_collection, font, light_text, "SS-01GL\n扳机触发开关", "总成标签_SS-01GL扳机开关", (45.4, 53.1, 22.15), (12.0, 17.0, 6.4), "SS-01GL")

    # Explain which preview is open and keep the tag layer easy to toggle.
    bpy.context.scene["工程说明"] = "器件名称预览；不是最终制造工程。组件名称按 pcb/carrier-config.json 与 pcb/BOM.csv 标注；组件包络为示意几何。"
    bpy.context.scene["物料标注数量"] = len(PART_LABELS)
    bpy.context.scene["电容规格说明"] = "当前物料清单中的电容均为100nF（0.1µF），没有100µF电容。"
    bpy.context.scene["颜色说明"] = "蓝色=电容；橙红=电阻；紫色=开关；黄色=接线；青色=模块；红色=电池；银灰=五金件；绿色=电路板；浅蓝灰=外壳。"

    scene = bpy.context.scene
    for area in bpy.context.screen.areas if bpy.context.screen else []:
        if area.type == "VIEW_3D":
            area.spaces.active.shading.type = "MATERIAL"

    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT), compress=True)
    missing = [ref for ref in PART_LABELS if ref not in body_objects]
    print(json.dumps({
        "output": str(OUTPUT),
        "bom_items": len(PART_LABELS),
        "matched_body_refs": sorted(body_objects),
        "unmatched_body_refs": unmatched_components,
        "missing_body_objects": missing,
        "additional_major_parts": sorted(special_objects),
        "matched_fastener_objects": sorted(fastener_objects),
        "visible_labels_created": sum(1 for obj in label_collection.objects if obj.type == "FONT"),
        "unclassified_loose_mesh_count_before_merge": len(remaining),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
