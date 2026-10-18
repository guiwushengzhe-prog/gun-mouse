"""核对嘉立创原生板与最终外壳孔位，更新原生工程和打板交付包。"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

from final_regular_layout import ROOT, RELEASE

LOG = ROOT/".logs/嘉立创最终版"
OUTPUT = ROOT/"outputs/嘉立创最终版"
NATIVE = ROOT/"pcb/嘉立创最终版"
BOARD_DIR = RELEASE/"电路板"
HISTORY = BOARD_DIR/"迁移前对照"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drill(text, precision=6):
    tools, current, holes = {}, None, []
    for line in text.splitlines():
        definition = re.fullmatch(r"T(\d+)C([\d.]+)", line)
        selection = re.fullmatch(r"T(\d+)", line)
        if definition:
            tools[int(definition[1])] = float(definition[2])
        elif selection:
            current = int(selection[1])
        elif line.startswith("X"):
            points = [tuple(round(float(v), precision) for v in p)
                      for p in re.findall(r"X(-?[\d.]+)Y(-?[\d.]+)", line)]
            assert current in tools and len(points) in (1, 2), line
            holes.append((round(tools[current], precision), tuple(sorted(points))))
    return Counter(holes)


def outline(text):
    assert "%FSLAX46Y46*%" in text and "%MOMM*%" in text
    lines, start = [], None
    for match in re.finditer(r"X(-?\d+)Y(-?\d+)D0([12])\*", text):
        end = (round(int(match[1])/1e6, 3), round(int(match[2])/1e6, 3))
        if match[3] == "1":
            assert start is not None
            lines.append(tuple(sorted((start, end))))
        start = end
    return Counter(lines)


def audit():
    exported = read(LOG/"原生文件内容导出.json")["value"]
    inspected = read(LOG/"最终原生几何与连接.json")["value"]
    assert exported["drc"] == inspected["drc"] == []
    assert exported["components"] == inspected["componentCount"] == 26
    assert len(inspected["pads"]) == 83 and len(inspected["vias"]) == 18
    assert set(exported["nets"]) == set(inspected["nets"]) and len(exported["nets"]) == 14
    baseline_dir = HISTORY if HISTORY.exists() else BOARD_DIR
    baseline_audit_path = RELEASE/"核对记录/迁移前对照/孔位与布线核对.json"
    if not baseline_audit_path.exists():
        baseline_audit_path = RELEASE/"核对记录/孔位与布线核对.json"
    baseline = read(baseline_audit_path)["实际孔位核对"]
    actual = {pad["PrimitiveId"]: pad for pad in inspected["pads"]}
    mapped, error = {}, 0
    for component in inspected["components"]:
        ref = component["Designator"]
        expected = list(baseline[ref])
        mapped[ref] = []
        for mapping in component["Pads"]:
            pad = actual[component["PrimitiveId"]+mapping["primitiveId"]]
            x, y = pad["X"]*.0254, -pad["Y"]*.0254
            candidates = [item for item in expected if item["焊盘号"] == pad["PadNumber"] and item["网络"] == pad["Net"]]
            assert candidates, (ref, pad["PadNumber"], pad["Net"])
            item = min(candidates, key=lambda item: abs(-item["装配坐标毫米"][0]-3-x)+abs(45-item["装配坐标毫米"][1]-y))
            expected.remove(item)
            difference = max(abs(-item["装配坐标毫米"][0]-3-x), abs(45-item["装配坐标毫米"][1]-y))
            assert difference < .002, (ref, item, pad, difference)
            error = max(error, difference)
            mapped[ref].append({**item, "嘉立创读回制板坐标毫米": [round(x, 6), round(y, 6)]})
        assert not expected, ref
    assert set(mapped) == set(baseline)
    with zipfile.ZipFile(OUTPUT/"嘉立创原始制板文件.zip") as archive:
        assert archive.testzip() is None
        contents = {name: archive.read(name) for name in archive.namelist()}
    stats, drill_error = {}, 0
    for kind, name in (("PTH", "Drill_PTH_Through.DRL"), ("NPTH", "Drill_NPTH_Through.DRL")):
        old = drill((baseline_dir/"制造文件"/f"gunmouse-final-{kind}.drl").read_text(encoding="utf-8"))
        new = drill(contents[name].decode())
        reference = (baseline_dir/"制造文件"/f"gunmouse-final-{kind}.drl").read_text(encoding="utf-8")
        assert drill(reference, 3) == drill(contents[name].decode(), 3), (kind, "制造钻孔不匹配")
        for (diameter, points), (new_diameter, new_points) in zip(sorted(old.elements()), sorted(new.elements())):
            drill_error = max(drill_error, abs(diameter-new_diameter),
                              *(abs(a-b) for p, q in zip(points, new_points) for a, b in zip(p, q)))
        assert drill_error < .00001, (kind, "制造钻孔误差", drill_error)
        stats[kind] = {"总孔数": sum(new.values()), "槽孔数": sum(n for (_, points), n in new.items() if len(points) == 2)}
    vias = drill(contents["Drill_PTH_Through_Via.DRL"].decode())
    assert sum(vias.values()) == 18 and not (vias-drill(contents["Drill_PTH_Through.DRL"].decode()))
    old_outline = (baseline_dir/"制造文件/gunmouse-final-Edge_Cuts.gm1").read_text(encoding="utf-8")
    assert outline(old_outline) == outline(contents["Gerber_BoardOutlineLayer.GKO"].decode())
    source = (NATIVE/"pcb/枪型飞鼠最终主板.epcb2").read_text(encoding="utf-8")
    rows = [(json.loads(h), json.loads(b.removesuffix("|")) if b.removesuffix("|") else None)
            for h, b in (line.split("||", 1) for line in source.splitlines())]
    head = [i for i, (h, b) in enumerate(rows) if h["type"] == "DOCHEAD" and b["docType"] == "PCB"][-1]
    stack = [(json.loads(h["id"])[1], b) for h, b in rows[head:] if h["type"] == "LAYER_PHYS"]
    thickness = sum(b["thickness"] for _, b in stack)*.0254
    assert len(stack) == 9 and abs(thickness-1.6) < .001
    copper = [b["thickness"]*.0254 for layer, b in stack if layer in (1, 2)]
    assert len(copper) == 2 and all(abs(value-.035) < .0001 for value in copper)
    return contents, {"软件": "嘉立创EDA专业版4.1.66", "原生工程": str(NATIVE/"枪型飞鼠最终版.eprj3"),
                      "工程标识": exported["project"]["uuid"], "主板标识": exported["pcb"],
                      "错误": 0, "未连接": 0, "警告": {}, "原生详细检查结果": [],
                      "元件数": 26, "焊盘及固定孔数": 83, "过孔数": 18, "网络数": 14,
                      "实际孔位核对": mapped, "孔位和网络核对数": 83,
                      "软件读回坐标最大轴向舍入误差毫米": round(error, 7),
                      "制造钻孔逐孔一致": True, "制造坐标比较分辨率毫米": .001,
                      "制造钻孔坐标最大差毫米": round(drill_error, 7), "钻孔核对": stats,
                      "板框中心线一致": True, "板外形毫米": [52, 82],
                      "铜层数": 2, "原生物理叠层总厚度毫米": round(thickness, 7),
                      "铜厚毫米": copper, "铺铜": "由嘉立创重新计算并通过原生严格规则检查",
                      "原生主板SHA256": digest(NATIVE/"pcb/枪型飞鼠最终主板.epcb2"),
                      "证据边界": "原生软件规则检查、孔位、网络和制造文件核对；未进行实物试装和通电。"}


def move_history(source, target):
    assert source.resolve().is_relative_to(RELEASE.resolve()) and target.resolve().is_relative_to(RELEASE.resolve())
    if source.exists() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)


def main():
    contents, report = audit()
    assert read(LOG/"关闭最终原生会话.json")["value"]["status"] == "closed"
    for name in ("gunmouse-final.kicad_pcb", "gunmouse-final.kicad_pro", "制造核对.json", "制造文件"):
        move_history(BOARD_DIR/name, HISTORY/name)
    for name in ("规则检查.json", "孔位与布线核对.json"):
        move_history(RELEASE/"核对记录"/name, RELEASE/"核对记录/迁移前对照"/name)
    destination = BOARD_DIR/"嘉立创原生工程"
    shutil.copytree(NATIVE, destination, dirs_exist_ok=True)
    shutil.copy2(OUTPUT/"枪型飞鼠_嘉立创原生工程.epro2", BOARD_DIR/"枪型飞鼠_嘉立创原生工程.epro2")
    shutil.copy2(OUTPUT/"嘉立创主板预览.png", BOARD_DIR/"嘉立创主板预览.png")
    fabrication = BOARD_DIR/"制造文件"
    fabrication.mkdir(exist_ok=True)
    selected = {name: data for name, data in contents.items() if name.endswith((".GTL", ".GBL", ".GTO", ".GBO", ".GTS", ".GBS", ".GKO", ".DRL")) and name != "Drill_PTH_Through_Via.DRL"}
    assert len(selected) == 9
    archive = RELEASE/"枪型飞鼠_最终版_上传打板.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in selected.items():
            (fabrication/name).write_bytes(data)
            z.writestr(name, data)
    report["打板压缩包SHA256"] = digest(archive)
    report["原生工程备份SHA256"] = digest(BOARD_DIR/"枪型飞鼠_嘉立创原生工程.epro2")
    report["制造文件SHA256"] = {name: digest(fabrication/name) for name in selected}
    for path in (BOARD_DIR/"制造核对.json", RELEASE/"核对记录/嘉立创原生核对.json", RELEASE/"核对记录/孔位与布线核对.json"):
        write(path, report)
    write(RELEASE/"核对记录/规则检查.json", {key: report[key] for key in ("软件", "工程标识", "主板标识", "错误", "未连接", "警告", "原生详细检查结果")})
    native_zip = RELEASE/"枪型飞鼠_嘉立创原生工程.zip"
    with zipfile.ZipFile(native_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                z.write(path, "嘉立创原生工程/"+path.relative_to(destination).as_posix())
    for path in (archive, native_zip, BOARD_DIR/"枪型飞鼠_嘉立创原生工程.epro2"):
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
    manifest = {path.relative_to(RELEASE).as_posix(): {"字节": path.stat().st_size, "SHA256": digest(path)}
                for path in sorted(RELEASE.rglob("*")) if path.is_file() and path.name != "交付文件核对.json"}
    write(RELEASE/"交付文件核对.json", manifest)
    complete = ROOT/"release/枪型飞鼠_最终版_完整文件.zip"
    with zipfile.ZipFile(complete, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(RELEASE.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(RELEASE).as_posix())
    with zipfile.ZipFile(complete) as z:
        assert z.testzip() is None and len(z.namelist()) == len(manifest)+1
    print(json.dumps({"原生工程": str(NATIVE/"枪型飞鼠最终版.eprj3"), "打板包": str(archive),
                      "原生工程包": str(native_zip), "孔位和网络": report["孔位和网络核对数"],
                      "钻孔": report["钻孔核对"], "错误": 0, "未连接": 0}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
