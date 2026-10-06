"""汇总已核对的单板自焊版交付件，校验未改固件并生成压缩包。

先运行：single_board_eda.py → package_single_board.py → economy_holder.py → render_holder.py →
check_left_equivalence.py，本脚本只复制与校验，不重新生成几何或电路。
"""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "gun-mouse-economy-single-v4"
DELIVER = ROOT / "deliverables" / "经济型单板自焊版"
PRINT = DELIVER / "打印文件"
REPORT = DELIVER / "检查报告"
HOLDER = ROOT / "outputs" / "economy-holder"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    PRINT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    source = ROOT / "deliverables" / "evt-a"
    for name in ("右键帽-EVT-A", "扳机触摸面盖", "摇杆帽"):
        for ext in ("stl", "step"):
            shutil.copy2(source / "打印文件" / (name + "." + ext), PRINT / (name + "." + ext))
    for ext in ("stl", "step"):
        shutil.copy2(ROOT / "deliverables" / "经济型改版" / "打印文件" / ("GY模块压框." + ext), PRINT / ("GY模块压框." + ext))

    # GY 适配资料沿用；工厂版的"SS移槽与GY局部复核"只适用于移槽左壳，本版不移槽，不复制。
    gy_src, gy_dst = ROOT / "deliverables" / "经济型工厂代焊版" / "GY模块适配说明", DELIVER / "GY模块适配说明"
    gy_dst.mkdir(exist_ok=True)
    for path in gy_src.iterdir():
        if path.name != "SS移槽与GY局部复核.json":
            shutil.copy2(path, gy_dst / path.name)
    # 全机螺丝统一为 M2 杯头内六角：压框两颗由 PA2×10 自攻改 M2×10 杯头（头部已复查）。
    note = gy_dst / "GY模块安装核对.txt"
    text = note.read_text(encoding="utf-8")
    old = "用两颗PA2×10盘头自攻螺丝；头径不大于4毫米。"
    assert text.count(old) == 1
    note.write_bytes(text.replace(old, "用两颗M2×10杯头内六角螺丝（与扳机调节螺钉同款），用1.5毫米内六角扳手拧；头径不大于4毫米。").encode("utf-8"))

    check = json.loads((source / "固件" / "固件文件校验.json").read_text(encoding="utf-8"))
    actual_sources = {name: sha(ROOT / "firmware" / "gun_mouse" / name) for name in check["sources"]}
    assert actual_sources == check["sources"], "固件源码与原工程样编译证据不一致"
    dest_firmware = DELIVER / "固件"
    dest_firmware.mkdir(exist_ok=True)
    for name, evidence in check["files"].items():
        path = source / "固件" / name
        assert sha(path) == evidence["sha256"] and path.stat().st_size == evidence["bytes"]
        shutil.copy2(path, dest_firmware / name)
    shutil.copy2(source / "固件" / "固件文件校验.json", dest_firmware / "固件文件校验.json")
    (REPORT / "固件与操作逻辑保持检查.json").write_bytes(json.dumps({
        "本轮修改固件": False, "源码校验": actual_sources, "二进制与原工程样完全相同": True,
        "范围": "原构建产物与源码逐文件校验；不代表本次新板已通电验收",
        "硬件改动对固件的影响": "R3改5.1k只改变充电电流；U4换同功能ESD；LED1/R4为纯硬件充电灯；扳机仍为J4的TRIG/GND常开触点，固件无需改动",
        "触摸与按键": "轻触仅启用体感；扣下左键、侧键右键、摇杆中键；松机械扳机但保持触摸时体感继续；离手清除积压",
        "摇杆": "偏转移动光标，与体感位移相加", "充电插拔": "不自动暂停控制",
    }, ensure_ascii=False, indent=2).encode("utf-8"))

    shutil.copy2(HOLDER / "几何检查.json", REPORT / "扳机与外壳核对.json")
    shutil.copy2(HOLDER / "左壳与GY适配核对.json", REPORT / "左壳与GY适配核对.json")
    shutil.copy2(HOLDER / "支架螺钉头核对.json", REPORT / "支架螺钉头核对.json")
    shutil.copy2(HOLDER / "螺丝统一核对.json", REPORT / "螺丝统一核对.json")
    unified = json.loads((REPORT / "螺丝统一核对.json").read_text(encoding="utf-8"))
    assert unified["结论"].startswith("统一为M2×10与M2×20")
    trigger = json.loads((REPORT / "扳机与外壳核对.json").read_text(encoding="utf-8"))
    assert trigger["same_switch_position_as_factory_daughter"]
    assert sha(ROOT / "config" / "economy-trigger.json") == trigger["config_sha256"]
    for name, info in trigger["parts"].items():
        assert sha(PRINT / (name + ".step")) == info["step_sha256"], name
        assert sha(PRINT / (name + ".stl")) == info["stl_sha256"], name
    left = json.loads((REPORT / "左壳与GY适配核对.json").read_text(encoding="utf-8"))
    assert left["同一实体"] and left["本版左壳SHA256"] == sha(PRINT / "左半壳-单板自焊.step")
    gy = json.loads((gy_dst / "几何检查.json").read_text(encoding="utf-8"))
    assert gy["print_parts"]["左半壳-经济型"]["step_sha256"] == left["GY适配检查所用左壳SHA256"]
    assert gy["print_parts"]["GY模块压框"]["stl_sha256"] == sha(PRINT / "GY模块压框.stl")

    required = ["左半壳-单板自焊", "右半壳-单板自焊", "扳机-经济型", "扳机开关支架-SS01GL", "GY模块压框",
                "右键帽-EVT-A", "扳机触摸面盖", "摇杆帽",
                "扳机设定片-经济型-0.8mm", "扳机设定片-经济型-1.0mm", "扳机设定片-经济型-1.2mm"]
    for name in required:
        for ext in ("stl", "step"):
            assert (PRINT / (name + "." + ext)).is_file(), "缺打印件 " + name
    assert sorted(p.stem for p in PRINT.glob("*.stl")) == sorted(required), "打印目录有多余或缺少的零件"

    board = json.loads((REPORT / "电路核对.json").read_text(encoding="utf-8"))
    assert board["工厂物料组数"] == 20 and board["每套工厂器件数"] == 37 and board["制板款数"] == 1
    assert board["采购修正"]["U4"]["Supplier Part"] == "C7420376"
    assert board["采购修正"]["R3"]["Supplier Part"] == "C25905"
    assert json.loads((REPORT / "电路规则检查.json").read_text(encoding="utf-8"))["value"]["count"] == 0
    native_key = "pcb\\" + NAME + "\\pcb\\PCB1.epcb2"
    assert sha(ROOT / "pcb" / NAME / "pcb" / "PCB1.epcb2") == board["本次导出SHA256"][native_key]
    for name, expected in board["订单清单SHA256"].items():
        assert sha(DELIVER / "制板文件" / name) == expected
    raw = REPORT / "原生导出"
    raw.mkdir(exist_ok=True)
    for name in ("原生物料.csv", "原生坐标.csv", "新主板网表.enet", "新原理图网表.enet"):
        source_file = ROOT / "outputs" / "economy-single-eda" / name
        assert sha(source_file) == board["本次导出SHA256"]["outputs\\economy-single-eda\\" + name]
        shutil.copy2(source_file, raw / name)
    for name in ("README.md", "扳机装配与调整.md", "预览图/扳机设定局部.png", "预览图/开关支架装配.png"):
        assert (DELIVER / name).is_file(), "缺说明 " + name

    manifest_path = DELIVER / "文件校验.json"
    package = DELIVER / "枪型飞鼠-单板自焊开关版.zip"
    paths = sorted(p for p in DELIVER.rglob("*") if p.is_file() and p not in (manifest_path, package))
    manifest = {str(p.relative_to(DELIVER)): {"bytes": p.stat().st_size, "sha256": sha(p)} for p in paths}
    manifest_path.write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in paths + [manifest_path]:
            z.write(p, str(p.relative_to(DELIVER)))
    with zipfile.ZipFile(package) as z:
        assert z.testzip() is None
        for name, info in manifest.items():
            assert hashlib.sha256(z.read(name.replace("\\", "/"))).hexdigest() == info["sha256"]
    print(json.dumps({"交付压缩包": str(package), "字节": package.stat().st_size, "文件数": len(paths) + 1},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
