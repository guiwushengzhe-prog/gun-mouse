"""核对新取回 PCB STEP 与冻结装配并离屏渲染；不修改任何设计。

直接复用原建壳脚本的拼板拆分和刚体坐标变换，输出只写本工作树 outputs。
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cadquery as cq
from PIL import ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
from build_shell import battery_model, box, dev_board_model, transformed  # noqa: E402
from render_views import caption, render  # noqa: E402
from verify_mechanical import bounds, sha256, solid_contacts, volume_overlap  # noqa: E402
from audit_assembly_interfaces import OUT, bore, load_assembly  # noqa: E402


def assembled_boards(source, cfg):
    """与 build_shell.load_pcb 的算法一致，唯一区别是源路径由调用者给定。"""
    shape = cq.importers.importStep(str(source)).val()
    board, daughter = cfg["board"], cfg["board"]["daughter"]
    du, dv = daughter["panel_origin_uv"]
    a0, a1 = daughter["outline_local"]["a"]
    b0, b1 = daughter["outline_local"]["b"]
    u0, u1 = du - b1 - 0.05, du - b0 + 0.05
    v0, v1 = dv + a0 - 0.05, dv + a1 + 0.6
    region = box(u0, u1, v0, v1, -30, 40)
    tabs = box(u0, u1, v1 - 0.7, dv + a1 + 2.6, -30, 40)
    main, small = [], []
    for solid in shape.Solids():
        bb = solid.BoundingBox()
        cx, cy = (bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2
        if bb.xlen > 60:
            main.append(solid.cut(region).cut(tabs))
            small.append(solid.intersect(region))
        elif u0 < cx < u1 and v0 < cy < v1:
            small.append(solid)
        else:
            main.append(solid)
    main = transformed(cq.Compound.makeCompound(main),
                       [[-1, 0, 0], [0, 0, 1], [0, 1, 0]],
                       (0, board["top_face_y"] - board["thickness"], 0))
    small = transformed(cq.Compound.makeCompound(small),
                        [[0, 0, 1], [0, 1, 0], [-1, 0, 0]],
                        (daughter["assembled_top_face_x"] - board["thickness"], -dv, du))
    return shape, main, small


def properties(shape):
    return {"valid": bool(shape.isValid()), "solid_count": len(shape.Solids()),
            "bounds_mm": bounds(shape), "volume_mm3": shape.Volume()}


def compare_properties(current, frozen):
    remaining = [{"shape": s, "bounds": bounds(s), "volume": s.Volume()} for s in frozen.Solids()]
    matches, unmatched = 0, []
    max_bounds, max_volume = 0.0, 0.0
    for i, solid in enumerate(current.Solids()):
        sb, sv = bounds(solid), solid.Volume()
        candidates = [(other, max(abs(x-y) for x, y in zip(sb, other["bounds"])),
                       abs(sv-other["volume"])) for other in remaining]
        candidates = [item for item in candidates if item[1] < 1e-4 and item[2] < 1e-3]
        if candidates:
            other, bound_error, volume_error = min(candidates, key=lambda item: item[1]+item[2])
            remaining.remove(other)
            matches += 1
            max_bounds = max(max_bounds, bound_error)
            max_volume = max(max_volume, volume_error)
        else:
            unmatched.append({"solid_index": i, **properties(solid)})
    return {"current": properties(current), "frozen": properties(frozen),
            "matched_solid_properties": matches, "current_unmatched": unmatched,
            "frozen_unmatched": [properties(s["shape"]) for s in remaining],
            "maximum_matched_bounds_error_mm": max_bounds,
            "maximum_matched_volume_error_mm3": max_volume,
            "all_solid_properties_match": not unmatched and not remaining,
            "note": "比较逐实体边界和体积，不宣称每个内部曲面完全等同；铜线电气连接另由设计规则与网表核对。"}


def footer(image, rows):
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 21)
    y0 = image.height - (len(rows) * 30 + 12)
    draw.rectangle((0, y0, image.width, image.height), fill="white")
    for i, row in enumerate(rows):
        draw.text((16, y0+6+30*i), row, fill=(35, 35, 35), font=font)
    return image


def interpret_comparison(report):
    """保留严格比较结果，量化板厚差值和薄贴合层，避免把小交集直接说成合格。"""
    for key in ("main_board_comparison", "daughter_comparison"):
        row = report[key]
        new, old = row["current_unmatched"], row["frozen_unmatched"]
        if len(new) != 1 or len(old) != 1:
            continue
        nb, ob = new[0]["bounds_mm"], old[0]["bounds_mm"]
        axis = min(range(3), key=lambda a: nb[a*2+1]-nb[a*2])
        nt, ot = nb[axis*2+1]-nb[axis*2], ob[axis*2+1]-ob[axis*2]
        planar_indices = [i for i in range(6) if i//2 != axis]
        new_area, old_area = new[0]["volume_mm3"]/nt, old[0]["volume_mm3"]/ot
        row["thin_board_difference_analysis"] = {
            "thickness_axis": ("X", "Y", "Z")[axis],
            "current_thickness_mm": nt, "frozen_thickness_mm": ot,
            "thickness_difference_mm": nt-ot,
            "planar_bounds_maximum_error_mm": max(abs(nb[i]-ob[i]) for i in planar_indices),
            "current_volume_divided_by_thickness_mm2": new_area,
            "frozen_volume_divided_by_thickness_mm2": old_area,
            "planar_area_difference_mm2": new_area-old_area,
            "measured_volume_difference_mm3": new[0]["volume_mm3"]-old[0]["volume_mm3"],
            "volume_difference_predicted_from_thickness_mm3": old_area*(nt-ot),
            "note": "边界和截面积兼容微小导出板厚差；这是量化解释，不把严格体积比较改成全同，也不证明每条轮廓等同。"}
    for name, contacts in report["current_board_contacts"].items():
        for contact in contacts:
            b = contact["overlap_bounds"]
            contact["overlap_y_thickness_mm"] = b[3]-b[2]
            if name in ("左半壳", "开发板") and b[3]-b[2] < 0.001:
                contact["interpretation"] = "已列出薄贴合层厚度，须结合对应贴合面解释，不代表实物公差验收"
    report["contact_interpretation"] = (
        "逐实体交集及边界保留在记录中。小交集必须同时核对边界厚度和预期贴合面，"
        "不能仅因体积小就算通过。扳机与静态长杠杆的驱动接触不等同随动机构实物验证。"
        "实物公差、运动随动及触摸/射频性能未验收。")


def render_battery_view(cfg, source):
    """补充背面图；引用原函数生成已审过的参考体，不生成新外壳或改变布局。"""
    _, main_board, daughter = assembled_boards(source, cfg)
    left = cq.importers.importStep(str(ROOT / "deliverables" / "pcb-shell-v1" / "打印文件" / "STEP" / "左半壳.step")).val()
    visual = {"left": left, "pcb": main_board, "daughter": daughter,
              "battery": battery_model(cfg), "dev": dev_board_model(cfg)}
    target = OUT / "关系图" / "04-电池与背面空间.png"
    target.parent.mkdir(exist_ok=True)
    image = caption(render(visual, (110, -280, 50), size=(1250, 1050), zoom=1.08,
                           overrides={"left": ((0.65, 0.73, 0.82), 1.0)}),
                    "取下右壳：背面的电池仓、主板与左壳支撑")
    footer(image, ["金：电池上限参考体（8×31×52.5毫米）；绿：新导出主板",
                   "电池仓厚8.4毫米；8毫米电池仅余0.4毫米固定材料空间",
                   "未显示成品线束；电池保护板、插头、质量和实物尺寸仍需核对"])
    image.save(target)
    return {"file": str(target.relative_to(ROOT)), "sha256": sha256(target)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / "config" / "pcb-shell-v1.json").read_text(encoding="utf-8"))
    source = OUT / "baseline-pcb-with-parts.step"
    if not source.exists():
        raise FileNotFoundError("新取回基线 STEP 尚未保存，不拿旧板冒充")
    if "--back-only" in sys.argv:
        # 已有前三图时可只补背面，避免重做已经完成的验证和全套渲染。
        target = OUT / "pcb-shell-current-export-report.json"
        report = json.loads(target.read_text(encoding="utf-8"))
        if (report["source_sha256"] != sha256(source)
                or report["config_sha256"] != sha256(ROOT / "config" / "pcb-shell-v1.json")):
            raise ValueError("新导出STEP或配置已改变，不能给旧报告追加新图")
        result = render_battery_view(cfg, source)
        report["images"] = [r for r in report["images"] if r["file"] != result["file"]]+[result]
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "source": str(source), "source_sha256": sha256(source), "source_bytes": source.stat().st_size,
              "config_sha256": sha256(ROOT / "config" / "pcb-shell-v1.json"),
              "coordinate_system": "毫米；X向前、Y向左、Z向上",
              "transform": {"main": "(u,v,w)→(-u,w-3.23,v)",
                            "daughter": "(u,v,w)→(w-20.6,v-1.0,-43.5-u)"}}
    print("Reading current native PCB STEP and frozen delivery assembly.", flush=True)
    raw, main_board, daughter = assembled_boards(source, cfg)
    print("Current PCB read and transformed; reading frozen assembly.", flush=True)
    models = load_assembly(report, cfg)
    print("Frozen assembly read; comparing cached solid properties.", flush=True)
    report["native_export_properties"] = properties(raw)
    report["main_board_comparison"] = compare_properties(main_board, models["主板"])
    print("Main board comparison complete.", flush=True)
    report["daughter_comparison"] = compare_properties(daughter, models["扳机小板"])
    print("Current and frozen model properties compared; checking physical interfaces.", flush=True)
    plate_candidates = [s for s in main_board.Solids() if s.BoundingBox().xlen > 110
                        and s.BoundingBox().zlen > 110
                        and abs(s.BoundingBox().ylen-cfg["board"]["thickness"]) < 1e-3]
    if len(plate_candidates) != 1:
        raise ValueError("新导出模型无法唯一定位板体")
    plate, top = plate_candidates[0], cfg["board"]["top_face_y"]
    report["current_board_mount_bores"] = [{"id": h["id"],
                "probe_overlap_mm3": volume_overlap(plate, bore(*h["xz"], h["d"]/2-0.01,
                                top-cfg["board"]["thickness"]-0.05, top+0.05))}
                for h in cfg["board"]["mount_holes"]]
    report["current_board_contacts"] = {}
    for name in ("左半壳", "右半壳", "电池", "开发板"):
        report["current_board_contacts"][name] = solid_contacts(models[name], main_board)
    report["current_daughter_contacts"] = {name: solid_contacts(models[name], daughter)
                                             for name in ("左半壳", "右半壳")}
    travel = cfg["trigger"]["switch_contact_from_board"]["rest"]-cfg["trigger"]["switch_contact_from_board"]["stop"]
    report["trigger_pressed_contacts_with_current_daughter"] = solid_contacts(
                    models["扳机"].translate(cq.Vector(-travel, 0, 0)), daughter)
    interpret_comparison(report)
    # 这些图直接渲染刚取回的 PCB 模型和正式交付外壳，无桌面截图。
    visual = {"left": models["左半壳"], "right": models["右半壳"],
              "trigger": models["扳机"], "cover": models["扳机触摸面盖"],
              "cap": models["右键帽"], "knob": models["摇杆帽"],
              "dev": models["开发板"], "battery": models["电池"],
              "pcb": main_board, "daughter": daughter}
    image_dir = OUT / "关系图"
    image_dir.mkdir(exist_ok=True)
    views = [("01-正式PCB与外壳关系.png", visual, (150, 260, 65),
              "新导出PCB与原外壳：统一坐标装配关系", None),
             ("02-正式PCB内部布局.png", {k:v for k,v in visual.items() if k != "left"}, (20, 300, -10),
              "取下左壳：新导出主板、小板、开发板、电池与按键", {"right": ((0.68, 0.75, 0.83), 1.0)}),
             ("03-接口与天线区域.png", {k:v for k,v in visual.items() if k not in ("left", "right")}, (95, 220, 65),
              "接口与器件：真实库模型 + 开发板、电池参考体", None)]
    report["images"] = []
    for filename, shapes, position, title, overrides in views:
        image = caption(render(shapes, position, size=(1250, 1050), zoom=1.08, overrides=overrides), title)
        footer(image, ["绿：主板　紫：扳机小板　蓝：开发板参考　金：电池上限参考",
                       "C5：X=57 / Z=16.5；C6：X=54 / Z=17（天线附近原位置保留）",
                       "模型核对图；实物尺寸、打印公差、全行程及无线效果仍需验证"])
        path = image_dir / filename
        image.save(path)
        report["images"].append({"file": str(path.relative_to(ROOT)), "sha256": sha256(path)})
        print("Rendered: " + filename, flush=True)
    report["images"].append(render_battery_view(cfg, source))
    report["manufacturing_finalized"] = False
    target = OUT / "pcb-shell-current-export-report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"report": str(target), "main_matches": report["main_board_comparison"]["all_solid_properties_match"],
                      "daughter_matches": report["daughter_comparison"]["all_solid_properties_match"],
                      "images": len(report["images"])}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
