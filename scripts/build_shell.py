"""从共用毫米参数生成工具验证用的电路板、外壳和装配模型。"""

import argparse
import json
import math
from pathlib import Path
import sys


def positive_number(data, key):
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} 必须是数字。")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{key} 必须大于零，且不能是无穷大。")
    return value


def read_config(path):
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if config["schema_version"] != 1:
        raise ValueError("只支持配置格式版本 1。")
    coordinates = config["coordinates"]
    if coordinates["units"] != "mm" or coordinates["origin"] != "board_center_bottom":
        raise ValueError("坐标必须使用毫米，原点必须位于电路板中心的底面。")
    board, enclosure = config["board"], config["enclosure"]
    width = positive_number(board, "width_mm")
    depth = positive_number(board, "depth_mm")
    positive_number(board, "thickness_mm")
    for key in (
        "wall_thickness_mm", "floor_thickness_mm", "side_clearance_mm",
        "below_board_clearance_mm", "above_board_clearance_mm",
        "mounting_post_diameter_mm", "mounting_post_hole_diameter_mm",
    ):
        positive_number(enclosure, key)
    post_radius = enclosure["mounting_post_diameter_mm"] / 2
    post_hole = enclosure["mounting_post_hole_diameter_mm"]
    if post_hole >= 2 * post_radius:
        raise ValueError("固定柱孔径必须小于固定柱外径。")
    holes = board["mounting_holes"]
    if not isinstance(holes, list) or len(holes) != 4:
        raise ValueError("这个矩形验证示例需要四个安装孔。")
    points = []
    for hole in holes:
        x, y = hole["x_mm"], hole["y_mm"]
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) for v in (x, y)):
            raise ValueError("安装孔坐标必须是有限数字。")
        diameter = positive_number(hole, "diameter_mm")
        if abs(x) + diameter / 2 >= width / 2 or abs(y) + diameter / 2 >= depth / 2:
            raise ValueError("安装孔必须完全位于板形内部。")
        gap = enclosure["side_clearance_mm"]
        if abs(x) + post_radius >= width / 2 + gap or abs(y) + post_radius >= depth / 2 + gap:
            raise ValueError("固定柱必须完全位于外壳内侧。")
        if not post_hole <= diameter < 2 * post_radius:
            raise ValueError("板上安装孔径须不小于固定柱孔径，且小于固定柱外径。")
        if any(math.hypot(x - px, y - py) <= 2 * post_radius for px, py in points):
            raise ValueError("安装孔位置导致固定柱重叠。")
        points.append((x, y))
    return config


def bounds(shape):
    box = shape.BoundingBox()
    return {name: getattr(box, name) for name in (
        "xmin", "xmax", "ymin", "ymax", "zmin", "zmax", "xlen", "ylen", "zlen"
    )}


