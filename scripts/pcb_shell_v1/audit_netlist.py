"""离线、只读核对配置、导出网表、PCB 焊盘和原理图实际引线。

运行：python scripts/pcb_shell_v1/audit_netlist.py
结果为标准输出上的 JSON；退出码 1 表示发现差异。不会打开嘉立创或改工程。
原理图核对使用本工程内嵌符号引脚与导线几何，不替代编辑器网表导出和规则检查。
"""

import argparse
from collections import Counter
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_documents(path):
    """读取嘉立创的内嵌库及末尾文档，保留记录行号和同编号最后状态。"""
    documents = []
    records = {}
    header = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("{") or "||" not in line:
            continue
        head, body = line.split("||", 1)
        head = json.loads(head)
        if head["type"] == "DOCHEAD":
            if header:
                documents.append((header, list(records.values())))
            header = json.loads(body.rstrip("|"))
            records = {}
            continue
        key = (head["type"], head.get("id"))
        body = body.rstrip("|")
        if body:
            records[key] = (head, json.loads(body), line_number)
        else:
            records.pop(key, None)
    if header:
        documents.append((header, list(records.values())))
    return documents


def attributes(records):
    result = {}
    for head, body, _ in records:
        if head["type"] == "ATTR":
            result.setdefault(body.get("parentId"), {})[body.get("key")] = body.get("value")
    return result


def compare_pins(expected, actual):
    differences = []
    for ref in sorted(expected.keys() | actual.keys()):
        wanted, found = expected.get(ref, {}), actual.get(ref, {})
        for pin in sorted(wanted.keys() | found.keys()):
            a, b = wanted.get(pin, ""), found.get(pin, "")
            if a != b:
                differences.append({"ref": ref, "pin": pin, "expected": a, "actual": b})
    return differences


def point_on_segment(x, y, segment):
    x1, y1, x2, y2 = (segment[k] for k in ("startX", "startY", "endX", "endY"))
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    return (abs(cross) < 1e-5 and min(x1, x2) - 1e-6 <= x <= max(x1, x2) + 1e-6
            and min(y1, y2) - 1e-6 <= y <= max(y1, y2) + 1e-6)


def audit():
    cfg = json.loads((ROOT / "config/pcb-shell-v1.json").read_text(encoding="utf-8"))
    expected = {part["ref"]: part["nets"] for part in cfg["parts"]}
    enet = json.loads((ROOT / "deliverables/pcb-shell-v1/制板文件/gun-mouse-v1-网表.enet")
                      .read_text(encoding="utf-8-sig"))
    exported = {c["props"]["Designator"]: {pin: p["net"] for pin, p in c["pinInfoMap"].items()
                                          if p["net"]} for c in enet["components"].values()}
    pcb_path = ROOT / "pcb/gun-mouse-v1/pcb/PCB1.epcb2"
    pcb = read_documents(pcb_path)[-1][1]
    pcb_attrs = attributes(pcb)
    pcb_refs = {h["id"]: pcb_attrs[h["id"]]["Designator"] for h, _, _ in pcb
                if h["type"] == "COMPONENT"}
    pcb_uids = {pcb_refs[h["id"]]: b.get("attrs", {}).get("Unique ID") for h, b, _ in pcb
                if h["type"] == "COMPONENT"}
    pcb_pins = {ref: {} for ref in pcb_refs.values()}
    for head, body, _ in pcb:
        if head["type"] == "PAD_NET":
            _, component, pin, _ = json.loads(head["id"])
            if component in pcb_refs and body.get("padNet"):
                pcb_pins[pcb_refs[component]][pin] = body["padNet"]

    sch_path = ROOT / "pcb/gun-mouse-v1/sch/Schematic1/P1.esch2"
    documents = read_documents(sch_path)
    symbols = {h["uuid"]: records for h, records in documents if h["docType"] == "SYMBOL"}
    sch = documents[-1][1]
    sch_attrs = attributes(sch)
    wires = {head["id"]: {"nets": set(), "net_attribute_lines": [], "segments": [], "pins": []}
             for head, _, _ in sch if head["type"] == "WIRE"}
    for head, body, line in sch:
        if head["type"] == "ATTR" and body.get("key") == "NET" and body.get("parentId") in wires:
            wire = wires[body["parentId"]]
            if body.get("value"):
                wire["nets"].add(body["value"])
                wire["net_attribute_lines"].append(line)
        if head["type"] == "LINE" and body.get("lineGroup") in wires:
            wires[body["lineGroup"]]["segments"].append((body, line))

    sch_pin_differences = []
    sch_uids = {}
    unsupported = []
    for head, component, _ in sch:
        if head["type"] != "COMPONENT":
            continue
        attr = sch_attrs[head["id"]]
        ref = attr["Designator"]
        sch_uids[ref] = attr.get("Unique ID")
        if component.get("isMirror"):
            unsupported.append(ref)
            continue
        symbol = symbols[attr["Symbol"]]
        pin_attrs = attributes(symbol)
        angle = math.radians(component["rotation"])
        for pin_head, pin, _ in symbol:
            if pin_head["type"] != "PIN" or pin["partId"] != component["partId"]:
                continue
            number = pin_attrs[pin_head["id"]]["Pin Number"]
            x = component["x"] + pin["x"] * math.cos(angle) - pin["y"] * math.sin(angle)
            y = component["y"] + pin["x"] * math.sin(angle) + pin["y"] * math.cos(angle)
            observed = set()
            for wire in wires.values():
                if any(point_on_segment(x, y, segment) for segment, _ in wire["segments"]):
                    observed.update(wire["nets"])
                    wire["pins"].append(f"{ref}.{number}")
            wanted = expected.get(ref, {}).get(number, "")
            if observed != ({wanted} if wanted else set()):
                sch_pin_differences.append({"ref": ref, "pin": number, "expected": wanted,
                                            "actual_labels": sorted(observed),
                                            "symbol_pin_xy": [round(x, 5), round(y, 5)]})

    short_evidence = [{"wire_id": ident, "net_labels": sorted(wire["nets"]),
                       "pins_on_wire": wire["pins"], "net_attribute_lines": wire["net_attribute_lines"],
                       "segments": [{"line": line, "xy": [s[k] for k in
                                     ("startX", "startY", "endX", "endY")]}
                                    for s, line in wire["segments"]]}
                      for ident, wire in wires.items() if len(wire["nets"]) > 1]
    result = {
        "scope": "离线只读；不代替软件网表编译、设计规则检查或电气性能验收",
        "configured_components": len(expected),
        "configured_connected_pins": sum(len(pins) for pins in expected.values()),
        "config_vs_exported_pcb": compare_pins(expected, exported),
        "config_vs_saved_pcb": compare_pins(expected, pcb_pins),
        "pcb_vs_schematic_unique_ids": [{"ref": ref, "pcb": pcb_uids.get(ref), "schematic": uid}
                                         for ref, uid in sch_uids.items() if pcb_uids.get(ref) != uid],
        "exported_unique_ids_stale": [{"ref": c["props"]["Designator"], "exported": uid,
                                       "saved_pcb": pcb_uids.get(c["props"]["Designator"])}
                                      for uid, c in enet["components"].items()
                                      if uid != pcb_uids.get(c["props"]["Designator"])],
        "schematic_source": str(sch_path),
        "schematic_pin_differences": sch_pin_differences,
        "wire_groups_with_conflicting_net_labels": short_evidence,
        "unsupported_mirrored_components": unsupported,
    }
    result["passed"] = not any(result[key] for key in result if isinstance(result[key], list))
    return result


