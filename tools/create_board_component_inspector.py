"""从既有最终装配提取主板和十二个器件，生成可点选中文名称的独立场景。"""
import csv
import hashlib
import json
import math
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shell/最终装配版/最终装配预览_472e040.blend"
OUT = ROOT / "shell/主板器件点选查看"
TARGET = OUT / "主板_点选查看元件值.blend"
OVERLAY = ROOT / "tools/board_component_overlay.py"

# 用板上编号保留同值器件之间的区别。阻值及容值另与当前物料清单核对。
PARTS = {
    "R_TRIG": ("3.3千欧电阻", "3.3千欧", "扳机输入电阻", "3.3k"),
    "R_TOUCH": ("510欧电阻", "510欧", "触摸输入串联电阻", "510"),
    "R_BAT_H": ("100千欧电阻", "100千欧", "电池电压分压上臂", "100k"),
    "R_BAT_L": ("100千欧电阻", "100千欧", "电池电压分压下臂", "100k"),
    "C_JOY_X": ("100纳法电容", "100纳法，0.1微法，标记104", "摇杆横轴滤波电容", "100n"),
    "C_JOY_Y": ("100纳法电容", "100纳法，0.1微法，标记104", "摇杆纵轴滤波电容", "100n"),
    "C_TRIG": ("100纳法电容", "100纳法，0.1微法，标记104", "扳机输入滤波电容", "100n"),
    "C_BAT": ("100纳法电容", "100纳法，0.1微法，标记104", "电池电压采样滤波电容", "100n"),
    "J_MCU": ("主控板", "ESP32-S3 SuperMini", "主控与蓝牙通信", None),
    "J_GY": ("惯性传感器模块", "GY-601N1", "检测姿态与转动", None),
    "SW1": ("摇杆模块", "HW-504", "摇杆横纵轴与按压输入", None),
    "J_SWITCH": ("电源拨动开关", "SS12D10 G5", "电池供电开关", None),
}


def source_group(name):
    if name.startswith("载板-"):
        return "BOARD"
    if "焊点" in name:
        return None
    for ref in PARTS:
        if ref.startswith(("R_", "C_")) and name.startswith(ref + "-"):
            return ref
    if name == "开发板" or name.startswith("开发板-"):
        return "J_MCU"
    if name == "陀螺仪板" or name.startswith("陀螺仪-"):
        return "J_GY"
    if name.startswith(("SW1-", "摇杆-")):
        return "SW1"
    if name.startswith("电源开关-"):
        return "J_SWITCH"
    return None


def bounds(objects):
    points = [obj.matrix_world @ Vector(p) for obj in objects for p in obj.bound_box]
    return [[min(p[i] for p in points) for i in range(3)],
            [max(p[i] for p in points) for i in range(3)]]