def measure_imported_board(cq, shape, expected_shape, board, tolerance):
    """量测圆孔，并用实际板边与孔重建裸板，以检查实体边界。"""
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    box = bounds(shape)
    groups = {}
    cylinder_face_count = 0
    for face in shape.Faces():
        if face.geomType() != "CYLINDER":
            continue
        cylinder_face_count += 1
        cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
        point, direction = cylinder.Location(), cylinder.Axis().Direction()
        if abs(abs(direction.Z()) - 1) > 1e-6:
            raise ValueError("裸板中存在倾斜圆柱面，不符合这个垂直圆孔验证示例。")
        face_box = bounds(face)
        if abs(face_box["zmin"] - box["zmin"]) > 1e-6 or abs(face_box["zmax"] - box["zmax"]) > 1e-6:
            raise ValueError("板上的圆孔没有贯穿整个板厚。")
        key = tuple(round(value, 6) for value in (point.X(), point.Y(), cylinder.Radius()))
        hole = groups.setdefault(key, {
            "x_mm": point.X(), "y_mm": point.Y(), "diameter_mm": 2 * cylinder.Radius(),
            "cylindrical_area_mm2": 0,
        })
        hole["cylindrical_area_mm2"] += face.Area()
    if len(groups) != len(board["mounting_holes"]):
        raise ValueError(f"导入板模型量测到 {len(groups)} 个圆孔，配置要求四个。")
    measured_holes, used = [], set()
    for expected in board["mounting_holes"]:
        key, measured = min(
            ((key, value) for key, value in groups.items() if key not in used),
            key=lambda item: math.hypot(item[1]["x_mm"] - expected["x_mm"],
                                       item[1]["y_mm"] - expected["y_mm"]),
        )
        used.add(key)
        center_error = math.hypot(measured["x_mm"] - expected["x_mm"],
                                  measured["y_mm"] - expected["y_mm"])
        diameter_error = abs(measured["diameter_mm"] - expected["diameter_mm"])
        if center_error > tolerance or diameter_error > tolerance:
            raise ValueError(f"实测孔位或孔径超出 {tolerance} 毫米公差：{measured}")
        expected_area = math.pi * measured["diameter_mm"] * box["zlen"]
        if abs(measured["cylindrical_area_mm2"] - expected_area) > 1e-5:
            raise ValueError("圆孔的侧壁面积不完整，不能确认它是贯穿圆孔。")
        measured_holes.append({**measured, "center_error_mm": center_error,
                               "diameter_error_mm": diameter_error})

    reference = (cq.Workplane("XY").workplane(offset=box["zmin"])
                 .center((box["xmin"] + box["xmax"]) / 2,
                         (box["ymin"] + box["ymax"]) / 2)
                 .rect(box["xlen"], box["ylen"]).extrude(box["zlen"]))
    removed_volume = 0
    for hole in measured_holes:
        cutter = (cq.Workplane("XY").workplane(offset=box["zmin"])
                  .center(hole["x_mm"], hole["y_mm"])
                  .circle(hole["diameter_mm"] / 2).extrude(box["zlen"]))
        reference = reference.cut(cutter)
        removed_volume += math.pi * (hole["diameter_mm"] / 2) ** 2 * box["zlen"]
    difference = shape.cut(reference.val()).Volume() + reference.val().cut(shape).Volume()
    formula_volume = box["xlen"] * box["ylen"] * box["zlen"] - removed_volume
    formula_error = abs(shape.Volume() - formula_volume)
    if difference > 1e-5 or formula_error > 1e-5:
        raise ValueError("实际板的实体边界或体积不符合矩形板减去四个圆孔的结构。")
    configuration_difference = shape.cut(expected_shape).Volume() + expected_shape.cut(shape).Volume()
    return {
        "hole_count": len(measured_holes), "cylindrical_face_count": cylinder_face_count,
        "holes": measured_holes, "actual_board_volume_mm3": shape.Volume(),
        "four_holes_removed_volume_mm3": removed_volume,
        "volume_formula_error_mm3": formula_error,
        "measured_geometry_boundary_difference_volume_mm3": difference,
        "configuration_shape_difference_volume_mm3": configuration_difference,
        "configuration_dimension_errors_mm": {
            "width": box["xlen"] - board["width_mm"],
            "depth": box["ylen"] - board["depth_mm"],
            "thickness": box["zlen"] - board["thickness_mm"],
        },
        "geometry_volume_tolerance_mm3": 1e-5,
        "coordinate_transform": "none",
        "precision_note": "按毫米、板中心底面原点直接导入，无平移或旋转；尺寸和孔位在允许公差内，但导出值可能不与配置逐位相等。",
    }


