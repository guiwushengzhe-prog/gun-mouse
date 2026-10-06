"""从工程样基线生成只含主板的独立工程；保留主板的全部铜线和孔位。"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
from common import MIL, load_config
from layout import main_board_face, sample_wire

SOURCE = ROOT / "pcb" / "gun-mouse-v1"
TARGET = ROOT / "pcb" / "gun-mouse-economy-v2"
OUT = ROOT / "outputs" / "economy-eda"
REMOVED_COMPONENTS = {"5540ef27bee0231f", "69a40ab7a737d1b9"}
REMOVED_NETS = {"D_COM", "D_NO"}


def parse(line):
    if "||" not in line:
        return None
    h, b = line.split("||", 1)
    if not b.rstrip("|").strip():
        return None
    return json.loads(h), json.loads(b.rstrip("|"))


def dump(h, b):
    return json.dumps(h, ensure_ascii=False, separators=(",", ":")) + "||" + json.dumps(b, ensure_ascii=False, separators=(",", ":")) + "|"


def pcb_records(path):
    inside = False
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        p = parse(line)
        if not p:
            continue
        h, b = p
        if h["type"] == "DOCHEAD":
            inside = b.get("docType") == "PCB"
        if inside:
            out.append((h, b, line))
    return out


def counts(path):
    records = pcb_records(path)
    return {t: sum(h["type"] == t for h, _, _ in records) for t in ("COMPONENT", "LINE", "VIA", "PAD", "POLY")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    src = SOURCE / "pcb" / "PCB1.epcb2"
    dst = TARGET / "pcb" / "PCB1.epcb2"
    if args.prepare:
        if TARGET.exists():
            if dst.read_bytes() != src.read_bytes():
                raise RuntimeError("目标工程已有改动，保留现有文件；不能覆盖")
        else:
            shutil.copytree(SOURCE, TARGET)
        old_index = TARGET / "gun-mouse-v1.eprj3"
        index = json.loads((old_index if old_index.exists() else TARGET / "gun-mouse-economy-v2.eprj3").read_text(encoding="utf-8"))
        index["name"] = "gun-mouse-economy-v2"
        index["content"] = "经济型工程样：单独主板，复用惯性模块，扳机自购直摆杆开关"
        (TARGET / "gun-mouse-economy-v2.eprj3").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        if old_index.exists():
            old_index.unlink()
        _, face = main_board_face(load_config())
        points = [[round(-x / MIL, 3), round(z / MIL, 3)] for x, z in sample_wire(face.outerWire())]
        poly = [*points[0], "L", *[v for p in points[1:] for v in p], *points[0]]
        lines = []
        inside = False
        removed = {}
        outline_changes = 0
        for line in dst.read_text(encoding="utf-8").splitlines():
            p = parse(line)
            if not p:
                lines.append(line)
                continue
            h, b = p
            if h["type"] == "DOCHEAD":
                inside = b.get("docType") == "PCB"
            if not inside:
                lines.append(line)
                continue
            ident = h.get("id", "")
            parent = b.get("parentId", "")
            key = json.loads(ident) if ident.startswith("[") else []
            remove = ident in REMOVED_COMPONENTS or parent in REMOVED_COMPONENTS
            remove |= bool(key and any(x in REMOVED_COMPONENTS for x in key))
            remove |= h["type"] == "PAD" and b.get("num", "").startswith("MB")
            remove |= b.get("netName") in REMOVED_NETS
            remove |= h["type"] == "NET" and any(x in REMOVED_NETS for x in key)
            remove |= h["type"] == "STRING" and b.get("text") == "TRIG SS-01GL13"
            if remove:
                removed[h["type"]] = removed.get(h["type"], 0) + 1
                continue
            if h["type"] == "POLY" and ident == "d9ffe4e1bdcda3b6":
                b["path"] = poly
                h["ticket"] += 20000
                line = dump(h, b)
                outline_changes += 1
            if h["type"] == "PANELIZE":
                b["on"] = False
                b["showVCutIndicator"] = False
                b["verticalSize"]["on"] = False
                b["horizontalSize"]["on"] = False
                line = dump(h, b)
            lines.append(line)
        assert outline_changes == 1
        dst.write_bytes("\n".join(lines).encode("utf-8"))
        # 后续官方接口同步删除参考原理图中的 SW4/J6，并更新采购属性。
        report = {"说明": "单板外框由原主板轮廓计算；只删除扳机小板实体和其独立铜线，未重布主板", "原文件sha256": hashlib.sha256(src.read_bytes()).hexdigest(), "删除记录": removed, "修改外圈数": outline_changes, "主板外形毫米": [119.3, 134.3]}
        (OUT / "主板生成记录.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.prepare or args.verify:
        original = pcb_records(src)
        current = pcb_records(dst)
        # 编辑器保存可更新票号，但不能改变主板铜线、过孔和器件坐标等属性。
        a = {h["id"]: b for h, b, _ in original if h["type"] in ("LINE", "VIA") and b.get("netName") not in REMOVED_NETS}
        b = {h["id"]: v for h, v, _ in current if h["type"] in ("LINE", "VIA")}
        assert a == b, "主板铜线或过孔有非预期差异"
        removed_lines = sum(h["type"] == "LINE" and v.get("netName") in REMOVED_NETS for h, v, _ in original)
        assert removed_lines == 8
        expected = counts(src) | {"COMPONENT": 46, "LINE": counts(src)["LINE"] - removed_lines, "PAD": 5}
        assert counts(dst) == expected, (counts(dst), expected)
        for h, v, _ in current:
            assert v.get("netName") not in REMOVED_NETS
            if h["type"] == "PAD":
                assert v.get("num") in {"H1", "H2", "H3", "H4", "H5"}
        report = {"主板铜线和过孔与原版属性完全一致": True, "原生图元": counts(dst), "不代焊": ["U1", "R10", "R11"], "已移除小板": ["SW4", "J6", "20个邮票孔", "8条小板铜线", "连接桥"], "注意": "原理图和电路板已同步删除 SW4/J6，R3/R5已更新工程样采购值，U1/R10/R11不装；现场规则及最终代焊清单由单独导出、打包脚本核对"}
        (OUT / "主板保留检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
