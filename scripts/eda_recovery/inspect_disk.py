"""只读统计独立试验板磁盘记录，不把运行中的预览当作已经保存。"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def snapshot(path):
    data = path.read_bytes()
    records = []
    for line in data.decode("utf-8-sig").splitlines():
        if "||" not in line:
            continue
        left, right = line.split("||", 1)
        records.append((json.loads(left), json.loads(right.rstrip("|"))))
    counts = Counter(meta["type"] for meta, _ in records)
    pads = [body for meta, body in records if meta["type"] == "PAD"]
    lines = [{"id": meta.get("id"), **body} for meta, body in records
             if meta["type"] in ("LINE", "TRACK") and body.get("layerId") in (1, 2)]
    pours = [{"id": meta.get("id"), **body} for meta, body in records if meta["type"] == "POUR"]
    filled = [{"id": meta.get("id"), **body} for meta, body in records if meta["type"] == "POURED"]
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(),
            "counts": dict(counts), "padCount": len(pads), "copperLines": lines,
            "pours": pours, "filled": filled,
            "fillPathCount": sum(len(f.get("pourFill", [])) for f in filled),
            "note": "仅统计磁盘记录；真实电气连接另由软件检查和铜层文件核对"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.board.parent.parent.name not in (
            "eda-recovery-probe", "eda-recovery-probe-headless", "eda-recovery-probe-direct"):
        parser.error("仅允许读取独立试验板目录")
    result = snapshot(args.board)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "copperLines": len(result["copperLines"]),
                      "pours": len(result["pours"]), "filledRecords": len(result["filled"]),
                      "fillPaths": result["fillPathCount"],
                      "sha256": result["sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
