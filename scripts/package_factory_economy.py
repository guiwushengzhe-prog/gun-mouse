"""生成工厂采购并代焊扳机版的订单清单及静态检查报告。

仅在新原生工程规则检查零项、生产资料已重新导出后运行；保留
原工程只读。机器下单文件沿用 UTF-16 制表符格式，不添加说明列。
"""

import csv
import json
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

from package_economy_board import (
    GEOMETRY_FIELDS, board_records, bodies, component_refs, digest, dump,
    gerber_paths, individual_bom, paste_features, read_rows, write_rows,
)

ROOT = Path(__file__).resolve().parents[1]
NAME = "gun-mouse-economy-factory-v3"
SOURCE = ROOT / "deliverables" / "evt-a" / "制板文件"
EXPORT = ROOT / "outputs" / "economy-factory-eda"
OUT = ROOT / "deliverables" / "经济型工厂代焊版" / "制板文件"
REPORTS = OUT.parent / "检查报告"
OLD_NATIVE = ROOT / "pcb" / "gun-mouse-v1" / "pcb" / "PCB1.epcb2"
NEW_NATIVE = ROOT / "pcb" / NAME / "pcb" / "PCB1.epcb2"
OMIT = {"U1", "R10", "R11"}


def main():
    assert Path.cwd().resolve() == ROOT, "请从本工作树根目录运行"
    originals = [OLD_NATIVE, SOURCE / "gun-mouse-v1-BOM.csv",
                 SOURCE / "gun-mouse-v1-坐标文件.csv"]
    original_hashes = {str(path.relative_to(ROOT)): digest(path) for path in originals}
    fresh_files = [NEW_NATIVE, EXPORT / "drc.json", EXPORT / "原生物料.csv",
                   EXPORT / "原生坐标.csv", EXPORT / "新主板网表.enet",
                   OUT / (NAME + "-Gerber.zip")]
    fresh_hashes = {str(path.relative_to(ROOT)): digest(path) for path in fresh_files}
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
    assert len(native_coords) == len(native_by_ref) == 48
    assert set(native_by_ref) == set(original_coords)
    assert len(bom) == 23 and len(bom_refs) == 45
    assert set(bom_refs) == set(original_coords) - OMIT
    for ref, row in bom_refs.items():
        if ref != "SW4":
            for field in row:
                if field not in {"No.", "Quantity", "Designator"}:
                    assert row[field] == baseline_bom[ref][field], (ref, field)
    assert bom_refs["SW4"]["Supplier Part"] == "C2896769"
    assert bom_refs["SW4"]["Manufacturer Part"] == "SS-01GL"
    assert bom_refs["SW4"]["Footprint"] == baseline_bom["SW4"]["Footprint"]
    assert bom_refs["R3"]["Supplier Part"] == "C25917"
    assert bom_refs["R5"]["Supplier Part"] == "C25744"
    for ref, row in native_by_ref.items():
        for field in GEOMETRY_FIELDS:
            assert row[field] == original_coords[ref][field], (ref, field)

    net = json.loads((EXPORT / "新主板网表.enet").read_text(encoding="utf-8-sig"))
    components = {comp["props"]["Designator"]: comp for comp in net["components"].values()}
    assert set(components) == set(native_by_ref)
    for ref in OMIT:
        assert components[ref]["props"]["Add into BOM"] == "no"
    for ref in bom_refs:
        props = components[ref]["props"]
        assert props["Add into BOM"] == "yes", ref
        for field in ["Supplier Part", "Manufacturer Part"]:
            assert props[field] == bom_refs[ref][field], (ref, field)
    coords = [dict(row) for row in native_coords if row["Designator"] in bom_refs]
    metadata_changes = {}
    for row in coords:
        ref = row["Designator"]
        if ref in {"R3", "R5", "SW4"}:
            before = {field: row[field] for field in ["Device", "Comment", "Value", "Datasheet"]}
            row.update({"Device": bom_refs[ref]["Manufacturer Part"],
                        "Comment": bom_refs[ref]["Comment"], "Value": bom_refs[ref]["Value"],
                        "Datasheet": components[ref]["props"]["Datasheet"]})
            metadata_changes[ref] = {"原库元数据": before, "本订单采购元数据": {
                field: row[field] for field in before}}
        for field in GEOMETRY_FIELDS:
            assert row[field] == native_by_ref[ref][field], (ref, field)
        assert row["Layer"] == "T"
    assert len(coords) == 45 and {row["Designator"] for row in coords} == set(bom_refs)

    original, native = board_records(OLD_NATIVE), board_records(NEW_NATIVE)
    old_refs, new_refs = component_refs(original), component_refs(native)
    assert new_refs == old_refs
    for kind in ["LINE", "VIA", "PAD", "POLY", "PAD_NET", "NET"]:
        assert bodies(original, kind) == bodies(native, kind), kind
    for key, body in bodies(native, "COMPONENT").items():
        before = bodies(original, "COMPONENT")[key]
        for field in ["x", "y", "angle", "layerId", "pinSwap", "pinSwapInfo"]:
            assert body[field] == before[field], (key, field)
        for field in ["Unique ID", "Channel ID"]:
            assert body["attrs"][field] == before["attrs"][field], (key, field)
    counts = Counter(head["type"] for head, _ in native)
    assert {kind: counts[kind] for kind in ["COMPONENT", "LINE", "VIA", "PAD", "POLY", "PAD_NET"]} == {
        "COMPONENT": 48, "LINE": 575, "VIA": 95, "PAD": 25, "POLY": 2, "PAD_NET": 204}
    for head, body in native:
        if head["type"] == "PAD_NET":
            _, comp_id, pin, _ = json.loads(head["id"])
            assert components[new_refs[comp_id]]["pinInfoMap"][pin]["net"] == body["padNet"]
    expected_pins = {"J4": {"1": "TRIG", "2": "GND", "3": "", "4": ""},
                     "J6": {"1": "D_NO", "2": "D_COM", "3": "", "4": ""},
                     "SW4": {"1": "D_COM", "2": "D_NO", "3": ""}}
    for ref, pins in expected_pins.items():
        assert {pin: value["net"] for pin, value in components[ref]["pinInfoMap"].items()} == pins
    panel = next(iter(bodies(native, "PANELIZE").values()))
    assert not panel["on"] and not panel["showVCutIndicator"]
    assert all(not panel[key]["on"] for key in [
        "horizontalStamp", "verticalStamp", "horizontalSize", "verticalSize"])

    with zipfile.ZipFile(OUT / (NAME + "-Gerber.zip")) as archive:
        outline = archive.read("Gerber_BoardOutlineLayer.GKO").decode("ascii")
        paste = archive.read("Gerber_TopPasteMaskLayer.GTP").decode("ascii")
        paths = gerber_paths(outline)
        assert len(paths) == 2 and all(path[0] == path[-1] for path in paths)
        assert "VCUT" not in outline.upper() and "V-CUT" not in outline.upper()
    all_features = paste_features(paste)
    paste_count = {}
    for ref, x, y, dx, dy in [("U1", 8, 29, 1.6, 1.4),
                              ("R10", 10, 24.8, .6, .8), ("R11", 12.5, 24.8, .6, .8)]:
        paste_count[ref] = sum(abs(feature["中心毫米"][0] - x) < dx
                              and abs(feature["中心毫米"][1] - y) < dy
                              for feature in all_features)
    assert paste_count == {"U1": 14, "R10": 2, "R11": 2}

    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    bom_path, coord_path = OUT / (NAME + "-BOM.csv"), OUT / (NAME + "-坐标文件.csv")
    write_rows(bom_path, bom, csv.QUOTE_MINIMAL, "\n")
    write_rows(coord_path, coords, csv.QUOTE_ALL, "\r\n")
    assert original_hashes == {str(path.relative_to(ROOT)): digest(path) for path in originals}
    assert fresh_hashes == {str(path.relative_to(ROOT)): digest(path) for path in fresh_files}
    (REPORTS / "电路规则检查.json").write_bytes((EXPORT / "drc.json").read_bytes())
    dump(REPORTS / "电路核对.json", {
        "状态": "工厂采购并代焊SS-01GL的重新审核资料；不是已获批准或已下单的成品",
        "工厂物料组数": 23, "每套工厂器件数": 45, "贴装面": "仅顶层",
        "原生器件总数": 48, "不装": sorted(OMIT),
        "保留": ["主板", "扳机小板", "两板连接器", "20邮票孔", "575铜线", "95过孔", "原电气网络和操作逻辑"],
        "采购修正": {ref: {field: bom_refs[ref][field] for field in [
            "Value", "Manufacturer Part", "Supplier Part", "Footprint"]} for ref in ["R3", "R5", "SW4"]},
        "原生采购与订单清单逐项一致": True,
        "坐标采购元数据修正": metadata_changes,
        "保留全部48原生器件几何与原板一致": True,
        "最终45坐标与新原生几何逐字段一致": True, "几何核对字段": GEOMETRY_FIELDS,
        "实际PCB图元计数_不含封装库和空体删除标记": dict(counts),
        "全部铜线_过孔_焊盘_板框_引脚网络与原版体完全一致": True,
        "导出网表与原生全部204引脚网络一致": True,
        "原生不装标志": {ref: components[ref]["props"]["Add into BOM"] for ref in sorted(OMIT)},
        "扳机引脚网络": expected_pins,
        "连接说明": "默认直通成品双头线对应J4的TRIG/GND与J6的D_NO/D_COM；机械COM/NO两根线对调仍按下导通，不能接到未使用的常闭脚",
        "V割软件标志关闭": True, "实际分板方式": "保留原有邮票孔，包含主板和扳机小板两种电路；并非单款单板",
        "生产板框闭合轮廓数": len(paths), "闭合轮廓边数": [len(path) - 1 for path in paths],
        "锡膏层留空要求": {"原始顶层锡膏层仍含": paste_count,
                       "工厂要求": "U1/R10/R11不装，不给相应焊盘开钢网口，不涂锡膏；保留铜焊盘与阻焊层",
                       "未声称": "原始GTP已删除这18个图形",
                       "官方依据": "https://m.jlc.com/portal/server_guide_4026.html"},
        "开关焊盘适配边界": "本报告验证原焊盘位置和网络未变；SS-01GL焊片端子及动作位置的尺寸适配由机械报告核对，不能只凭旧封装名SS-01GL13判断型号相同",
        "尚待确认": ["C2896769在国内SMT的实际库存、供货方式和代焊价格",
                   "剩余全部器件与邮票孔异形两款拼板获批经济型",
                   "工厂混拼、工艺边、夹具、锡膏开口、X射线检查等实际费用",
                   "实物装配、扳机手感、模块固定、固件和游戏验收"],
        "设计规则检查错误数": 0, "规则证据文件": "电路规则检查.json",
        "源只读文件SHA256": original_hashes, "本次导出SHA256": fresh_hashes,
        "订单清单SHA256": {path.name: digest(path) for path in [bom_path, coord_path]},
    })
    material_without_switch = Decimal("172.54") - sum(map(Decimal, ["41.86", "62.60", ".326"]))
    processing_without_mix = sum(map(Decimal, ["50", "100", "20", "12.80", "2.44", "3"]))
    mix_examples = []
    reference_price = Decimal("4.24")
    for mix in [Decimal("50"), Decimal("100")]:
        total = material_without_switch + reference_price * 2 + processing_without_mix + mix
        mix_examples.append({"混拼假设元": str(mix), "示例合计元": str(total.quantize(Decimal(".01")))})
    dump(REPORTS / "费用推算-工厂代焊.json", {
        "状态": "条件费用示例，未取得本订单报价；不得称4.24元是嘉立创SMT单价",
        "数量条件": "工厂焊两套主板和扳机小板；用户只有1个旧GY模块，因此当前只装配1套完整功能样机，另1套电路板备用",
        "器件估算来源": "原用户截图两套器件172.54元，扣不代焊U1两件41.86、原SW4两件62.60、R10R11采购组0.326",
        "不含新SW4的旧单价器件估算元": str(material_without_switch),
        "新SW4": {"型号": "SS-01GL", "料号": "C2896769", "本订单数量": 2,
                "国内SMT实际单价": None, "零售参考仅供示例元": str(reference_price),
                "零售参考来源": "https://item.szlcsc.com/3139927.html"},
        "加工固定条件估算元": {"工程费": "50", "五种普通扩展物料上料": "100", "插件工程费": "20",
                          "每套64个插件焊点_两套": "12.80", "每套122个贴片焊点_两套": "2.44", "确认可制造性": "3"},
        "加工固定小计元": str(processing_without_mix),
        "两款拼板收费待确认": "公开表经济型50元/款；首款是否含在50元工程费中未明确，暂给额外50与100两种口径。标准型原单150元拼板费不能声称已免费",
        "仅以零售4.24作假设的两种示例": mix_examples,
        "计算式": "67.754 + 2×实际SMT新SW4单价 + 188.24 + 工厂确认的两款拼板费 + 其它实际费用",
        "成立条件": ["工厂批准此两款邮票孔拼板经济型、全器件安装于顶层、厚度与工艺可接",
                     "普通扩展五类各20元，U2与R3继续免上料费",
                     "沿用原报价焊点分类、剩余器件单价和最少采购量"],
        "未计或未知费用": ["光板制板费、运费、打印费、连接线",
                       "异形板、工艺边、夹具工程费用",
                       "U2等器件是否仍触发X射线检查",
                       "C2896769是否需新增/代采及对应最少数量和附加费",
                       "新订单元件价格、最低购买量、库存、免上料资格变化"],
        "旧模块新增采购费": "0元，用户已经拥有；模块仍需自行按装配说明连接固定",
        "公开规则查阅日期": "2026-10-06",
        "公开收费说明": "https://www.jlc.com/portal/server_guide_4025.html",
        "公开收费表": "https://pbt-pub.jlc.com/pbt/cms/c8f17f24-22cd-4403-a1b0-c7c93b70365a-image.png",
        "经济型工艺说明": "https://www.jlc.com/portal/server_guide_30669.html",
    })
    print(json.dumps({"assembly_groups": len(bom), "assembly_parts": len(coords),
                      "drc_errors": 0, "factory_switch_supplier_part": "C2896769",
                      "example_totals_yuan_not_quote": mix_examples}, ensure_ascii=True))


if __name__ == "__main__":
    main()
