"""生成单板自焊开关版的订单清单及静态检查报告。

仅在单板副本规则检查零项、生产资料已重新导出后运行。机器下单文件沿用 UTF-16 制表符格式。
铜线、过孔、焊盘、外框与单主板 v2 完全相同；相对 v2 只改采购/不装属性。
"""

import csv
import json
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

from package_economy_board import (
    GEOMETRY_FIELDS, board_records, bodies, component_refs, digest, dump,
    gerber_paths, individual_bom, read_rows, write_rows,
)

ROOT = Path(__file__).resolve().parents[1]
NAME = "gun-mouse-economy-single-v4"
SOURCE = ROOT / "deliverables" / "evt-a" / "制板文件"
EXPORT = ROOT / "outputs" / "economy-single-eda"
OUT = ROOT / "deliverables" / "经济型单板自焊版" / "制板文件"
REPORTS = OUT.parent / "检查报告"
V1_NATIVE = ROOT / "pcb" / "gun-mouse-v1" / "pcb" / "PCB1.epcb2"
V2_NATIVE = ROOT / "pcb" / "gun-mouse-economy-v2" / "pcb" / "PCB1.epcb2"
V2_GERBER = ROOT / "deliverables" / "经济型改版" / "制板文件" / "gun-mouse-economy-v2-Gerber.zip"
NEW_NATIVE = ROOT / "pcb" / NAME / "pcb" / "PCB1.epcb2"
OMIT = {"U1", "R10", "R11", "R12", "C7", "C8", "J3", "J4", "J5", "U4"}
REMOVED = {"SW4", "J6"}
CHANGED = {"R3"}


def gerber_features(text):
    """按光圈定义解析闪光、线段和区域；光圈编号重排不算图形变化。"""
    import re
    macros = {m.group(1): m.group(2).strip() for m in re.finditer(r"%AM([^*]+)\*(.*?)%", text, re.S)}
    apertures = {m.group(1): (m.group(2), macros.get(m.group(2), ""), m.group(3))
                 for m in re.finditer(r"%ADD(\d+)([^,*]+)(?:,([^*]*))?\*%", text)}
    body = re.sub(r"%.*?%", "", text, flags=re.S)
    current, x, y, region, points, features = None, 0, 0, False, [], Counter()
    for command in body.split("*"):
        command = command.strip()
        if not command or command.startswith("G04"):
            continue
        if command == "G36":
            region, points = True, []
            continue
        if command == "G37":
            region = False
            features[("REGION", tuple(points))] += 1
            continue
        m = re.match(r"(?:G54)?D(\d+)$", command)
        if m and int(m.group(1)) >= 10:
            current = apertures.get(m.group(1))
            continue
        m = re.match(r"(G0?[123])?(?:X(-?\d+))?(?:Y(-?\d+))?(?:I(-?\d+))?(?:J(-?\d+))?D0?([123])$", command)
        if m:
            nx = int(m.group(2)) if m.group(2) else x
            ny = int(m.group(3)) if m.group(3) else y
            if region:
                points.append((m.group(6), nx, ny))
            elif m.group(6) == "3":
                features[("FLASH", current, nx, ny)] += 1
            elif m.group(6) == "1":
                features[("DRAW", current, min((x, y), (nx, ny)), max((x, y), (nx, ny)))] += 1
            x, y = nx, ny
    return features


