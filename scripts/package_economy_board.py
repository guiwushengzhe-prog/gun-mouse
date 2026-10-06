"""核对并打包单主板、自装扳机的备选资料；不替代工厂焊扳机方案。

保留嘉立创原生的 UTF-16、制表符字段模式。仅写新的订单清单和
电路检查报告，不修改原工程、新工程、铜层或焊盘。
"""

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deliverables" / "evt-a" / "制板文件"
EXPORT = ROOT / "outputs" / "economy-eda"
OUT = ROOT / "deliverables" / "经济型改版" / "制板文件"
REPORTS = OUT.parent / "检查报告"
OLD_NATIVE = ROOT / "pcb" / "gun-mouse-v1" / "pcb" / "PCB1.epcb2"
NEW_NATIVE = ROOT / "pcb" / "gun-mouse-economy-v2" / "pcb" / "PCB1.epcb2"
OMIT = {"U1", "R10", "R11"}
REMOVED = {"SW4", "J6"}
GEOMETRY_FIELDS = [
    "Footprint", "Mid X", "Mid Y", "Ref X", "Ref Y", "Pad X", "Pad Y",
    "Pins", "Layer", "Rotation", "SMD",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path):
    raw = path.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    return list(csv.DictReader(io.StringIO(raw.decode(encoding)), delimiter="\t"))


def write_rows(path, rows, quoting, newline):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t",
                            quoting=quoting, lineterminator=newline)
    writer.writeheader()
    writer.writerows(rows)
    path.write_bytes(stream.getvalue().encode("utf-16"))
    assert read_rows(path) == rows, "订单清单序列化后内容改变"


def board_records(path):
    """只统计实际 PCB 文档，忽略封装库图元和空体删除标记。"""
    records, inside = [], False
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        head, body = line.split("||", 1)
        head, body = json.loads(head), body.rstrip("|")
        if head["type"] == "DOCHEAD":
            inside = bool(body) and json.loads(body).get("docType") == "PCB"
        if inside and body:
            records.append((head, json.loads(body)))
    return records


def bodies(records, kind):
    return {head["id"]: body for head, body in records if head["type"] == kind}


def component_refs(records):
    return {body["parentId"]: body["value"] for head, body in records
            if head["type"] == "ATTR" and body["key"] == "Designator"}


def individual_bom(rows):
    result = {}
    for row in rows:
        refs = [ref.strip() for ref in row["Designator"].split(",")]
        assert len(refs) == int(row["Quantity"]), row
        for ref in refs:
            assert ref not in result, ref
            result[ref] = row
    return result


def gerber_paths(text):
    paths = []
    for match in re.finditer(r"G0[123]X(-?\d+)Y(-?\d+)D0([12])\*", text):
        point = [int(match[1]) / 1e5, int(match[2]) / 1e5]
        if match[3] == "2":
            paths.append([point])
        else:
            assert paths, "板框绘制缺少起点"
            paths[-1].append(point)
    return paths