def main():
    if Path(bpy.data.filepath).resolve() != SOURCE.resolve():
        raise RuntimeError("必须从已核对的最终装配预览建立，不覆盖源场景")
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    with (ROOT / "pcb/BOM.csv").open(encoding="utf-8-sig", newline="") as stream:
        bom = {row["Reference"]: row for row in csv.DictReader(stream)}
    for ref, (_, _, _, expected) in PARTS.items():
        if expected is not None:
            assert bom[ref]["Value / Type"] == expected, ref

    grouped = {ref: [] for ref in ["BOARD", *PARTS]}
    for obj in list(bpy.data.objects):
        group = source_group(obj.name) if obj.type == "MESH" else None
        if group:
            obj.hide_set(False)
            obj.hide_viewport = obj.hide_render = obj.hide_select = False
            grouped[group].append(obj)
        else:
            bpy.data.objects.remove(obj, do_unlink=True)
    assert all(grouped.values()), {ref: len(items) for ref, items in grouped.items()}

    # 对照已下单孔位，确认提取的小元件没有因对象分组或旧预览而移动。
    config = json.loads((ROOT / "release/2026-10-18-最终版/工程源文件/模型基准配置.json").read_text(encoding="utf-8"))
    audit = json.loads((ROOT / "release/2026-10-18-最终版/电路板/制造核对.json").read_text(encoding="utf-8"))
    board_bounds = bounds(grouped["BOARD"])
    outline = config["pcb"]["outline_xz"]
    dx = board_bounds[0][0] - min(p[0] for p in outline)
    dz = board_bounds[1][2] + min(p[1] for p in outline)
    positions = {}
    for ref in PARTS:
        if not ref.startswith(("R_", "C_")):
            continue
        bb = bounds(grouped[ref])
        actual = [(bb[0][0] + bb[1][0]) / 2, (bb[0][2] + bb[1][2]) / 2]
        pads = audit["实际孔位核对"][ref]
        center = [sum(p["装配坐标毫米"][i] for p in pads) / len(pads) for i in (0, 1)]
        expected = [center[0] + dx, -center[1] + dz]
        difference = max(abs(a - b) for a, b in zip(actual, expected))
        assert difference < .01, (ref, actual, expected)
        positions[ref] = {"模型中心": actual, "下单孔位中心对应值": expected, "最大差毫米": difference}

    collections = {}
    for name in ("主板", "电阻与电容", "模块与开关"):
        collections[name] = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collections[name])
    mapping = []
    for ref, objects in grouped.items():
        original_names = [o.name for o in objects]
        before = bounds(objects)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        bpy.ops.object.join()
        obj = bpy.context.active_object
        label, value, purpose = ("主板", "52×82毫米双层板", "器件安装位置参考") if ref == "BOARD" else PARTS[ref][:3]
        obj.name = label if ref == "BOARD" else label + "｜" + ref
        obj["器件名称"], obj["器件编号"], obj["器件值"], obj["用途"] = label, ref, value, purpose
        target_collection = collections["主板" if ref == "BOARD" else "电阻与电容" if ref.startswith(("R_", "C_")) else "模块与开关"]
        for old in list(obj.users_collection):
            old.objects.unlink(obj)
        target_collection.objects.link(obj)
        after = bounds([obj])
        assert max(abs(a - b) for p, q in zip(before, after) for a, b in zip(p, q)) < .0001
        mapping.append({"编号": ref, "名称": obj.name, "器件值": value, "来源对象": original_names})
    for collection in list(bpy.data.collections):
        if collection not in collections.values() and not collection.objects and not collection.children:
            bpy.data.collections.remove(collection)

    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = .001
    scene.unit_settings.length_unit = "MILLIMETERS"
    view_rotation = Vector((0, -1, 0)).to_track_quat("-Z", "Y") @ Quaternion((0, 0, 1), math.pi)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.shading.type, space.shading.color_type = "SOLID", "MATERIAL"
                space.shading.background_type = "VIEWPORT"
                space.shading.background_color = (.055, .065, .085)
                space.overlay.show_floor = space.overlay.show_axis_x = space.overlay.show_axis_y = False
                space.overlay.show_text = True
                space.region_3d.view_rotation = view_rotation
                space.region_3d.view_perspective = "ORTHO"
                space.region_3d.view_location = Vector((20, -16, 0))
                space.region_3d.view_distance = 110
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if region and bpy.context.window and screen == bpy.context.window.screen:
                    with bpy.context.temp_override(window=bpy.context.window, area=area, region=region):
                        bpy.ops.view3d.view_all(center=True)
            elif area.type == "PROPERTIES":
                area.spaces.active.context = "OBJECT"
    bpy.ops.object.select_all(action="DESELECT")
    resistor = next(o for o in bpy.data.objects if o.get("器件编号") == "R_TRIG")
    resistor.select_set(True)
    bpy.context.view_layer.objects.active = resistor
    assert len([o for o in scene.objects if o.type == "MESH"]) == 13

    code = OVERLAY.read_text(encoding="utf-8")
    text = bpy.data.texts.new("点选显示元件名称.py")
    text.write(code)
    text.use_module = True
    note = bpy.data.texts.new("使用说明")
    note.write("左键点击器件，左上角显示中文名称与阻值、容值。中键旋转，滚轮缩放，Home键查看全板。\n"
               "同一器件本体和引脚为同一个对象。模型用于认位置，实际铜线以已下单嘉立创板为准。\n")
    OUT.mkdir(exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(TARGET), compress=True)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_hash
    (OUT / "器件对应与位置核对.json").write_text(json.dumps({"源场景": str(SOURCE), "源场景SHA256": source_hash,
        "器件数量": len(PARTS), "对应": mapping, "八颗小元件位置核对": positions}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("COMPONENT_INSPECTOR_SAVED", str(TARGET), flush=True)


if __name__ == "__main__":
    main()