def main():
    assert Path.cwd().resolve() == ROOT, "请从本工作树根目录运行"
    originals = [V1_NATIVE, V2_NATIVE, V2_GERBER, SOURCE / "gun-mouse-v1-BOM.csv", SOURCE / "gun-mouse-v1-坐标文件.csv"]
    original_hashes = {str(path.relative_to(ROOT)): digest(path) for path in originals}
    fresh_files = [NEW_NATIVE, EXPORT / "drc.json", EXPORT / "原生物料.csv", EXPORT / "原生坐标.csv",
                   EXPORT / "新主板网表.enet", EXPORT / "新原理图网表.enet", OUT / (NAME + "-Gerber.zip")]
    fresh_hashes = {str(path.relative_to(ROOT)): digest(path) for path in fresh_files}
    drc = json.loads((EXPORT / "drc.json").read_text(encoding="utf-8"))
    assert drc["ok"] and drc["value"]["count"] == 0 and drc["value"]["items"] == []
    assert all(path.stat().st_mtime >= (EXPORT / "drc.json").stat().st_mtime
               for path in fresh_files if path != NEW_NATIVE)

    baseline_bom = individual_bom(read_rows(SOURCE / "gun-mouse-v1-BOM.csv"))
    bom = read_rows(EXPORT / "原生物料.csv")
    bom_refs = individual_bom(bom)
    original_coords = {row["Designator"]: row for row in read_rows(SOURCE / "gun-mouse-v1-坐标文件.csv")}
    native_coords = read_rows(EXPORT / "原生坐标.csv")
    native_by_ref = {row["Designator"]: row for row in native_coords}
    assert len(native_coords) == len(native_by_ref) == 46
    assert set(native_by_ref) == set(original_coords) - REMOVED
    assert len(bom) == 19 and len(bom_refs) == 36
    assert set(bom_refs) == set(native_by_ref) - OMIT
    for ref, row in bom_refs.items():
        if ref in CHANGED:
            continue
        for field in row:
            if field not in {"No.", "Quantity", "Designator"}:
                assert row[field] == baseline_bom[ref][field], (ref, field)
    # R3 与 R1/R2 同一物料行。
    assert bom_refs["R3"] == bom_refs["R1"]
    assert bom_refs["R3"]["Supplier Part"] == "C25905" and bom_refs["R3"]["Value"] == "5.1kΩ"
    assert bom_refs["R5"]["Supplier Part"] == "C25744"
    assert "LED1" in bom_refs and "R4" in bom_refs
    for ref, row in native_by_ref.items():
        for field in GEOMETRY_FIELDS:
            assert row[field] == original_coords[ref][field], (ref, field)

    net = json.loads((EXPORT / "新主板网表.enet").read_text(encoding="utf-8-sig"))
    components = {comp["props"]["Designator"]: comp for comp in net["components"].values()}
    sch_net = json.loads((EXPORT / "新原理图网表.enet").read_text(encoding="utf-8-sig"))
    sch_components = {comp["props"]["Designator"]: comp for comp in sch_net["components"].values()}
    v1_net = json.loads((ROOT / "deliverables" / "pcb-shell-v1" / "制板文件" / "gun-mouse-v1-网表.enet")
                        .read_text(encoding="utf-8"))
    v1_components = {comp["props"]["Designator"]: comp for comp in v1_net["components"].values()}
    assert set(sch_components) == set(components) == set(native_by_ref)
    for ref, comp in components.items():
        for field in ["Unique ID", "Channel ID", "Add into BOM", "Supplier Part"]:
            assert comp["props"][field] == sch_components[ref]["props"][field], (ref, field)
        pins = {pin: p["net"] for pin, p in comp["pinInfoMap"].items()}
        assert pins == {pin: p["net"] for pin, p in sch_components[ref]["pinInfoMap"].items()}, ref
        assert pins == {pin: p["net"] for pin, p in v1_components[ref]["pinInfoMap"].items()}, ref
    for ref in OMIT:
        assert components[ref]["props"]["Add into BOM"] == "no"
    for ref in bom_refs:
        props = components[ref]["props"]
        assert props["Add into BOM"] == "yes", ref
        for field in ["Supplier Part", "Manufacturer Part"]:
            assert props[field] == bom_refs[ref][field], (ref, field)
    u4 = {pin: p["net"] for pin, p in components["U4"]["pinInfoMap"].items()}
    assert u4 == {"1": "USB_DP", "2": "GND", "3": "USB_DN", "4": "USB_DN", "5": "VBUS", "6": "USB_DP"}
    j4 = {pin: p["net"] for pin, p in components["J4"]["pinInfoMap"].items()}
    assert j4 == {"1": "TRIG", "2": "GND", "3": "", "4": ""}

    coords = [dict(row) for row in native_coords if row["Designator"] in bom_refs]
    metadata_changes = {}
    for row in coords:
        ref = row["Designator"]
        if ref in {"R3", "R5"}:
            # EDA 坐标的 Device 沿用库实体名；订单采用本次采购型号。
            before = {field: row[field] for field in ["Device", "Comment", "Value", "Datasheet"]}
            row.update({"Device": bom_refs[ref]["Manufacturer Part"], "Comment": bom_refs[ref]["Comment"],
                        "Value": bom_refs[ref]["Value"], "Datasheet": components[ref]["props"]["Datasheet"]})
            metadata_changes[ref] = {"原库元数据": before, "本订单采购元数据": {f: row[f] for f in before}}
        for field in GEOMETRY_FIELDS:
            assert row[field] == native_by_ref[ref][field], (ref, field)
        assert row["Layer"] == "T"
    assert len(coords) == 36

    v2, native = board_records(V2_NATIVE), board_records(NEW_NATIVE)
    v2_refs, new_refs = component_refs(v2), component_refs(native)
    assert new_refs == v2_refs
    for kind in ["LINE", "VIA", "PAD", "POLY", "PAD_NET", "NET", "PANELIZE"]:
        assert bodies(v2, kind) == bodies(native, kind), kind
    for key, body in bodies(native, "COMPONENT").items():
        before = bodies(v2, "COMPONENT")[key]
        for field in ["x", "y", "angle", "layerId", "pinSwap", "pinSwapInfo"]:
            assert body[field] == before[field], (key, field)
        assert body["attrs"]["Unique ID"] == before["attrs"]["Unique ID"], key
        assert body["attrs"]["Channel ID"] == sch_components[new_refs[key]]["props"]["Channel ID"], key
    counts = Counter(head["type"] for head, _ in native)
    for head, body in native:
        if head["type"] == "PAD_NET":
            _, comp_id, pin, _ = json.loads(head["id"])
            assert components[new_refs[comp_id]]["pinInfoMap"][pin]["net"] == body["padNet"]
    panel = next(iter(bodies(native, "PANELIZE").values()))
    assert not panel["on"] and not panel["showVCutIndicator"]

    layer_compare = {}
    with zipfile.ZipFile(OUT / (NAME + "-Gerber.zip")) as new_zip, zipfile.ZipFile(V2_GERBER) as old_zip:
        outline = new_zip.read("Gerber_BoardOutlineLayer.GKO").decode("ascii")
        paths = gerber_paths(outline)
        assert len(paths) == 2 and all(path[0] == path[-1] for path in paths)
        assert sorted(len(path) - 1 for path in paths) == [4, 76]
        assert "VCUT" not in outline.upper() and "V-CUT" not in outline.upper()
        names = sorted(n for n in new_zip.namelist() if n.startswith(("Gerber_", "Drill_")))
        assert names == sorted(n for n in old_zip.namelist() if n.startswith(("Gerber_", "Drill_")))
        for name in names:
            new_text, old_text = new_zip.read(name).decode("ascii"), old_zip.read(name).decode("ascii")
            if name.startswith("Drill_"):
                strip = lambda t: [line for line in t.splitlines() if not line.startswith(";")]
                same = strip(new_text) == strip(old_text)
            else:
                same = gerber_features(new_text) == gerber_features(old_text)
            assert same, name
            layer_compare[name] = "与单主板v2图形一致"

    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    bom_path, coord_path = OUT / (NAME + "-BOM.csv"), OUT / (NAME + "-坐标文件.csv")
    write_rows(bom_path, bom, csv.QUOTE_MINIMAL, "\n")
    write_rows(coord_path, coords, csv.QUOTE_ALL, "\r\n")
    assert original_hashes == {str(path.relative_to(ROOT)): digest(path) for path in originals}
    assert fresh_hashes == {str(path.relative_to(ROOT)): digest(path) for path in fresh_files}
    (REPORTS / "电路规则检查.json").write_bytes((EXPORT / "drc.json").read_bytes())
    dump(REPORTS / "电路核对.json", {
        "状态": "单板自焊开关版重新审核资料；不是已获批准或已下单的成品",
        "接单条件": "经济型；不能经济型接单则不付款生产，先查明具体器件或工艺原因",
        "工厂物料组数": 19, "每套工厂器件数": 36, "贴装面": "仅顶层", "制板款数": 1,
        "原生器件总数": 46, "已从电路删除": sorted(REMOVED), "不装": sorted(OMIT),
        "不装依据": {"U1": "改用已有GY-601N1-LSM6DSV16X模块", "R10_R11": "模块自带2.2k总线上拉",
                   "R12": "3V3到IMU_CS的上拉只服务U1-12；模块已有CS上拉",
                   "C7_C8": "U1局部去耦；主板C4/C5/C6及模块本地去耦保留", "无需替代焊接或跳线": True,
                   "J3_J4_J5": "三个PH2.0座同为C295747扩展料，全部不装免一种换料费；电池、扳机开关、触摸电极线由用户直接焊到原1.0×3.8毫米焊盘"},
        "保留充电灯": {"LED1": "C2286", "R4": "C11702", "原因": "CHRG只接LED1，主控读不到充电状态；两套仅约1.2元"},
        "采购修正": {ref: {field: bom_refs[ref][field] for field in [
            "Value", "Manufacturer Part", "Supplier Part", "Footprint"]} for ref in ["R3", "R5"]},
        "R3依据": "TP4056充电电流≈1200/R：5.1k约235mA（6.8k约176mA）；与R1/R2同料，少一种物料。首件按说明测充电温度",
        "U4不装依据": {"原因": "免换料的SRV05-4（C7420376/C20615829/C85364）国内库存不足，C558418无库存；用户选择不装而不多付20元换料费",
                     "电路": "本板U4的1、6脚同为USB_DP且有铜线直连，3、4脚同为USB_DN且有铜线直连；不装时USB数据线与VBUS仍连通，充电和下载正常",
                     "代价": "USB口无静电保护；插线前先放掉身上静电",
                     "以后要装": "原设计USBLC6-2SC6/C7519可直接焊回同一焊盘"},
        "原生采购与订单清单逐项一致": True, "坐标采购元数据修正": metadata_changes,
        "最终36坐标与新原生几何逐字段一致": True, "几何核对字段": GEOMETRY_FIELDS,
        "实际PCB图元计数": {kind: counts[kind] for kind in ["COMPONENT", "LINE", "VIA", "PAD", "POLY", "PAD_NET"]},
        "铜线_过孔_焊盘_外框_拼板设置与单主板v2完全一致": True,
        "Gerber逐层与单主板v2比较": layer_compare,
        "原理图与电路板全部46器件身份_通道关联_不装属性_采购料号_引脚网络一致": True,
        "46器件引脚网络与正式板v1逐脚一致": True,
        "原生不装标志": {ref: components[ref]["props"]["Add into BOM"] for ref in sorted(OMIT)},
        "直接焊线焊盘": {"J3": "1脚VBAT(+)、2脚GND(-)；与USB口金属外壳导通的是负极", "J4": j4,
                     "J4接法": "SS-01GL的COM与NO两根线直接焊到J4的1、2脚焊盘，两线对调不影响，NC不接",
                     "J5": "1、2脚同为TOUCH，触摸电极线焊任一焊盘"},
        "V割软件标志关闭": True, "生产板框闭合轮廓数": len(paths), "闭合轮廓边数": [len(path) - 1 for path in paths],
        "未装器件锡膏": "嘉立创答复只对贴装器件开钢网上锡，未贴位置不上锡：https://m.jlc.com/portal/server_guide_4026.html",
        "尚待确认": ["国内本次全部待装器件获批经济型，包括潮敏及温度适配审查",
                   "SRV05-4与U2在国内匹配页是否显示免换料；不免时按扩展库20元/种",
                   "X射线检查等实际附加费",
                   "实物装配、扳机手感、模块固定、充电温度、固件和游戏验收"],
        "设计规则检查错误数": 0, "规则证据文件": "电路规则检查.json",
        "源只读文件SHA256": original_hashes, "本次导出SHA256": fresh_hashes,
        "订单清单SHA256": {path.name: digest(path) for path in [bom_path, coord_path]},
    })
    write_cost()
    print(json.dumps({"BOM": str(bom_path), "坐标": str(coord_path), "物料组": 19, "器件": 36}, ensure_ascii=False))