def paste_features(text):
    features, polygon = [], None
    for line in text.splitlines():
        if line == "G36*":
            polygon = []
        elif line == "G37*":
            points = polygon[:-1] if polygon[0] == polygon[-1] else polygon
            features.append({"类型": "区域", "中心毫米": [
                sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points)]})
            polygon = None
        else:
            match = re.search(r"G0[123]X(-?\d+)Y(-?\d+)D0([123])\*", line)
            if match:
                point = [int(match[1]) / 1e5, int(match[2]) / 1e5]
                if polygon is not None:
                    polygon.append(point)
                elif match[3] == "3":
                    features.append({"类型": "焊盘闪点", "中心毫米": point})
    return features


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    assert Path.cwd().resolve() == ROOT, "请从本工作树根目录运行"
    source_files = [OLD_NATIVE, SOURCE / "gun-mouse-v1-BOM.csv",
                    SOURCE / "gun-mouse-v1-坐标文件.csv"]
    source_hashes = {str(path.relative_to(ROOT)): digest(path) for path in source_files}
    fresh_files = [NEW_NATIVE, EXPORT / "原生物料.csv", EXPORT / "原生坐标.csv",
                   EXPORT / "新主板网表.enet", EXPORT / "drc.json",
                   OUT / "gun-mouse-economy-v2-Gerber.zip"]
    export_hashes = {str(path.relative_to(ROOT)): digest(path) for path in fresh_files}
    drc = json.loads((EXPORT / "drc.json").read_text(encoding="utf-8"))
    assert drc["ok"] and drc["value"]["count"] == 0 and drc["value"]["items"] == []
    assert all(path.stat().st_mtime >= (EXPORT / "drc.json").stat().st_mtime
               for path in fresh_files if path != NEW_NATIVE)

    baseline_bom = individual_bom(read_rows(SOURCE / "gun-mouse-v1-BOM.csv"))
    bom = read_rows(EXPORT / "原生物料.csv")
    bom_refs = individual_bom(bom)
    original_coords = {row["Designator"]: row for row in
                       read_rows(SOURCE / "gun-mouse-v1-坐标文件.csv")}
    native_coords = read_rows(EXPORT / "原生坐标.csv")
    native_by_ref = {row["Designator"]: row for row in native_coords}
    assert len(native_by_ref) == len(native_coords) == 46
    assert set(native_by_ref) == set(original_coords) - REMOVED
    assert set(bom_refs) == set(native_by_ref) - OMIT
    assert len(bom) == 22 and len(bom_refs) == 43
    assert not (set(bom_refs) & (OMIT | REMOVED))
    for ref, row in bom_refs.items():
        for field in row:
            if field not in {"No.", "Quantity", "Designator"}:
                assert row[field] == baseline_bom[ref][field], (ref, field)
    for ref in native_by_ref:
        for field in GEOMETRY_FIELDS:
            assert native_by_ref[ref][field] == original_coords[ref][field], (ref, field)

    coords = [dict(row) for row in native_coords if row["Designator"] in bom_refs]
    for row in coords:
        ref = row["Designator"]
        if ref in {"R3", "R5"}:
            # EDA 坐标的 Device 是旧库实体名；订单采用已修正的采购型号。
            row["Device"] = bom_refs[ref]["Manufacturer Part"]
            row["Datasheet"] = original_coords[ref]["Datasheet"]
        expected_device = (bom_refs[ref]["Manufacturer Part"] if ref in {"R3", "R5"}
                           else original_coords[ref]["Device"])
        assert row["Device"] == expected_device, ref
        assert row["Layer"] == "T"
    assert len(coords) == 43

    original, native = board_records(OLD_NATIVE), board_records(NEW_NATIVE)
    old_refs, new_refs = component_refs(original), component_refs(native)
    assert set(new_refs.values()) == set(native_by_ref)
    original_lines, new_lines = bodies(original, "LINE"), bodies(native, "LINE")
    removed_lines = {key: value for key, value in original_lines.items() if key not in new_lines}
    assert len(original_lines) == 575 and len(new_lines) == 567
    assert len(removed_lines) == 8
    assert all(value["netName"] in {"D_COM", "D_NO"} for value in removed_lines.values())
    assert all(key in original_lines and value == original_lines[key]
               for key, value in new_lines.items())
    assert bodies(original, "VIA") == bodies(native, "VIA")
    for kind in ["COMPONENT", "PAD_NET"]:
        old, new = bodies(original, kind), bodies(native, kind)
        for key, body in new.items():
            if kind == "PAD_NET":
                assert body == old[key], key
            else:
                for field in ["x", "y", "angle", "layerId", "pinSwap", "pinSwapInfo"]:
                    assert body[field] == old[key][field], (key, field)
                for field in ["Unique ID", "Channel ID"]:
                    assert body["attrs"][field] == old[key]["attrs"][field], (key, field)
    assert len(bodies(native, "VIA")) == 95 and len(bodies(native, "PAD")) == 5
    assert len(bodies(native, "POLY")) == 2
    panel = next(iter(bodies(native, "PANELIZE").values()))
    assert not panel["on"] and not panel["showVCutIndicator"]
    assert all(not panel[key]["on"] for key in [
        "horizontalStamp", "verticalStamp", "horizontalSize", "verticalSize"])

    net = json.loads((EXPORT / "新主板网表.enet").read_text(encoding="utf-8-sig"))
    components = {comp["props"]["Designator"]: comp for comp in net["components"].values()}
    assert set(components) == set(native_by_ref)
    for ref in OMIT:
        assert components[ref]["props"]["Add into BOM"] == "no"
    for ref in bom_refs:
        props = components[ref]["props"]
        assert props["Add into BOM"] == "yes", ref
        assert props["Supplier Part"] == bom_refs[ref]["Supplier Part"], ref
        assert props["Manufacturer Part"] == bom_refs[ref]["Manufacturer Part"], ref
    for head, body in native:
        if head["type"] == "PAD_NET":
            _, comp_id, pin, _ = json.loads(head["id"])
            assert components[new_refs[comp_id]]["pinInfoMap"][pin]["net"] == body["padNet"]
    j4 = components["J4"]["pinInfoMap"]
    assert j4["1"]["net"] == "TRIG" and j4["2"]["net"] == "GND"
    assert j4["3"]["net"] == "" and j4["4"]["net"] == ""

    with zipfile.ZipFile(OUT / "gun-mouse-economy-v2-Gerber.zip") as archive:
        outline = archive.read("Gerber_BoardOutlineLayer.GKO").decode("ascii")
        paste = archive.read("Gerber_TopPasteMaskLayer.GTP").decode("ascii")
        paths = gerber_paths(outline)
        assert len(paths) == 2 and all(path[0] == path[-1] for path in paths)
        assert sorted(len(path) - 1 for path in paths) == [4, 76]
        assert "VCUT" not in outline.upper() and "V-CUT" not in outline.upper()
    all_features = paste_features(paste)
    paste_at_omitted = {}
    for ref, x, y, dx, dy in [("U1", 8, 29, 1.6, 1.4),
                              ("R10", 10, 24.8, .6, .8), ("R11", 12.5, 24.8, .6, .8)]:
        paste_at_omitted[ref] = [feature for feature in all_features
                                if abs(feature["中心毫米"][0] - x) < dx
                                and abs(feature["中心毫米"][1] - y) < dy]
    assert {ref: len(features) for ref, features in paste_at_omitted.items()} == {
        "U1": 14, "R10": 2, "R11": 2}

    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    bom_path = OUT / "gun-mouse-economy-v2-备选单主板-BOM.csv"
    coord_path = OUT / "gun-mouse-economy-v2-备选单主板-坐标文件.csv"
    write_rows(bom_path, bom, csv.QUOTE_MINIMAL, "\n")
    write_rows(coord_path, coords, csv.QUOTE_ALL, "\r\n")
    assert source_hashes == {str(path.relative_to(ROOT)): digest(path) for path in source_files}
    assert export_hashes == {str(path.relative_to(ROOT)): digest(path) for path in fresh_files}
    (REPORTS / "电路规则检查-备选单主板.json").write_bytes((EXPORT / "drc.json").read_bytes())
    report = {
        "状态": "单主板、自行安装扳机开关的备选；不满足工厂采购并焊好扳机的最终要求",
        "禁止误用": "不能把本备选清单与恢复扳机小板后的生产文件混用",
        "工厂物料组数": 22, "每板工厂器件数": 43, "贴装面": "仅顶层",
        "源工程器件数": 46, "不装": sorted(OMIT), "已删除小板器件": sorted(REMOVED),
        "采购核对": {ref: {field: bom_refs[ref][field] for field in [
            "Value", "Manufacturer Part", "Supplier Part", "Footprint"]} for ref in ["R3", "R5"]},
        "几何核对字段": GEOMETRY_FIELDS,
        "保留46器件几何与原板一致": True, "最终43坐标与新原生几何一致": True,
        "坐标采购元数据修正": "R3/R5 的 Device 改为本订单制造商型号；位置、角度、封装未变",
        "实际PCB图元计数_不含封装库及空体删除标记": dict(Counter(head["type"] for head, _ in native)),
        "原实际铜线数": 575, "保留铜线数": 567, "仅删除8小板铜线": True,
        "保留铜线和95过孔体完全一致": True, "保留器件焊盘网络完全一致": True,
        "原生与导出网表引脚网络一致": True,
        "扳机接口J4": {"1": "TRIG", "2": "GND", "3和4": "机械固定焊脚，无电气网络"},
        "原生不装标志": {ref: components[ref]["props"]["Add into BOM"] for ref in sorted(OMIT)},
        "原生拼板与V割标志均关闭": True,
        "生产板框": {"独立外框数": 1, "外框边数": 76, "内槽数": 1, "内槽边数": 4,
                    "备注": "仍是原主板外形，边界范围约119.3×134.3毫米；不因去小板宣称光板面积费用下降"},
        "锡膏层必须交工厂处理": {
            "当前原始顶层锡膏层仍含留空位置": {ref: len(features) for ref, features in paste_at_omitted.items()},
            "开钢网和上锡要求": "U1/R10/R11 不装，不给相应焊盘开钢网口，不涂锡膏；铜焊盘和阻焊层保留",
            "证据": "https://m.jlc.com/portal/server_guide_4026.html",
            "依据": "官方回复表示仅给贴装器件开钢网口上锡，未贴位置不上锡；需随本订单不装清单确认",
            "没有声称": "原生GTP已移除这18个图形"},
        "验证边界": "规则检查0项问题和静态一致性通过；尚未取得工厂经济型审核、实际报价和实物功能验收",
        "规则证据文件": "电路规则检查-备选单主板.json",
        "源只读文件SHA256": source_hashes, "本次导出SHA256": export_hashes,
        "订单清单SHA256": {path.name: digest(path) for path in [bom_path, coord_path]},
    }
    dump(REPORTS / "电路核对-备选单主板.json", report)
    material = Decimal("172.54") - sum(map(Decimal, ["41.86", "62.60", ".326", "2.908"]))
    processing = sum(map(Decimal, ["50", "100", "20", "12.20", "2.36", "3"]))
    estimate = {
        "状态": "单主板自装扳机备选的条件推算，不是工厂报价，不适用于恢复扳机小板的方案",
        "数量条件": "2块工厂半成品主板，1块接用户已有GY模块完成样机，另1块备用；不能称2套完整成品",
        "材料原报价来源": "用户截图：原两套器件172.54元；沿用原单价和最少采购量作差",
        "材料扣减元": {"U1两件": "41.86", "SW4两件": "62.60", "R10R11采购组": ".326", "J6两件": "2.908"},
        "材料条件推算元": str(material),
        "加工条件推算元": {"工程费": "50", "五种普通扩展库上料": "100", "插件工程费": "20",
                          "每板61个插件焊点_两板": "12.20", "每板118个贴片焊点_两板": "2.36", "确认可制造性": "3"},
        "加工小计元": str(processing), "合计条件推算元": str((material + processing).quantize(Decimal(".01"))),
        "成立条件": ["工厂批准经济型、只焊顶层、普通工艺和普通厚度",
                     "仅一种主板电路，无自拼多款扳机小板",
                     "U2与R3继续免上料费，五种普通扩展料各20元",
                     "工厂认可焊点分类和器件最少购买量，没有额外工装或检查费"],
        "未知及未计费用": ["恢复扳机小板后的混拼费和新SW4实际SMT价格",
                        "若U2等需要X射线检查，按实际件数另收",
                        "器件代采购价格、库存、最少采购量或免上料资格变动",
                        "异形板工艺边、夹具及工厂工程处理费",
                        "光板费、运费、打印费、线材、扳机开关；已有GY模块不新增采购支出"],
        "公开规则查阅日期": "2026-10-06",
        "公开收费来源": "https://www.jlc.com/portal/server_guide_4025.html",
        "公开收费表": "https://pbt-pub.jlc.com/pbt/cms/c8f17f24-22cd-4403-a1b0-c7c93b70365a-image.png",
        "经济型工艺限制来源": "https://www.jlc.com/portal/server_guide_30669.html",
        "混拼说明": "公开表经济型为50元/款；首款是否含在工程费内未明确，恢复第二款电路后必须重新试算，不能假定免费",
    }
    dump(REPORTS / "电路费用推算-备选单主板.json", estimate)
    print(json.dumps({"status": "backup_only", "bom_groups": len(bom), "assembly_parts": len(coords),
                      "drc_errors": 0, "estimated_yuan_conditional": str(material + processing)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
