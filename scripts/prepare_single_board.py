"""复制单主板经济型工程：扳机开关改用户自焊于打印支架，取消扳机小板和第二款拼板。

只生成属性修改参数，不改铜线、过孔、焊盘、外框和网络：
- R12/C7/C8 与 U1/R10/R11 一样不装（只服务于未安装的原裸传感器）；
- R3 改用与 R1/R2 相同的 5.1k 物料，充电电流约 235mA，同时少一种物料；
- U4（USB 静电保护）不装：SRV05-4 国内库存不足，用户选择省掉；板上 1-6、3-4 脚已有铜线直连，
  不装时 USB 数据线和充电仍然连通，只是 USB 口没有静电保护。属性保留原设计 USBLC6-2SC6（C7519）；
- LED1/R4 充电灯保留；
- J3/J4/J5 三个 PH2.0 座不装（同一扩展料，三个都不装才免一种换料费）：电池、扳机开关、触摸电极的线
  由用户直接焊到原焊盘上；网购电池多为两根裸线，直接焊还避免 PH 插头正负极与板子相反。
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
OMIT = ("U1", "R10", "R11", "R12", "C7", "C8", "J3", "J4", "J5", "U4")
RESERVED = {"Unique ID", "Footprint", "Device", "Symbol", "3D Model", "3D Model Transform", "Reuse Block",
            "Group ID", "Channel ID", "Convert to PCB", "Footprint Name", "Device Name", "Designator",
            "DeviceName", "FootprintName", "3D Model Title"}


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
    data.update(name=NAME, content="经济型单板：取消扳机小板，开关用户自焊于打印支架；R3=5.1k，U4不装")
    (TARGET / (NAME + ".eprj3")).write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    index.unlink()
    arguments = write_arguments()
    print(json.dumps({"工程": str(TARGET), "修改器件": sorted(arguments["parts"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
