"""准备工厂代焊低价扳机开关的独立副本；保留主板和扳机小板走线。"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NAME = "gun-mouse-economy-factory-v3"
SOURCE = ROOT / "pcb" / "gun-mouse-v1"
TARGET = ROOT / "pcb" / NAME
OUT = ROOT / "outputs" / "economy-factory-eda"
RESERVED = {"Unique ID", "Footprint", "Device", "Symbol", "3D Model", "3D Model Transform", "Reuse Block", "Group ID", "Channel ID", "Convert to PCB", "Footprint Name", "Device Name", "Designator"}


def write_arguments():
    compiled = json.loads((ROOT / "deliverables" / "pcb-shell-v1" / "制板文件" / "gun-mouse-v1-网表.enet").read_text(encoding="utf-8"))
    by_ref = {c["props"]["Designator"]:c["props"] for c in compiled["components"].values()}
    parts = {ref:{key:value for key,value in by_ref[ref].items() if key not in RESERVED}
             for ref in ("U1", "R10", "R11", "R3", "R5", "SW4")}
    for ref in ("U1", "R10", "R11"):
        parts[ref]["Add into BOM"] = "no"
    changes = json.loads((ROOT / "config" / "evt-a.json").read_text(encoding="utf-8"))["bom_changes"]
    for ref in ("R3", "R5"):
        item = changes[ref]
        value = item["to_value"]
        parts[ref].update({"Name":value, "Value":value, "Supplier Part":item["lcsc"],
                          "Manufacturer Part":item["mpn"], "LCSC Part Name":f"厚膜电阻 {value} ±1%",
                          "Datasheet":f"https://www.lcsc.com/product-detail/{item['lcsc']}.html",
                          "Description":f"电阻类型:厚膜电阻;阻值:{value};精度:±1%;功率:62.5mW;工作电压:50V;",
                          "JLCPCB Part Class":"Extended Part" if ref == "R3" else "Basic Part"})
    sw = parts["SW4"]
    sw.update({"Name":"SS-01GL", "Supplier":"LCSC", "Supplier Part":"C2896769", "Manufacturer":"OMRON(欧姆龙)", "Manufacturer Part":"SS-01GL", "LCSC Part Name":"超小型微动开关，0.1A直摆杆，焊片端子", "Datasheet":"https://item.szlcsc.com/3139927.html", "Description":"SS-01GL，0.1A微小负载型，直摆杆，焊片端子；安装和动作尺寸按原厂图", "Add into BOM":"yes"})
    arguments = {"projectName":NAME, "parts":parts}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bom-properties-args.json").write_bytes(json.dumps(arguments, ensure_ascii=False).encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--args-only", action="store_true")
    if parser.parse_args().args_only:
        write_arguments()
        return
    if TARGET.exists():
        raise RuntimeError("目标副本已存在，保留已有修改，不覆盖")
    shutil.copytree(SOURCE, TARGET)
    index = TARGET / "gun-mouse-v1.eprj3"
    data = json.loads(index.read_text(encoding="utf-8"))
    data.update(name=NAME, content="经济型工厂代焊：扳机改SS-01GL，复用用户陀螺模块，不做V割")
    (TARGET / (NAME + ".eprj3")).write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    index.unlink()
    # 保留已有邮票孔连接。只关闭软件自动V割标识，不改原生铜线和铣切外框。
    path = TARGET / "pcb" / "PCB1.epcb2"
    lines = []
    is_pcb = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if "||" in line:
            h, body = line.split("||", 1)
            head = json.loads(h)
            if body.rstrip("|"):
                value = json.loads(body.rstrip("|"))
                if head["type"] == "DOCHEAD":
                    is_pcb = value.get("docType") == "PCB"
                if is_pcb and head["type"] == "PANELIZE":
                    value["on"] = False
                    value["showVCutIndicator"] = False
                    value["verticalSize"]["on"] = False
                    value["horizontalSize"]["on"] = False
                    line = json.dumps(head, separators=(",", ":")) + "||" + json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "|"
        lines.append(line)
    path.write_bytes("\n".join(lines).encode("utf-8"))
    # 编译网表包含继承的器件属性，不能仅取文档里显式写出的少数属性。
    write_arguments()
    print(json.dumps({"工程":str(TARGET), "操作":"保留工厂焊接扳机小板，不采用自焊开关支架", "低价开关代焊资格":"等待新订单实际匹配，不以零售价冒充代焊价"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
