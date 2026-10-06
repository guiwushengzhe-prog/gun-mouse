"""汇总已核对的工厂代焊交付件，校验未改固件并生成压缩包。"""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELIVER = ROOT / "deliverables" / "经济型工厂代焊版"
PRINT = DELIVER / "打印文件"
REPORT = DELIVER / "检查报告"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    PRINT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    source = ROOT / "deliverables" / "evt-a"
    # 只复制仍适用的三件；新左右壳/扳机/设定片由工厂版机构脚本生成。
    for name in ("右键帽-EVT-A", "扳机触摸面盖", "摇杆帽"):
        for ext in ("stl", "step"):
            shutil.copy2(source / "打印文件" / (name + "." + ext), PRINT / (name + "." + ext))
    gy_clamp = ROOT / "deliverables" / "经济型改版" / "打印文件"
    for ext in ("stl", "step"):
        shutil.copy2(gy_clamp / ("GY模块压框." + ext), PRINT / ("GY模块压框." + ext))
    check = json.loads((source / "固件" / "固件文件校验.json").read_text(encoding="utf-8"))
    firmware_sources = ROOT / "firmware" / "gun_mouse"
    actual_sources = {name:sha(firmware_sources / name) for name in check["sources"]}
    assert actual_sources == check["sources"], "固件源码与原工程样编译证据不一致"
    dest_firmware = DELIVER / "固件"
    dest_firmware.mkdir(exist_ok=True)
    for name, evidence in check["files"].items():
        path = source / "固件" / name
        assert sha(path) == evidence["sha256"] and path.stat().st_size == evidence["bytes"]
        shutil.copy2(path, dest_firmware / name)
    shutil.copy2(source / "固件" / "固件文件校验.json", dest_firmware / "固件文件校验.json")
    (REPORT / "固件与操作逻辑保持检查.json").write_bytes(json.dumps({
        "本轮修改固件":False, "源码校验":actual_sources,
        "二进制与原工程样完全相同":True,
        "范围":"原构建产物与源码逐文件校验；不代表本次新板已通电验收",
        "触摸与按键":"轻触仅启用体感；扣下左键、侧键右键、摇杆中键；松机械扳机但保持触摸时体感继续；离手清除积压",
        "摇杆":"偏转移动光标，与体感位移相加",
        "充电插拔":"不自动暂停控制",
    }, ensure_ascii=False, indent=2).encode("utf-8"))
    required = ["左半壳-经济型", "右半壳-经济型", "扳机-经济型", "GY模块压框",
                "右键帽-EVT-A", "扳机触摸面盖", "摇杆帽",
                "扳机设定片-经济型-0.8mm", "扳机设定片-经济型-1.0mm", "扳机设定片-经济型-1.2mm"]
    for name in required:
        for ext in ("stl", "step"):
            assert (PRINT / (name + "." + ext)).is_file(), "缺打印件 " + name
    for name in ("gun-mouse-economy-factory-v3-Gerber.zip", "gun-mouse-economy-factory-v3-BOM.csv", "gun-mouse-economy-factory-v3-坐标文件.csv"):
        assert (DELIVER / "制板文件" / name).is_file(), "缺下单文件 " + name
    board_report = json.loads((REPORT / "电路核对.json").read_text(encoding="utf-8"))
    assert board_report["工厂物料组数"] == 23 and board_report["每套工厂器件数"] == 45
    assert board_report["采购修正"]["SW4"]["Manufacturer Part"] == "SS-01GL"
    assert board_report["采购修正"]["SW4"]["Supplier Part"] == "C2896769"
    assert board_report["原生采购与订单清单逐项一致"]
    assert board_report["最终45坐标与新原生几何逐字段一致"]
    assert (REPORT / "扳机与外壳核对.json").is_file()
    assert (DELIVER / "GY模块适配说明" / "SS移槽与GY局部复核.json").is_file()
    assert sha(ROOT / "pcb" / "gun-mouse-economy-factory-v3" / "pcb" / "PCB1.epcb2") == board_report["本次导出SHA256"]["pcb\\gun-mouse-economy-factory-v3\\pcb\\PCB1.epcb2"]
    assert json.loads((REPORT / "电路规则检查.json").read_text(encoding="utf-8"))["value"]["count"] == 0
    for name, expected in board_report["订单清单SHA256"].items():
        assert sha(DELIVER / "制板文件" / name) == expected
    trigger = json.loads((REPORT / "扳机与外壳核对.json").read_text(encoding="utf-8"))
    assert sha(ROOT / "config" / "economy-trigger.json") == trigger["config_sha256"]
    for name, info in trigger["parts"].items():
        assert sha(PRINT / (name + ".step")) == info["step_sha256"]
        assert sha(PRINT / (name + ".stl")) == info["stl_sha256"]
    gy = json.loads((DELIVER / "GY模块适配说明" / "SS移槽与GY局部复核.json").read_text(encoding="utf-8"))
    assert sha(PRINT / "左半壳-经济型.step") == gy["candidate_sha256"]
    # 保存本轮原生导出，方便脱离临时输出目录核查采购和全部引脚网络。
    raw = REPORT / "原生导出"
    raw.mkdir(exist_ok=True)
    for name in ("原生物料.csv", "原生坐标.csv", "新主板网表.enet"):
        source_file = ROOT / "outputs" / "economy-factory-eda" / name
        assert sha(source_file) == board_report["本次导出SHA256"]["outputs\\economy-factory-eda\\" + name]
        shutil.copy2(source_file, raw / name)
    manifest_path = DELIVER / "文件校验.json"
    package = DELIVER / "枪型飞鼠-便宜开关工厂代焊版.zip"
    paths = sorted(path for path in DELIVER.rglob("*") if path.is_file() and path not in (manifest_path, package))
    manifest = {str(path.relative_to(DELIVER)):{"bytes":path.stat().st_size,"sha256":sha(path)} for path in paths}
    manifest_path.write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in paths + [manifest_path]:
            z.write(path, str(path.relative_to(DELIVER)))
    with zipfile.ZipFile(package) as z:
        assert z.testzip() is None
        for name, info in manifest.items():
            assert hashlib.sha256(z.read(name.replace("\\", "/"))).hexdigest() == info["sha256"]
    print(json.dumps({"交付压缩包":str(package),"字节":package.stat().st_size,"文件数":len(paths)+1,"固件未修改":True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