def build(config, output, board_step):
    try:
        import cadquery as cq
    except ImportError as error:
        raise ValueError("当前 Python 环境没有 CadQuery，请使用已安装的 CadQuery 环境运行。") from error

    board, enclosure = config["board"], config["enclosure"]
    width, depth, thickness = (board[key] for key in ("width_mm", "depth_mm", "thickness_mm"))
    wall = enclosure["wall_thickness_mm"]
    floor = enclosure["floor_thickness_mm"]
    gap = enclosure["side_clearance_mm"]
    below = enclosure["below_board_clearance_mm"]
    above = enclosure["above_board_clearance_mm"]
    inner_width, inner_depth = width + 2 * gap, depth + 2 * gap
    top_z, bottom_z = thickness + above, -below - floor

    demo_board = cq.Workplane("XY").rect(width, depth).extrude(thickness)
    for hole in board["mounting_holes"]:
        cutter = (cq.Workplane("XY").center(hole["x_mm"], hole["y_mm"])
                  .circle(hole["diameter_mm"] / 2).extrude(thickness))
        demo_board = demo_board.cut(cutter)

    shell = (cq.Workplane("XY").workplane(offset=bottom_z)
             .rect(inner_width + 2 * wall, inner_depth + 2 * wall)
             .extrude(top_z - bottom_z))
    cavity = (cq.Workplane("XY").workplane(offset=-below)
              .rect(inner_width, inner_depth).extrude(top_z + below))
    shell = shell.cut(cavity)
    for hole in board["mounting_holes"]:
        x, y = hole["x_mm"], hole["y_mm"]
        post = (cq.Workplane("XY").workplane(offset=-below).center(x, y)
                .circle(enclosure["mounting_post_diameter_mm"] / 2).extrude(below))
        drill = (cq.Workplane("XY").workplane(offset=bottom_z).center(x, y)
                 .circle(enclosure["mounting_post_hole_diameter_mm"] / 2).extrude(below + floor))
        shell = shell.union(post).cut(drill)

    selected_board = demo_board
    tolerance = 0.05
    if board_step:
        selected_board = cq.importers.importStep(str(board_step))
    board_shape = cq.Compound.makeCompound(selected_board.vals())
    if board_step:
        if len(board_shape.Solids()) != 1:
            raise ValueError("导入的裸板模型必须只包含一个实体；请排除元件或其他装配件。")
        imported_bounds = bounds(board_shape)
        required = {
            "xmin": -width / 2, "xmax": width / 2,
            "ymin": -depth / 2, "ymax": depth / 2,
            "zmin": 0, "zmax": thickness,
            "xlen": width, "ylen": depth, "zlen": thickness,
        }
        if any(abs(imported_bounds[key] - value) > tolerance for key, value in required.items()):
            raise ValueError(
                "导入板模型的尺寸或原点不符合共用配置。要求板中心 X=Y=0、板底面 Z=0，"
                f"裸板尺寸 {width}×{depth}×{thickness} 毫米，允许误差 {tolerance} 毫米；"
                f"实际包围盒为 {imported_bounds}。请先在电路板工具中确认板模型的坐标；"
                "脚本不会自动搬移或旋转模型，也不接受包含元件的装配模型。"
            )

    shell_shape = shell.val()
    validity = {
        "shell": shell_shape.isValid() and bool(shell_shape.Solids()),
        "demo_board": demo_board.val().isValid() and bool(demo_board.val().Solids()),
        "selected_board": board_shape.isValid() and bool(board_shape.Solids()),
    }
    if not all(validity.values()):
        raise ValueError(f"模型不是有效实体，停止导出：{validity}")
    imported_verification = (
        measure_imported_board(cq, board_shape, demo_board.val(), board, tolerance)
        if board_step else None
    )
    intersection_volume = shell_shape.intersect(board_shape).Volume()
    if intersection_volume > 1e-6:
        raise ValueError(f"电路板与外壳发生碰撞，交集体积 {intersection_volume} 立方毫米。")

    output.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(shell, str(output / "outer-shell.step"))
    cq.exporters.export(shell, str(output / "outer-shell.stl"))
    cq.exporters.export(demo_board, str(output / "demo-board.step"))
    assembly = cq.Assembly(name="toolchain_demo")
    assembly.add(shell, name="shell", color=cq.Color(0.7, 0.75, 0.8))
    assembly.add(selected_board, name="board", color=cq.Color(0.1, 0.5, 0.2))
    assembly.export(str(output / "assembly.step"))
    report = {
        "purpose": config["purpose"],
        "mode": "imported_bare_board" if board_step else "shared_parameters_demo",
        "mode_description": (
            "使用外部裸板模型，已核对尺寸、原点、四个实际安装孔、实体边界、体积和碰撞；未验证元件空间或电路。"
            if board_step else "板与壳均来自同一配置；还没有使用电路板软件导出的实际板模型。"
        ),
        "cadquery_version": cq.__version__,
        "coordinates": config["coordinates"],
        "board_dimensions_mm": {"width": width, "depth": depth, "thickness": thickness},
        "configured_mounting_holes_mm": board["mounting_holes"],
        "imported_board_source": str(board_step) if board_step else None,
        "imported_board_holes_verified": bool(imported_verification) if board_step else None,
        "imported_board_verification": imported_verification,
        "board_bounds_mm": bounds(board_shape),
        "shell_bounds_mm": bounds(shell_shape),
        "cavity_dimensions_mm": {
            "width": inner_width, "depth": inner_depth, "height": top_z + below,
            "side_gap": gap, "below_board": below, "above_board": above,
        },
        "valid_solids": validity,
        "board_shell_intersection_volume_mm3": intersection_volume,
        "board_bounds_tolerance_mm": tolerance,
        "collision_volume_tolerance_mm3": 1e-6,
        "files": ["outer-shell.step", "outer-shell.stl", "demo-board.step", "assembly.step"],
        "limitations": "这是工具验证示例；不代表枪形外壳、真实硬件布局、强度或可生产设计。",
    }
    (output / "geometry-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已导出到：{output}\n模型有效；板与外壳交集体积：{intersection_volume:.9g} 立方毫米。")
    print(report["mode_description"])


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=root / "config" / "toolchain-demo.json",
                        help="共用配置文件，默认使用项目内的工具验证示例。")
    parser.add_argument("--output", type=Path, default=root / "outputs" / "toolchain-demo",
                        help="模型和几何报告输出目录。")
    parser.add_argument("--board-step", type=Path,
                        help="电路板工具导出的裸板模型；要求毫米、板中心原点、板底面 Z=0。")
    args = parser.parse_args()
    try:
        config = read_config(args.config.resolve())
        board_step = args.board_step.resolve() if args.board_step else None
        build(config, args.output.resolve(), board_step)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"生成失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
