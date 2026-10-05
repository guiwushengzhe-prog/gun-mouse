"""离线核对覆铜对照的实际光绘几何；不连接软件、不改任何设计文件。"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import zipfile

from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box
from shapely.ops import polygonize, unary_union

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "formal-validation"
ARC_TOL_MM = 0.00001


def winding(point, contour):
    value = 0
    x, y = point.x, point.y
    for a, b in zip(contour, contour[1:]):
        cross = (b[0] - a[0]) * (y - a[1]) - (x - a[0]) * (b[1] - a[1])
        if a[1] <= y < b[1] and cross > 0:
            value += 1
        elif b[1] <= y < a[1] and cross < 0:
            value -= 1
    return value


def region_geometry(contour):
    if len(contour) < 4 or math.dist(contour[0], contour[-1]) > 0.00002:
        raise ValueError("光绘区域轮廓不闭合")
    # 切入段可能完全重合；先划分平面，再按原轮廓绕数保留铜面，避免填满孔。
    faces = polygonize(unary_union(LineString(contour)))
    return unary_union([face for face in faces if winding(face.representative_point(), contour)])


def arc_points(start, end, center, clockwise):
    radius = math.dist(start, center)
    if radius <= 0 or abs(math.dist(end, center) - radius) > 0.0001:
        raise ValueError("光绘圆弧半径不一致")
    begin = math.atan2(start[1] - center[1], start[0] - center[0])
    finish = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = (finish - begin) % (2 * math.pi)
    if clockwise:
        sweep -= 2 * math.pi
    elif abs(sweep) < 1e-12:
        sweep = 2 * math.pi
    step = 2 * math.acos(max(-1.0, 1 - ARC_TOL_MM / radius))
    count = max(1, math.ceil(abs(sweep) / max(step, 1e-6)))
    return [start] + [(center[0] + radius * math.cos(begin + sweep * i / count),
                      center[1] + radius * math.sin(begin + sweep * i / count))
                     for i in range(1, count)] + [end]


def aperture_geometry(spec, position):
    name, params, macro = spec
    x, y = position
    if name == "C":
        return Point(x, y).buffer(params[0] / 2, quad_segs=128)
    if name == "R":
        return box(x - params[0] / 2, y - params[1] / 2,
                   x + params[0] / 2, y + params[1] / 2)
    if name == "O":
        width, height = params[:2]
        if width >= height:
            return LineString([(x - (width - height) / 2, y), (x + (width - height) / 2, y)]) \
                .buffer(height / 2, quad_segs=128)
        return LineString([(x, y - (height - width) / 2), (x, y + (height - width) / 2)]) \
            .buffer(width / 2, quad_segs=128)
    if macro:
        values = [float(item) for item in macro.rstrip("*").split(",")]
        if values[0] != 4 or values[1] != 1:
            raise ValueError("不支持该光圈宏，不能臆造铜形状")
        vertices = int(values[2]) + 1
        points = list(zip(values[3:3 + vertices * 2:2], values[4:3 + vertices * 2:2]))
        poly = Polygon(points)
        if not poly.is_valid:
            raise ValueError("光圈宏轮廓无效")
        return affinity.translate(affinity.rotate(poly, values[-1], origin=(0, 0)), x, y)
    raise ValueError("不支持的光圈：" + name)


def parse_gerber(text):
    fmt = re.search(r"%FSLAX(\d)(\d)Y(\d)(\d)\*%", text)
    if not fmt or fmt.group(2) != fmt.group(4) or "%MOMM*%" not in text:
        raise ValueError("仅接受本次导出的毫米、前导零省略、绝对坐标光绘格式")
    scale = 10 ** int(fmt.group(2))
    macros = {match.group(1): match.group(2).replace("\n", "").replace("\r", "")
              for match in re.finditer(r"%AM([^*]+)\*(.*?)%", text, re.S)}
    apertures = {}
    for match in re.finditer(r"%ADD(\d+)([^,*]+)(?:,([^*]+))?\*%", text):
        name = match.group(2)
        params = tuple(float(item) for item in (match.group(3) or "").split("X") if item)
        apertures[int(match.group(1))] = (name if name not in macros else "MACRO", params, macros.get(name))
    stripped = re.sub(r"%.*?%", "", text, flags=re.S)
    section, aperture, position, interpolation = None, None, (0.0, 0.0), 1
    inside_region, contour, region_count, arc_count = False, [], 0, 0
    copper, other_shapes, outline_paths, signatures = [], [], [], Counter()
    outline_path = []
    for raw in stripped.split("*"):
        token = raw.strip()
        if not token:
            continue
        if token.startswith("G04"):
            if token.endswith(" Start"):
                section = token[4:-6].strip()
            elif token.endswith(" End"):
                section = None
            continue
        if token == "G36":
            if inside_region or section != "Copper":
                raise ValueError("区域命令不在新增覆铜分段或嵌套区域")
            inside_region, contour = True, []
            region_count += 1
            continue
        if token == "G37":
            if not inside_region:
                raise ValueError("区域结束命令失配")
            if contour:
                copper.append(region_geometry(contour))
            inside_region, contour = False, []
            continue
        if token in ("G75", "M02"):
            continue
        modes = re.findall(r"G0?([123])(?=[XYIJD]|$)", token)
        if modes:
            interpolation = int(modes[-1])
        selection = re.fullmatch(r"(?:G54)?D(\d+)", token)
        if selection and int(selection.group(1)) >= 10:
            aperture = apertures[int(selection.group(1))]
            continue
        fields = {key: int(value) for key, value in re.findall(r"([XYIJ])([+-]?\d+)", token)}
        operation = re.search(r"D0?([123])$", token)
        if not operation or not fields:
            raise ValueError("未解析的光绘绘图命令：" + token[:100])
        op = int(operation.group(1))
        end = (fields.get("X", round(position[0] * scale)) / scale,
               fields.get("Y", round(position[1] * scale)) / scale)
        if op == 2:
            if inside_region:
                if contour:
                    copper.append(region_geometry(contour))
                contour = [end]
            if section == "PolygonModel":
                if outline_path:
                    outline_paths.append(outline_path)
                outline_path = [end]
        elif op == 1:
            points = [position, end]
            center = None
            if interpolation in (2, 3):
                center = (position[0] + fields.get("I", 0) / scale,
                          position[1] + fields.get("J", 0) / scale)
                points = arc_points(position, end, center, interpolation == 2)
                arc_count += 1
            if inside_region:
                if not contour:
                    raise ValueError("区域缺少起点")
                contour.extend(points[1:])
            elif section == "PolygonModel":
                outline_path.extend(points[1:])
            else:
                if aperture is None or aperture[0] != "C":
                    raise ValueError("仅接受圆形光圈绘制连接线")
                shape = LineString(points).buffer(aperture[1][0] / 2, quad_segs=128)
                if section == "Copper":
                    copper.append(shape)
                else:
                    other_shapes.append((section, shape))
                    signatures[(section, "draw", aperture, interpolation, position, end, center)] += 1
        elif op == 3:
            if aperture is None or inside_region:
                raise ValueError("光绘闪光命令状态错误")
            shape = aperture_geometry(aperture, end)
            if section == "Copper":
                copper.append(shape)
            else:
                other_shapes.append((section, shape))
                signatures[(section, "flash", aperture, end)] += 1
        position = end
    if inside_region:
        raise ValueError("光绘区域未结束")
    if outline_path:
        outline_paths.append(outline_path)
    return {"new_copper": unary_union(copper), "other_shapes": other_shapes,
            "signatures": signatures, "outline_paths": outline_paths,
            "region_count": region_count, "arc_count": arc_count, "copper_primitive_count": len(copper)}


def ring_equivalent(a, b, tolerance=0.00003):
    def without_close(points):
        return points[:-1] if math.dist(points[0], points[-1]) < tolerance else points
    a, b = without_close(a), without_close(b)
    if len(a) != len(b):
        return False
    for offset in range(len(a)):
        for direction in (1, -1):
            if all(math.dist(point, a[(offset + direction * i) % len(a)]) < tolerance
                   for i, point in enumerate(b)):
                return True
    return False


def paint(ax, geometry, color, alpha=1):
    if geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        ax.fill(*geometry.exterior.xy, color=color, alpha=alpha, linewidth=0)
        for hole in geometry.interiors:
            ax.fill(*hole.xy, color="white", linewidth=0)
    elif hasattr(geometry, "geoms"):
        for item in geometry.geoms:
            paint(ax, item, color, alpha)


def main():
    layout = json.loads((OUT / "source-layout.json").read_text(encoding="utf-8-sig"))
    config = json.loads((ROOT / "config" / "pcb-shell-v1.json").read_text(encoding="utf-8-sig"))
    antenna_u = -config["board"]["antenna_copper_keepout_x_min"]
    antenna = box(-1000, -1000, antenna_u, 1000)
    slots = [(slot["name"], Polygon(slot["uv"])) for slot in layout["cutouts"]]
    baseline = OUT / "baseline-gerber.zip"
    candidate = OUT / "copper-gerber.zip"
    report = {"scope": "仅核对独立覆铜副本新增光绘铜面与连接线；不替换交付设计或实物验收",
              "arcSagittaToleranceMm": ARC_TOL_MM, "units": "mm",
              "sourceHashes": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in (baseline, candidate)}, "layers": {}}
    plots = []
    with zipfile.ZipFile(baseline) as before_zip, zipfile.ZipFile(candidate) as after_zip:
        old_outline = parse_gerber(before_zip.read("Gerber_BoardOutlineLayer.GKO").decode("ascii"))
        new_outline = parse_gerber(after_zip.read("Gerber_BoardOutlineLayer.GKO").decode("ascii"))
        expected = [layout["outline_uv"], *[slot["uv"] for slot in layout["cutouts"]]]
        outline_matches = all(any(ring_equivalent(a, b) for a in new_outline["outline_paths"]) for b in expected)
        report["physicalOutline"] = {"pathCount": len(new_outline["outline_paths"]),
            "matchesLayoutIncludingCutout": len(expected) == len(new_outline["outline_paths"]) and outline_matches,
            "matchesBaseline": len(old_outline["outline_paths"]) == len(new_outline["outline_paths"]) and
                all(any(ring_equivalent(a, b) for a in new_outline["outline_paths"])
                    for b in old_outline["outline_paths"])}
        for name in ("Gerber_TopLayer.GTL", "Gerber_BottomLayer.GBL"):
            before = parse_gerber(before_zip.read(name).decode("ascii"))
            after = parse_gerber(after_zip.read(name).decode("ascii"))
            if not before["new_copper"].is_empty:
                raise ValueError("原版已有覆铜，不能把候选覆铜分段全部当成新增铜")
            copper = after["new_copper"]
            violations = copper.intersection(antenna)
            slot_checks = [{"name": label, "overlapAreaMm2": copper.intersection(slot).area,
                            "clearanceMm": copper.distance(slot)} for label, slot in slots]
            existing_antenna = [(section, shape) for section, shape in before["other_shapes"]
                                if shape.intersection(antenna).area > 1e-8]
            deleted = before["signatures"] - after["signatures"]
            added = after["signatures"] - before["signatures"]
            report["layers"][name] = {"newCopperAreaMm2": copper.area, "newCopperBoundsUvMm": list(copper.bounds),
                "newCopperG36Regions": after["region_count"], "circularArcCommandsParsed": after["arc_count"],
                "newCopperPrimitiveCount": after["copper_primitive_count"],
                "newCopperAntennaOverlapAreaMm2": violations.area, "newCopperAntennaClearanceMm": copper.distance(antenna),
                "newCopperTouchesAntennaBoundary": not violations.is_empty,
                "newCopperBoundaryIntersectionLengthMm": violations.length,
                "strictClosedAntennaRegionDisjoint": violations.is_empty,
                "cutouts": slot_checks, "existingPadViaTrackRecordsUnchanged": not deleted and not added,
                "missingExistingRecords": sum(deleted.values()), "addedNonPourRecords": sum(added.values()),
                "existingGerberObjectsInAntennaZoneBySection": dict(Counter(section for section, _ in existing_antenna)),
                "passed": not copper.is_empty and violations.area < 1e-8 and all(item["overlapAreaMm2"] < 1e-8 for item in slot_checks)
                          and not deleted and not added}
            plots.append((name, copper, existing_antenna))
    report["passed"] = all(layer["passed"] for layer in report["layers"].values()) and all(
        report["physicalOutline"][key] for key in ("matchesLayoutIncludingCutout", "matchesBaseline"))
    report["limitations"] = ["已有 C5/C6 焊盘及部分原导线进入当前 X≥52 mm 限制区，保留并单列，未重新设计",
        "passed 只指面积和原文件保持检查：新增铜接触 X=52 边界，零间距，不满足严格闭集 X≥52 完全无铜的数学条件",
        "圆弧与圆形光圈离散化用于面积核对，边界有约0.00005 mm量级的数值近似；不能代替制造商光绘验收",
        "软件与光绘检查不能证明天线射频表现、电池和外壳装配或真实打印质量"]
    destination = OUT / "copper-gerber-geometry-report.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font = FontProperties(fname=r"C:\Windows\Fonts\msyh.ttc")
    fig, axes = plt.subplots(1, 2, figsize=(12, 8))
    for ax, (name, copper, old_objects) in zip(axes, plots):
        ax.axvspan(-62, antenna_u, color="#f8d6b3", alpha=0.65)
        paint(ax, copper, "#22957a")
        for _, shape in old_objects:
            paint(ax, shape, "#bc3636")
        for path in new_outline["outline_paths"]:
            ax.plot(*zip(*path), color="#4f5660", linewidth=0.7)
        for _, slot in slots:
            ax.plot(*slot.exterior.xy, color="#d74747", linewidth=1)
        ax.axvline(antenna_u, color="#dd7b24", linewidth=1, linestyle="--")
        ax.set_xlim(-62, 61)
        ax.set_ylim(-99, 45)
        ax.set_aspect("equal")
        ax.set_title("顶层新增铜" if name.endswith("GTL") else "底层新增铜", fontproperties=font)
        ax.set_xlabel("电路板横坐标 U（毫米，U=-X）", fontproperties=font)
        ax.set_ylabel("电路板纵坐标 V（毫米，V=Z）", fontproperties=font)
        ax.grid(alpha=0.15)
    fig.suptitle("绿色：新增地铜；红色：原有天线区铜；橙色：当前天线限制区", fontproperties=font)
    fig.tight_layout()
    fig.savefig(OUT / "copper-gerber-geometry.png", dpi=140)
    plt.close(fig)
    print(json.dumps({"passed": report["passed"], "report": str(destination),
                      "layers": report["layers"], "physicalOutline": report["physicalOutline"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
