"""从工程样清单生成经济型审核候选，保留原铜层、坐标和固件。

输出是重新审核和询价材料；工厂尚未批准经济型，模块安装尚未实测。
"""

import csv
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deliverables" / "evt-a" / "制板文件"
OUT = ROOT / "deliverables" / "经济型审核候选"
OMIT = {
    "U1": "改接用户已有的同芯片 GY-601N1 模块，不手焊裸芯片",
    "R10": "模块已有数据线上拉，原板上拉留空",
    "R11": "模块已有时钟线上拉，原板上拉留空",
    "SW4": "同型号 SS-01GL13 自购、自行焊接",
    "J6": "小板只制光板，成品线裸端直接焊在开关公共端和常开端",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path):
    data = path.read_bytes()
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    return list(csv.DictReader(io.StringIO(data.decode(encoding)), delimiter="\t"))


def write_rows(path, rows, fields, quoting=csv.QUOTE_MINIMAL):
    with path.open("w", encoding="utf-16", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", quoting=quoting)
        writer.writeheader()
        writer.writerows(rows)


def main():
    bom_path = SOURCE / "gun-mouse-v1-BOM.csv"
    coord_path = SOURCE / "gun-mouse-v1-坐标文件.csv"
    gerber_path = SOURCE / "gun-mouse-v1-Gerber.zip"
    original_bom, original_coords = read_rows(bom_path), read_rows(coord_path)
    all_refs = {row["Designator"] for row in original_coords}
    assert set(OMIT) <= all_refs
    candidate_bom = []
    for row in original_bom:
        refs = [ref.strip() for ref in row["Designator"].split(",")]
        assert len(refs) == int(row["Quantity"]), row
        kept = [ref for ref in refs if ref not in OMIT]
        if not kept:
            continue
        updated = dict(row)
        updated.update({"No.": str(len(candidate_bom) + 1), "Quantity": str(len(kept)), "Designator": ",".join(kept)})
        candidate_bom.append(updated)
    candidate_coords = [row for row in original_coords if row["Designator"] not in OMIT]
    bom_refs = {ref for row in candidate_bom for ref in row["Designator"].split(",")}
    assert bom_refs == {row["Designator"] for row in candidate_coords} == all_refs - set(OMIT)
    assert len(candidate_bom) == 22 and len(candidate_coords) == 43
    assert all(row["Layer"] == "T" for row in candidate_coords)
    original_by_ref = {row["Designator"]: row for row in original_coords}
    assert all(row == original_by_ref[row["Designator"]] for row in candidate_coords)
    OUT.mkdir(parents=True, exist_ok=True)
    write_rows(OUT / "gun-mouse-economy-candidate-BOM.csv", candidate_bom, list(original_bom[0]))
    write_rows(OUT / "gun-mouse-economy-candidate-坐标文件.csv", candidate_coords, list(original_coords[0]), csv.QUOTE_ALL)
    (OUT / "gun-mouse-economy-candidate-Gerber.zip").write_bytes(gerber_path.read_bytes())
    report = {
        "状态": "经济型审核与报价候选，未获工厂批准，不能直接付款生产",
        "基线": "7725ea4 工程样 EVT-A",
        "未修改": ["原板铜层和板形", "保留器件的坐标、角度和料号", "固件", "原打印文件"],
        "原元件组": len(original_bom), "原每套元件数": len(original_coords),
        "工厂元件组": len(candidate_bom), "工厂每套元件数": len(candidate_coords),
        "不代焊": OMIT,
        "必须先处理": ["PCB 生产资料取消 V 割并重新审核", "确认经济型支持所有剩余代焊器件", "核对只贴主板时多款板费用", "模块刚性固定与轴向复核"],
        "源文件校验": {path.name: digest(path) for path in (bom_path, coord_path, gerber_path)},
        "生成文件校验": {path.name: digest(path) for path in sorted(OUT.glob("*.csv"))} | {"gun-mouse-economy-candidate-Gerber.zip": digest(OUT / "gun-mouse-economy-candidate-Gerber.zip")},
    }
    (OUT / "清单核对.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"组数": len(candidate_bom), "每套工厂安装数": len(candidate_coords), "原坐标保留": True, "原板生产文件保留": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