def audit_compiled():
    """核对软件实际编译出的原理图网表，另列元数据差异，不将其伪称为 DRC 根因。"""
    config_path = ROOT / "config/pcb-shell-v1.json"
    schematic_path = ROOT / "outputs/pcb-shell-v1/schematic-netlist.enet"
    pcb_path = ROOT / "deliverables/pcb-shell-v1/制板文件/gun-mouse-v1-网表.enet"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    schematic = json.loads(schematic_path.read_text(encoding="utf-8-sig"))
    pcb = json.loads(pcb_path.read_text(encoding="utf-8-sig"))
    expected = {part["ref"]: part["nets"] for part in cfg["parts"]}
    compiled = {c["props"]["Designator"]: (uid, c) for uid, c in schematic["components"].items()}
    saved = {c["props"]["Designator"]: (uid, c) for uid, c in pcb["components"].items()}

    def connected(components):
        return {ref: {pin: p.get("net", "") for pin, p in c["pinInfoMap"].items() if p.get("net")}
                for ref, (_, c) in components.items()}

    differences = []
    for comparison, actual in (("配置与编译原理图", connected(compiled)),
                               ("配置与导出电路板", connected(saved)),
                               ("编译原理图与导出电路板", connected(saved))):
        want = connected(compiled) if comparison == "编译原理图与导出电路板" else expected
        differences.extend({"comparison": comparison, **diff} for diff in compare_pins(want, actual))
        if want.keys() != actual.keys():
            differences.append({"comparison": comparison, "component_set_difference":
                                sorted(want.keys() ^ actual.keys())})

    identity_keys = {"Footprint", "Device", "Supplier Part", "Manufacturer Part", "Convert to PCB",
                     "Unique ID", "Designator"}
    metadata = []
    unused_pad_differences = []
    for ref in sorted(compiled.keys() & saved.keys()):
        suid, sch = compiled[ref]
        puid, board = saved[ref]
        if suid != puid:
            differences.append({"ref": ref, "property": "网表器件唯一编号", "schematic": suid, "pcb": puid})
        for key in sorted(sch["props"].keys() | board["props"].keys()):
            a, b = sch["props"].get(key), board["props"].get(key)
            if a == b:
                continue
            delta = {"ref": ref, "property": key, "schematic": a, "pcb": b}
            (differences if key in identity_keys else metadata).append(delta)
        pin_delta = sorted(sch["pinInfoMap"].keys() ^ board["pinInfoMap"].keys())
        if pin_delta:
            unused_pad_differences.append({"ref": ref, "pin_numbers": pin_delta,
                                           "note": "引脚网络已逐项比较；这里列出空网络机械焊盘等编号差异"})

    return {
        "passed": not differences,
        "pcb_compared": True,
        "component_count": len(compiled),
        "pin_count": sum(len(pins) for pins in expected.values()),
        "differences": differences,
        "scope": "核对软件编译原理图与配置、导出电路板的已连接引脚、空网络、器件集合、唯一编号、封装及采购身份；"
                 "passed 不代表软件全部元数据同步或设计规则检查为零，不代表电气性能验收",
        "source": {"schematic": str(schematic_path), "pcb": str(pcb_path), "config": str(config_path)},
        "property_difference_counts": dict(Counter(delta["property"] for delta in metadata)),
        "metadata_differences": metadata,
        "unconnected_pin_structure_differences": unused_pad_differences,
        "global_metadata_difference_keys": sorted(key for key in schematic.keys() | pcb.keys()
                                                   if key != "components" and schematic.get(key) != pcb.get(key)),
        "drc_cause_status": "元数据差异是排查候选，尚未通过导入差异界面或软件检查变化证明根因",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiled", action="store_true", help="核对已经导出的编译原理图网表")
    parser.add_argument("--output", type=Path, help="另存 JSON 报告；不修改设计文件")
    args = parser.parse_args()
    report = audit_compiled() if args.compiled else audit()
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
