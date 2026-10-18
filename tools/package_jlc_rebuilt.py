"""核对从空白原生重绘的最终主板，并按嘉立创原样导出文件打包。"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import zipfile

from package_jlc_final import drill, outline

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release/2026-10-18-最终版"
NATIVE = ROOT / "pcb/嘉立创最终复绘"
INPUT = NATIVE / "核对输入"
SOURCE = NATIVE / "枪型飞鼠最终原生复绘.eprj2"
EXPORT = INPUT / "嘉立创原始制板文件.zip"
BACKUP = INPUT / "枪型飞鼠_最终原生复绘.epro2"
BOARD = RELEASE / "电路板"
HISTORY = BOARD / "迁移前对照/旧整板迁移版"
STL_HASHES = {
    "主体底座.stl": "80bfdb21c74d12bf65a1252c561c1237276a3766eca3a60d7897dbf7b87a0276",
    "摇杆支座.stl": "04661e69b9298d6afe45294b14ee7854e4ca7da1fa3ba889b9e57490852c0170",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(source):
    # 铜区字符串可能包含Unicode换行符，不能使用splitlines()拆断JSON记录。
    for line in source.split("\n"):
        if not line:
            continue
        header, body = line.split("||", 1)
        body = body.removesuffix("|")
        yield json.loads(header), json.loads(body) if body else None


def compare_saved(a, b):
    """嘉立创落盘将坐标舍入为小数点后4位毫英寸；其余属性必须一致。"""
    if isinstance(a, bool) or isinstance(b, bool):
        assert a == b
        return 0
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        difference = abs(a - b)
        assert difference <= .0001, (a, b, difference)
        return difference
    if isinstance(a, dict) and isinstance(b, dict):
        assert a.keys() == b.keys()
        return max((compare_saved(a[k], b[k]) for k in a), default=0)
    if isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b)
        return max((compare_saved(x, y) for x, y in zip(a, b)), default=0)
    assert a == b, (a, b)
    return 0


def match_drills(expected, actual):
    """一一匹配，包含槽孔的两个端点；允许原生毫英寸坐标的数值舍入。"""
    pending = list(actual.elements())
    maximum = 0
    for diameter, points in expected.elements():
        choices = []
        for i, (other_diameter, other_points) in enumerate(pending):
            if len(points) != len(other_points):
                continue
            error = max(abs(diameter - other_diameter),
                        *(abs(a - b) for p, q in zip(points, other_points) for a, b in zip(p, q)))
            choices.append((error, i))
        error, index = min(choices)
        assert error < .002, ("制造钻孔不匹配", diameter, points, error)
        maximum = max(maximum, error)
        pending.pop(index)
    assert not pending, ("多出的制造钻孔", pending)
    return maximum


def audit():
    exported = read(INPUT / "嘉立创导出状态.json")
    reopened = read(INPUT / "嘉立创保存重开状态.json")
    assert exported["drc"] == reopened["drc"] == []
    assert exported["board"] == reopened["board"] == "61a266ba7448f6bd"
    assert len(reopened["pads"]) == 83 and len(reopened["lines"]) == 835 and len(reopened["vias"]) == 32
    saved_error = max(compare_saved({p["PrimitiveId"]: p for p in exported[kind]},
                                    {p["PrimitiveId"]: p for p in reopened[kind]})
                      for kind in ("pads", "lines", "vias")) * .0254
    assert not reopened["components"], "本板使用独立原生焊盘；不得误报为器件实例"
    baseline = read(RELEASE / "核对记录/迁移前对照/孔位与布线核对.json")["实际孔位核对"]
    pending = list(reopened["pads"])
    mapped, maximum = {}, 0
    for ref, items in baseline.items():
        mapped[ref] = []
        for item in items:
            number = ref + ("." + item["焊盘号"] if item["焊盘号"] else "")
            expected_x, expected_y = -item["装配坐标毫米"][0] - 3, 45 - item["装配坐标毫米"][1]
            choices = [(max(abs(p["X"] * .0254 - expected_x), abs(-p["Y"] * .0254 - expected_y)), i)
                       for i, p in enumerate(pending) if p["PadNumber"] == number and p["Net"] == item["网络"]]
            error, index = min(choices)
            assert error < .002, (ref, number, error)
            pad = pending.pop(index)
            assert pad["Metallization"] == bool(item["焊盘号"]), (ref, pad)
            maximum = max(maximum, error)
            mapped[ref].append({**item, "嘉立创读回制板坐标毫米": [pad["X"] * .0254, -pad["Y"] * .0254]})
    assert not pending
    contract = read(ROOT / "pcb/circuit-netlist.json")["nets"]
    actual_nets = {net: sorted(p["PadNumber"] for p in reopened["pads"] if p["Net"] == net)
                   for net in {p["Net"] for p in reopened["pads"] if p["Net"]}}
    assert actual_nets == {net: sorted(pins) for net, pins in contract.items()}
    assert len(actual_nets) == 14 and sum(map(len, actual_nets.values())) == 55
    assert sum(p["Metallization"] for p in reopened["pads"]) == 71
    with zipfile.ZipFile(EXPORT) as z:
        assert z.testzip() is None
        contents = {name: z.read(name) for name in z.namelist()}
    stats = {}
    drill_error = 0
    for kind, name in (("PTH", "Drill_PTH_Through.DRL"), ("NPTH", "Drill_NPTH_Through.DRL")):
        old = drill((BOARD / "迁移前对照/制造文件" / f"gunmouse-final-{kind}.drl").read_text())
        new = drill(contents[name].decode())
        # 本次重新布线的过孔数会改变；71个焊孔包含0.7毫米宽的槽孔。
        fixed_old = Counter({k: n for k, n in old.items() if kind == "NPTH" or k[0] > .5})
        fixed_new = Counter({k: n for k, n in new.items() if kind == "NPTH" or k[0] > .5})
        drill_error = max(drill_error, match_drills(fixed_old, fixed_new))
        stats[kind] = {"总孔数": sum(new.values()), "固定焊孔或机械孔数": sum(fixed_new.values()),
                       "槽孔数": sum(n for (_, points), n in new.items() if len(points) == 2)}
    assert stats["PTH"]["总孔数"] == 103 and stats["NPTH"]["总孔数"] == 12
    vias = drill(contents["Drill_PTH_Through_Via.DRL"].decode())
    assert sum(vias.values()) == 32 and not (vias - drill(contents["Drill_PTH_Through.DRL"].decode()))
    assert outline((BOARD / "迁移前对照/制造文件/gunmouse-final-Edge_Cuts.gm1").read_text()) == outline(contents["Gerber_BoardOutlineLayer.GKO"].decode())
    rows = list(records(reopened["source"]))
    stack = [(json.loads(h["id"])[1], body) for h, body in rows if h["type"] == "LAYER_PHYS"]
    thickness = sum(body["thickness"] for _, body in stack) * .0254
    copper = [body["thickness"] * .0254 for layer, body in stack if layer in (1, 2)]
    assert len(stack) == 9 and abs(thickness - 1.6) < .001
    assert len(copper) == 2 and all(abs(value - .035) < .0001 for value in copper)
    assert Counter(h["type"] for h, _ in rows)["POURED"] == 2
    assert all(contents[name].count(b"G36*") > 0 for name in ("Gerber_TopLayer.GTL", "Gerber_BottomLayer.GBL"))
    with zipfile.ZipFile(BACKUP) as z:
        assert z.testzip() is None
        native = z.read(next(name for name in z.namelist() if name.endswith(".epru"))).decode("utf-8")
        active, backup_rows = False, []
        for h, body in records(native):
            if h["type"] == "DOCHEAD":
                active = body.get("uuid") == reopened["board"] and body.get("docType") == "PCB"
            if active:
                backup_rows.append((h, body))
        counts = Counter(h["type"] for h, _ in backup_rows)
        assert counts["PAD"] == 83 and counts["LINE"] == 835 and counts["VIA"] == 32
        assert counts["POUR"] == 2 and counts["COMPONENT"] == 0
        # 官方工程备份保留已删除铺铜对象的缓存，只比较仍有父铺铜区的两份有效缓存。
        active_pours = {h["id"] for h, _ in backup_rows if h["type"] == "POUR"}
        backup_rows = [(h, b) for h, b in backup_rows
                       if h["type"] != "POURED" or json.loads(h["id"])[1] in active_pours]
        assert sum(h["type"] == "POURED" for h, _ in backup_rows) == 2
        for kind in ("PAD", "LINE", "VIA", "POUR", "POURED"):
            compare_saved({h["id"]: b for h, b in rows if h["type"] == kind},
                          {h["id"]: b for h, b in backup_rows if h["type"] == kind})
    with sqlite3.connect(SOURCE.as_uri() + "?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert read(INPUT / "嘉立创核验会话关闭.json")["status"] == "closed"
    for name, expected in STL_HASHES.items():
        assert digest(RELEASE / "三维打印" / name) == expected, name
    return contents, {
        "软件": "嘉立创EDA专业版4.1.66", "原生工程": str(SOURCE),
        "工程标识": reopened["project"]["uuid"], "主板标识": reopened["board"],
        "绘制方法": "从空白PCB新建83个原生焊盘/孔，按最终版机械及电气约定独立重新布线；未导入原整板、旧走线或旧覆铜",
        "设计维护方式": "独立原生焊盘和网络板图；没有关联器件实例及配套原理图。后续改动需按焊盘和网络维护。",
        "错误": 0, "未连接": 0, "警告": {}, "原生详细检查结果": [], "保存重开检查通过": True,
        "保存重开属性最大数值舍入毫米": saved_error,
        "焊盘及固定孔数": 83, "金属化焊盘数": 71, "非金属孔数": 12, "网络数": 14,
        "连接引脚数": 55, "走线段数": 835, "过孔数": 32, "实际孔位核对": mapped,
        "孔位和网络核对数": 83, "软件读回坐标最大轴向舍入误差毫米": round(maximum, 8),
        "制造焊孔及固定孔逐孔匹配": True, "制造钻孔坐标或孔径最大差毫米": round(drill_error, 8),
        "制造比对允许数值舍入毫米": .002, "钻孔核对": stats,
        "板框中心线一致": True, "板外形毫米": [52, 82], "铜层数": 2,
        "原生物理叠层总厚度毫米": thickness, "铜厚毫米": copper,
        "原生工程SHA256": digest(SOURCE), "原生工程备份SHA256": digest(BACKUP),
        "打板压缩包SHA256": digest(EXPORT), "打板压缩包保持嘉立创导出原始字节": True,
        "打印件SHA256": STL_HASHES, "优惠券平台验证": "未验证；按用户要求由用户自行到平台确认",
        "证据边界": "原生设计规则、保存重开、网络合同、机械孔位及制造文件核对；未进行实物试装或通电。",
    }


def archive_old(source, relative):
    target = HISTORY / relative
    assert source.resolve().is_relative_to(RELEASE.resolve()) and target.resolve().is_relative_to(RELEASE.resolve())
    if source.exists() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)


def main():
    contents, report = audit()  # 所有核对通过之后才修改交付目录。
    for source, relative in (
        (BOARD / "嘉立创原生工程", "嘉立创原生工程"),
        (BOARD / "枪型飞鼠_嘉立创原生工程.epro2", "枪型飞鼠_嘉立创原生工程.epro2"),
        (BOARD / "制造文件", "制造文件"),
        (BOARD / "嘉立创主板预览.png", "嘉立创主板预览.png"),
        (RELEASE / "枪型飞鼠_嘉立创原生工程.zip", "枪型飞鼠_嘉立创原生工程.zip"),
        (RELEASE / "枪型飞鼠_最终版_上传打板.zip", "枪型飞鼠_最终版_上传打板.zip"),
    ):
        archive_old(source, relative)
    destination = BOARD / "嘉立创原生重绘"
    destination.mkdir(exist_ok=True)
    shutil.copy2(SOURCE, destination / SOURCE.name)
    shutil.copy2(BACKUP, destination / BACKUP.name)
    shutil.copy2(INPUT / "嘉立创主板预览.png", BOARD / "嘉立创主板预览.png")
    shutil.copy2(NATIVE / "实现完成说明.md", destination / "实现完成说明.md")
    usage = ("当前工程：枪型飞鼠最终原生复绘.eprj2\n"
             "官方工程备份：枪型飞鼠_最终原生复绘.epro2\n"
             "在嘉立创专业版打开后选择“枪型飞鼠最终主板”；PCB1和原理图是软件新建工程的空白占位。\n"
             "本次为原生焊盘及网络板图重绘，没有关联器件实例及配套原理图。\n"
             "优惠券是否可用，由用户自行到平台确认，本交付未核验平台结果。\n")
    (destination / "打开说明.txt").write_text(usage, encoding="utf-8")
    fabrication = BOARD / "制造文件"
    fabrication.mkdir(exist_ok=True)
    for name, data in contents.items():
        assert Path(name).name == name
        (fabrication / name).write_bytes(data)
    upload = RELEASE / "枪型飞鼠_最终版_上传打板.zip"
    shutil.copy2(EXPORT, upload)  # 保留官方原包，包含重复过孔表和官方说明，不自行重打包。
    assert digest(upload) == digest(EXPORT)
    report["制造文件SHA256"] = {name: digest(fabrication / name) for name in contents}
    for path in (BOARD / "制造核对.json", RELEASE / "核对记录/嘉立创原生核对.json", RELEASE / "核对记录/孔位与布线核对.json"):
        write(path, report)
    write(RELEASE / "核对记录/规则检查.json", {k: report[k] for k in ("软件", "工程标识", "主板标识", "错误", "未连接", "原生详细检查结果", "保存重开检查通过")})
    for name in ("嘉立创保存重开状态.json", "嘉立创核验会话关闭.json"):
        shutil.copy2(INPUT / name, RELEASE / "核对记录" / name)
    native_zip = RELEASE / "枪型飞鼠_嘉立创原生工程.zip"
    with zipfile.ZipFile(native_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(destination.iterdir()):
            z.write(path, "嘉立创原生重绘/" + path.name)
    manifest = {path.relative_to(RELEASE).as_posix(): {"字节": path.stat().st_size, "SHA256": digest(path)}
                for path in sorted(RELEASE.rglob("*")) if path.is_file() and path.name != "交付文件核对.json"}
    write(RELEASE / "交付文件核对.json", manifest)
    complete = ROOT / "release/枪型飞鼠_最终版_完整文件.zip"
    with zipfile.ZipFile(complete, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(RELEASE.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(RELEASE).as_posix())
    for path in (upload, native_zip, complete):
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
    with zipfile.ZipFile(complete) as z:
        assert len(z.namelist()) == len(manifest) + 1
        assert hashlib.sha256(z.read(upload.name)).hexdigest() == digest(EXPORT)
    print(json.dumps({"打板包": str(upload), "工程": str(SOURCE), "错误": 0, "未连接": 0,
                      "孔位最大数值差毫米": report["制造钻孔坐标或孔径最大差毫米"], "制造钻孔": report["钻孔核对"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
