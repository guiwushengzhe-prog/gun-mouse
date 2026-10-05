"""与原成果提交比较：配置不变，电路板只允许通道关联和软件保存元数据变化。"""

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import subprocess

from audit_netlist import read_documents

ROOT = Path(__file__).resolve().parents[2]


def baseline_bytes(revision, relative):
    return subprocess.run(["git", "show", f"{revision}:{relative}"], cwd=ROOT,
                          check=True, stdout=subprocess.PIPE).stdout


def canonical_records(documents):
    records = {}
    for header, items in documents:
        for head, body, _ in items:
            head = {k: v for k, v in head.items() if k != "ticket"}
            body = copy.deepcopy(body)
            # 通道编号只承担原理图关联，不改变封装、位置、焊盘或走线。
            if head["type"] == "COMPONENT":
                body.get("attrs", {}).pop("Channel ID", None)
            if head["type"] == "ATTR" and body.get("key") == "Channel ID":
                continue
            records[(header["uuid"], head["type"], head.get("id"))] = (head, body)
    return records


def verify(revision):
    configuration = {}
    for name in ("pcb-shell-v1.json", "pcb-parts-geometry.json"):
        relative = f"config/{name}"
        old, new = baseline_bytes(revision, relative), (ROOT / relative).read_bytes()
        configuration[name] = {"unchanged": old == new, "sha256": hashlib.sha256(new).hexdigest()}
    relative = "pcb/gun-mouse-v1/pcb/PCB1.epcb2"
    snapshot = ROOT / ".logs" / "pcb-baseline.epcb2"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(baseline_bytes(revision, relative))
    old = canonical_records(read_documents(snapshot))
    new = canonical_records(read_documents(ROOT / relative))
    differences = [{"document": key[0], "type": key[1], "id": key[2],
                    "before": old.get(key), "after": new.get(key)}
                   for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]
    return {"baseline_commit": revision, "configuration": configuration,
            "pcb_record_counts": dict(Counter(key[1] for key in new)),
            "pcb_unexpected_differences": differences,
            "passed": not differences and all(c["unchanged"] for c in configuration.values()),
            "scope": "忽略记录保存序号、文档保存头和通道编号关联属性；其余库、封装、器件、属性、焊盘网络、走线、孔与板框逐记录一致。"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="dff2043")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/pcb-shell-v1/design-baseline-report.json")
    args = parser.parse_args()
    result = verify(args.baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "differences": len(result["pcb_unexpected_differences"]),
                      "counts": result["pcb_record_counts"], "report": str(args.output)}, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)