def write_cost():
    d = Decimal
    # 原用户截图两套器件172.54元；扣不代焊U1、原SW4、R10/R11组、小板J6及J3～J5（按J6单价1.454元/只）。
    # R3/U4/R12/C7/C8差额很小，不再扣。U4 不装，SMT 焊点每套再少 6 个。
    material = d("172.54") - sum(map(d, ["41.86", "62.60", ".326", "2.908", "8.724"]))
    processing = {"工程费": d("50"), "普通扩展贴片料上料_USB1_U3_SW3": d("60"), "插件工程费": d("20"),
                  "每套61个插件焊点_两套": d("12.20"), "每套94个贴片焊点_两套": d("1.88"), "确认可制造性": d("3")}
    fixed = sum(processing.values())
    total = material + fixed
    factory_v3 = {"低": d("313.13") + d("1.224"), "高": d("363.13") + d("1.224")}
    dump(REPORTS / "费用推算-单板自焊.json", {
        "状态": "条件费用示例，未取得本订单报价",
        "数量条件": "工厂焊两块主板；用户只有1个旧GY模块，先装1套完整样机，另1块主板备用",
        "器件估算来源": "原截图两套器件172.54元，扣U1两件41.86、原SW4两件62.60、R10/R11采购组0.326、J6两件2.908、J3～J5六件8.724",
        "器件估算元": str(material),
        "加工条件估算元": {k: str(v) for k, v in processing.items()},
        "加工小计元": str(fixed),
        "U4": "不装：免换料的SRV05-4国内库存不足，不再多付20元换C7519",
        "下单页实际报价_删除U4前": {"元件费": "41.75", "加工费": "147.2", "说明": "加工费与本推算一致；删除U4后加工费约147.08，个性化服务（氮气焊接5.2元）可选"},
        "多款板费": "单款主板，不再有扳机小板的第二款费用（公开表经济型50元/款）",
        "两块部分装配主板条件合计元": str(total.quantize(d(".01"))),
        "用户自购": {"SS-01GL两只": "约5～9元（零售约2.35～4.24元/只，含运费看渠道）",
                   "M2杯头内六角与螺母": "约10～20元（M2×10与M2×20两种，含合壳与压框）",
                   "PH2.0线": "不需要；电池、开关、触摸线直接焊在主板焊盘上"},
        "对比工厂代焊小板版": {"原推算区间元_恢复充电灯后": {k: str(v) for k, v in factory_v3.items()},
                         "本版约少": "约100～155元：多款板费50～100元，J3～J5与U4不装省换料费40元和座子约8.7元，另含开关代焊约9.1元、J6约3.0元，扣自购开关约5～9元"},
        "未计或未知费用": ["光板制板费、运费、打印费", "工艺边、夹具、X射线检查",
                       "新订单元件价格、最低购买量、库存、免换料资格变化"],
        "公开规则查阅日期": "2026-10-07",
        "公开收费表": "https://pbt-pub.jlc.com/pbt/cms/c8f17f24-22cd-4403-a1b0-c7c93b70365a-image.png",
        "经济型工艺说明": "https://www.jlc.com/portal/server_guide_30669.html",
        "换料费官方说明": "https://m.jlc.com/portal/server_guide_38538.html",
    })


if __name__ == "__main__":
    main()
