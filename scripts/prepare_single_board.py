"""复制单主板经济型工程：扳机开关改用户自焊于打印支架，取消扳机小板和第二款拼板。

只生成属性修改参数，不改铜线、过孔、焊盘、外框和网络：
- R12/C7/C8 与 U1/R10/R11 一样不装（只服务于未安装的原裸传感器）；
- R3 改用与 R1/R2 相同的 5.1k 物料，充电电流约 235mA，同时少一种物料；
- U4 改为同封装、同引脚功能的 SRV05-4（C7420376），板上 1-6、3-4 脚已有铜线直连；
- LED1/R4 充电灯保留。
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NAME = "gun-mouse-economy-single-v4"
SOURCE = ROOT / "pcb" / "gun-mouse-economy-v2"
TARGET = ROOT / "pcb" / NAME
OUT = ROOT / "outputs" / "economy-single-eda"
OMIT = ("U1", "R10", "R11", "R12", "C7", "C8")
RESERVED = {"Unique ID", "Footprint", "Device", "Symbol", "3D Model", "3D Model Transform", "Reuse Block",
            "Group ID", "Channel ID", "Convert to PCB", "Footprint Name", "Device Name", "Designator",
            "DeviceName", "FootprintName", "3D Model Title"}
U4_UPDATE = {
    "Name": "SRV05-4", "Manufacturer": "R+O(宏嘉诚)", "Manufacturer Part": "SRV05-4",
    "Supplier": "LCSC", "Supplier Part": "C7420376", "Supplier Footprint": "SOT-23-6L",
    "LCSC Part Name": "四路单向ESD 5V截止 1pF",
    "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/c94a8eedc13753364c00c764db36d52a.pdf",
    "Description": "四路单向ESD，1/3/4/6脚为I/O、2脚GND、5脚VCC；VRWM 5V，VBR≥6V，结电容1pF；"
                   "替换USBLC6-2SC6，本板1-6、3-4脚已有铜线直连",
    "Reverse Stand-Off Voltage (Vrwm)": "5V", "Clamping Voltage": "15V", "Peak Pulse Current (Ipp)": "4A",
    "Voltage - Breakdown": "6V", "Reverse Leakage Current (Ir)": "5uA", "Number of Channels": "四路",
    "Operating Temperature": "-55℃~+125℃", "Junction Capacitance": "1pF",
    "JLCPCB Part Class": "Extended Part", "Add into BOM": "yes"}


def write_arguments():
    compiled = json.loads((ROOT / "deliverables" / "pcb-shell-v1" / "制板文件" / "gun-mouse-v1-网表.enet")
                          .read_text(encoding="utf-8"))
    by_ref = {c["props"]["Designator"]: c["props"] for c in compiled["components"].values()}
    keep = lambda ref: {k: v for k, v in by_ref[ref].items() if k not in RESERVED}
    parts = {ref: keep(ref) for ref in OMIT}
    for ref in OMIT:
        parts[ref]["Add into BOM"] = "no"
    # R3 直接沿用 R1 的完整采购属性，使导出清单与 R1/R2 合为同一物料组。
    parts["R3"] = keep("R1")
    parts["U4"] = {**keep("U4"), **U4_UPDATE}
    arguments = {"projectName": NAME, "parts": parts}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bom-properties-args.json").write_bytes(json.dumps(arguments, ensure_ascii=False).encode("utf-8"))
    return arguments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--args-only", action="store_true")
    if parser.parse_args().args_only:
        write_arguments()
        return
    if TARGET.exists():
        raise RuntimeError("目标副本已存在，保留已有修改，不覆盖")
    shutil.copytree(SOURCE, TARGET)
    index = TARGET / "gun-mouse-economy-v2.eprj3"
    data = json.loads(index.read_text(encoding="utf-8"))
    data.update(name=NAME, content="经济型单板：取消扳机小板，开关用户自焊于打印支架；R3=5.1k，U4=SRV05-4")
    (TARGET / (NAME + ".eprj3")).write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    index.unlink()
    arguments = write_arguments()
    print(json.dumps({"工程": str(TARGET), "修改器件": sorted(arguments["parts"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
