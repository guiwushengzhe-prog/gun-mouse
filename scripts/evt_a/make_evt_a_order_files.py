r"""由正式制板文件生成 EVT-A 下单文件：只按 config/evt-a.json 改 R3、R5 的阻值与料号。

Gerber 原样复制（走线、器件位置、封装不变）；物料表与坐标文件保持原 UTF-16 制表符格式。
正式配置 config/pcb-shell-v1.json 与 EDA 工程仍是改值前的基线，改板时再合并本差异。
运行：python scripts\evt_a\make_evt_a_order_files.py
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "deliverables" / "pcb-shell-v1" / "制板文件"
DST = ROOT / "deliverables" / "evt-a" / "制板文件"
BOM = "gun-mouse-v1-BOM.csv"
CPL = "gun-mouse-v1-坐标文件.csv"
GERBER = "gun-mouse-v1-Gerber.zip"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def newline_of(path):
    return "\r\n" if "\r\n" in path.read_bytes().decode("utf-16") else "\n"


def read_rows(path):
    text = path.read_bytes().decode("utf-16")
    return [line.split("\t") for line in text.splitlines()]


def write_rows(path, rows, newline):
    """保持原文件的换行风格（物料表为 LF，坐标文件为 CRLF）。"""
    path.write_bytes((newline.join("\t".join(r) for r in rows) + newline).encode("utf-16"))


def main():
    changes = json.loads((ROOT / "config" / "evt-a.json").read_text(encoding="utf-8"))["bom_changes"]
    DST.mkdir(parents=True, exist_ok=True)

    rows = read_rows(SRC / BOM)
    head, body = rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
    col = {name: i for i, name in enumerate(head)}
    for ref, ch in changes.items():
        for r in body:
            refs = [x for x in r[col["Designator"]].split(",") if x]
            if ref in refs:
                refs.remove(ref)
                r[col["Designator"]] = ",".join(refs)
                r[col["Quantity"]] = str(len(refs))
        target = next((r for r in body if r[col["Supplier Part"]] == ch["lcsc"]), None)
        if target:
            refs = [x for x in target[col["Designator"]].split(",") if x] + [ref]
            refs.sort(key=lambda s: (s.rstrip("0123456789"), int(s[len(s.rstrip("0123456789")):] or 0)))
            target[col["Designator"]] = ",".join(refs)
            target[col["Quantity"]] = str(len(refs))
        else:
            template = next(r for r in body if r[col["Footprint"]] == "R0402")
            new = list(template)
            new[col["No."]] = str(max(int(r[col["No."]]) for r in body) + 1)
            new[col["Quantity"]] = "1"
            new[col["Comment"]] = new[col["Value"]] = ch["to_value"]
            new[col["Designator"]] = ref
            new[col["Manufacturer Part"]] = ch["mpn"]
            new[col["Supplier Part"]] = ch["lcsc"]
            body.append(new)
    body = [r for r in body if r[col["Quantity"]] != "0"]
    write_rows(DST / BOM, [head] + body, newline_of(SRC / BOM))

    rows = read_rows(SRC / CPL)
    head, body = rows[0], rows[1:]
    col = {name: i for i, name in enumerate(head)}
    sample = {r[col["Device"]].strip('"'): r for r in body}
    for r in body:
        ref = r[col["Designator"]].strip('"')
        if ref in changes:
            ch = changes[ref]
            r[col["Device"]] = f'"{ch["mpn"]}"'
            r[col["Comment"]] = r[col["Value"]] = f'"{ch["to_value"]}"'
            same = sample.get(ch["mpn"])
            r[col["Datasheet"]] = same[col["Datasheet"]] if same else f'"https://www.lcsc.com/product-detail/{ch["lcsc"]}.html"'
    write_rows(DST / CPL, [head] + body, newline_of(SRC / CPL))

    (DST / GERBER).write_bytes((SRC / GERBER).read_bytes())
    report = {
        "scope": "EVT-A 下单文件：仅 R3、R5 阻值与料号变化",
        "gerber_identical_to_formal": sha(DST / GERBER) == sha(SRC / GERBER),
        "gerber_sha256": sha(DST / GERBER),
        "bom_sha256": sha(DST / BOM), "cpl_sha256": sha(DST / CPL),
        "formal_sources": {f: sha(SRC / f) for f in (BOM, CPL, GERBER)},
        "changes": changes,
    }
    if not report["gerber_identical_to_formal"]:
        raise ValueError("Gerber 不应改变")
    (DST / "下单文件差异.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
