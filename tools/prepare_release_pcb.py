"""从当前装配预览板复制交付源，核对孔位并导出可上传的制造压缩包。

使用现有 KiCad 9 的 Python 执行；不改预览板、正式板或旧交付。
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

import pcbnew as pcb

from preview_layout import BODY_MOUNT_HOLE, IMU_MOUNT_HOLES, IMU_TRANSLATION_Z, POWER_CENTER_XZ
from preview_local_joystick_mount import LOCAL_HOLES

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shell/快速结构预览/pcb/preview-local-mount.kicad_pcb"
OUT = ROOT / "release/2026-10-18/电路板"
NAME = "gunmouse-v2-20261018"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mm(vector):
    return [round(pcb.ToMM(vector.x), 6), round(pcb.ToMM(vector.y), 6)]


def xy(point):
    return [round(-point[0]-3, 6), round(45-point[1], 6)]


def run(*arguments):
    subprocess.run(["kicad-cli", *map(str, arguments)], check=True)


def board_audit(board):
    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    assert board.GetCopperLayerCount() == 2
    assert abs(pcb.ToMM(board.GetDesignSettings().GetBoardThickness())-1.6) < 1e-6
    actual = {}
    holes = [(f"H_JOY_LOCAL_{i}", point, [2.4, 2.4]) for i, point in enumerate(LOCAL_HOLES, 1)]
    holes += [(f"H_IMU_{i}", point, [2.4, 3.6]) for i, point in enumerate(IMU_MOUNT_HOLES, 1)]
    holes += [("H_BODY_5", BODY_MOUNT_HOLE, [2.4, 2.4])]
    config = json.loads((ROOT / "pcb/carrier-config.json").read_text(encoding="utf-8"))
    holes += [(hole["id"], hole["xz"], [hole["d"], hole["d"]]) for hole in config["pcb"]["mount_holes"]]
    for reference, point, size in holes:
        fp = footprints[reference]
        pads = list(fp.Pads())
        assert len(pads) == 1, reference
        pad = pads[0]
        assert mm(pad.GetPosition()) == xy(point), (reference, mm(pad.GetPosition()), xy(point))
        assert mm(pad.GetDrillSize()) == size, (reference, mm(pad.GetDrillSize()), size)
        assert pad.GetAttribute() == pcb.PAD_ATTRIB_NPTH, reference
        actual[reference] = {"主板坐标毫米": mm(pad.GetPosition()), "装配坐标毫米": list(point), "孔径毫米": size}
    for part in config["parts"]:
        for hole in part.get("npth", []):
            matches = [pad for pad in footprints[part["ref"]].Pads() if mm(pad.GetPosition()) == xy(hole["xz"])]
            assert len(matches) == 1 and mm(matches[0].GetDrillSize()) == hole["drill"], hole
            assert matches[0].GetAttribute() == pcb.PAD_ATTRIB_NPTH, hole
            actual[hole["id"]] = {"主板坐标毫米": mm(matches[0].GetPosition()), "装配坐标毫米": hole["xz"], "孔径毫米": hole["drill"]}
    assert mm(footprints["J_SWITCH"].GetPosition()) == xy(POWER_CENTER_XZ)
    baseline = pcb.LoadBoard(str(ROOT / "pcb/gun-mouse-supermini-carrier.kicad_pcb"))
    old_imu = next(fp for fp in baseline.GetFootprints() if fp.GetReference() == "J_GY")
    old_xy = mm(old_imu.GetPosition())
    assert mm(footprints["J_GY"].GetPosition()) == [old_xy[0], round(old_xy[1]-IMU_TRANSLATION_Z, 6)]
    expected_edges = {tuple(sorted((tuple(xy(a)), tuple(xy(b))))) for a, b in zip(config["pcb"]["outline_xz"], config["pcb"]["outline_xz"][1:]+config["pcb"]["outline_xz"][:1])}
    edges = [drawing for drawing in board.GetDrawings() if drawing.GetLayer() == pcb.Edge_Cuts]
    assert len(edges) == 6
    assert {tuple(sorted((tuple(mm(edge.GetStart())), tuple(mm(edge.GetEnd()))))) for edge in edges} == expected_edges
    pads = [pad for fp in board.GetFootprints() for pad in fp.Pads()]
    holes_by_type = {"PTH": [], "NPTH": []}
    for pad in pads:
        size = mm(pad.GetDrillSize())
        if not min(size):
            continue
        plated = pad.GetAttribute() != pcb.PAD_ATTRIB_NPTH
        holes_by_type["PTH" if plated else "NPTH"].append({"中心毫米": mm(pad.GetPosition()), "孔径毫米": size})
    for track in board.GetTracks():
        if isinstance(track, pcb.PCB_VIA):
            diameter = round(pcb.ToMM(track.GetDrill()), 6)
            holes_by_type["PTH"].append({"中心毫米": mm(track.GetPosition()), "孔径毫米": [diameter, diameter]})
    return {"铜层数": 2, "板厚毫米": 1.6, "外形毫米": [52, 82], "板框闭合线段": 6,
            "当前装配共用孔位": actual, "电源开关中心毫米": mm(footprints["J_SWITCH"].GetPosition()),
            "惯性模块中心毫米": mm(footprints["J_GY"].GetPosition()), "钻孔表": holes_by_type}


def audit_drill(path, expected):
    """核对输出钻孔的实际中心、孔径及G85槽长，不只核对文件存在。"""
    text = path.read_text(encoding="utf-8")
    assert "METRIC" in text and "M30" in text
    tools = {int(number): float(diameter) for number, diameter in re.findall(r"^T(\d+)C([\d.]+)", text, re.M)}
    current = None
    actual = []
    for line in text.splitlines():
        match = re.fullmatch(r"T(\d+)", line)
        if match:
            current = int(match[1])
            continue
        match = re.fullmatch(r"X(-?[\d.]+)Y(-?[\d.]+)(?:G85X(-?[\d.]+)Y(-?[\d.]+))?", line)
        if not match:
            continue
        values = [float(value) if value is not None else None for value in match.groups()]
        x, y, endx, endy = values
        diameter = tools[current]
        if endx is None:
            actual.append({"中心毫米": [x, -y], "孔径毫米": [diameter, diameter]})
        else:
            actual.append({"中心毫米": [(x+endx)/2, -(y+endy)/2],
                           "孔径毫米": [diameter+abs(endx-x), diameter+abs(endy-y)]})
    normalize = lambda row: tuple(round(value, 3) for field in ("中心毫米", "孔径毫米") for value in row[field])
    assert Counter(map(normalize, actual)) == Counter(map(normalize, expected)), (path, actual, expected)
    return {"总孔数": len(actual), "槽孔数": sum(row["孔径毫米"][0] != row["孔径毫米"][1] for row in actual)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    board_path = OUT / f"{NAME}.kicad_pcb"
    project_path = board_path.with_suffix(".kicad_pro")
    before = digest(SOURCE)
    shutil.copy2(SOURCE, board_path)
    shutil.copy2(SOURCE.with_suffix(".kicad_pro"), project_path)
    assert digest(board_path) == before
    inspection = board_audit(pcb.LoadBoard(str(board_path)))
    report_path = OUT / "规则检查.json"
    run("pcb", "drc", "--format", "json", "--severity-all", "--output", report_path, board_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    errors = [row for row in report.get("violations", []) if row.get("severity") == "error"]
    assert not errors and not report.get("unconnected_items", []), (errors, report.get("unconnected_items"))
    inspection["规则检查"] = {"错误": len(errors), "未连接": len(report.get("unconnected_items", [])),
                          "警告": dict(Counter(row.get("type", "unknown") for row in report.get("violations", []) if row.get("severity") != "error"))}
    inspection["规则检查"]["封装库提示说明"] = "交付源内含完整封装；本机未注册外部GunMouseHandSolder库，提示不影响铜层、阻焊、丝印或钻孔导出。"
    gerber = OUT / "制造文件"
    gerber.mkdir(exist_ok=True)
    run("pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts",
        "--subtract-soldermask", "--output", gerber, board_path)
    run("pcb", "export", "drill", "--format", "excellon", "--drill-origin", "absolute",
        "--excellon-zeros-format", "decimal", "--excellon-oval-format", "alternate",
        "--excellon-units", "mm", "--excellon-separate-th", "--output", gerber, board_path)
    outputs = sorted(gerber.iterdir())
    expected_extensions = {".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gm1", ".gbrjob", ".drl"}
    assert {path.suffix for path in outputs} == expected_extensions
    assert len(outputs) == 10
    for path in outputs:
        if path.suffix not in {".drl", ".gbrjob"}:
            content = path.read_text(encoding="utf-8")
            assert "%FSLAX46Y46*%" in content and "%MOMM*%" in content and "M02*" in content, path
    for kind, expected in inspection.pop("钻孔表").items():
        inspection[f"{kind}导出核对"] = audit_drill(gerber / f"{NAME}-{kind}.drl", expected)
    job = json.loads((gerber / f"{NAME}-job.gbrjob").read_text(encoding="utf-8"))
    assert job["GeneralSpecs"]["LayerNumber"] == 2 and job["GeneralSpecs"]["BoardThickness"] == 1.6
    copper = [layer["Thickness"] for layer in job["MaterialStackup"] if layer["Type"] == "Copper"]
    assert copper == [.035, .035], copper
    inspection["铜厚微米"] = [35, 35]
    inspection["制造说明"] = "双层FR4裸板，1.6毫米板厚、双面1盎司铜；不含钢网或工厂贴片文件。表面处理在下单页面选择，文件不替代实物插装及通电验证。"
    archive = OUT / "枪型飞鼠_新版电路板_上传打板.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as target:
        for path in outputs:
            target.write(path, path.name)
    with zipfile.ZipFile(archive) as target:
        assert target.testzip() is None and len(target.namelist()) == 10
    assert digest(SOURCE) == before == digest(board_path)
    inspection.update({"源版本": args.revision, "KiCad版本": subprocess.check_output(["kicad-cli", "version"], text=True).strip(),
                       "源预览板SHA256": before, "制造压缩包SHA256": digest(archive),
                       "制造压缩包文件数": len(outputs), "源文件与交付源逐字节一致": True,
                       "制造文件SHA256": {path.name: digest(path) for path in outputs}})
    (OUT / "交付核对.json").write_text(json.dumps(inspection, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(inspection, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
