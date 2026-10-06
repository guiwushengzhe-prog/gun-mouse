r"""编译正式板固件并交付到 deliverables/evt-a/固件/。

步骤：先在电脑上编译运行逻辑检查（g++）；再把 firmware/gun_mouse 的源码复制到固定输入目录，
用 Arduino 命令行工具编译（固定缓存目录，小改动只增量编译）；最后复制烧录文件并记录校验值。
运行：python scripts\firmware\build_firmware.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKETCH = ROOT / "firmware" / "gun_mouse"
WORK = ROOT / "outputs" / "firmware"
# 编译工具链的链接器不能处理含中文的路径（项目在“枪型飞鼠”目录下），编译输入、缓存与输出放在纯英文目录。
ASCII_WORK = Path(os.environ["LOCALAPPDATA"]) / "GunMouseFirmware"
INPUT = ASCII_WORK / "compile-input" / "gun_mouse"
CACHE = ASCII_WORK / "build-cache"
OUT = ASCII_WORK / "out"
DELIVER = ROOT / "deliverables" / "evt-a" / "固件"
CLI = Path(r"E:\各种软件\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe")
CONFIG = Path(os.environ["USERPROFILE"]) / ".arduinoIDE" / "arduino-cli.yaml"
# 与旧项目在同型号开发板上实测的参数一致；串口改为原生 USB（底部 Type-C 可直接看日志和烧录）。
FQBN = ("esp32:esp32:esp32s3:FlashSize=16M,PartitionScheme=default_8MB,FlashMode=qio,PSRAM=opi,"
        "CDCOnBoot=cdc,USBMode=hwcdc,UploadSpeed=921600")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd, **kw):
    print(">", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def host_checks():
    exe = WORK / "test_firmware_logic.exe"
    WORK.mkdir(parents=True, exist_ok=True)
    run(["g++", "-std=c++17", "-O1", "-Wall", "-Wextra", f"-I{SKETCH}",
         ROOT / "firmware" / "tests" / "test_firmware_logic.cpp", "-o", exe])
    run([exe])
    core = WORK / "check_control_core.exe"
    run(["g++", "-std=c++17", "-O1", ROOT / "firmware" / "reference" / "check_control_core.cpp", "-o", core])
    run([core])


def main():
    host_checks()
    INPUT.mkdir(parents=True, exist_ok=True)
    sources = [p for p in SKETCH.iterdir() if p.suffix in (".ino", ".h", ".cpp")]
    for stale in INPUT.iterdir():  # 固定输入名单，避免多余文件让编译缓存失效
        if stale.name not in {p.name for p in sources}:
            stale.unlink()
    for p in sources:
        if not (INPUT / p.name).exists() or (INPUT / p.name).read_bytes() != p.read_bytes():
            shutil.copyfile(p, INPUT / p.name)
    start = time.time()
    run([CLI, "compile", "--jobs", "12", "--fqbn", FQBN, "--config-file", CONFIG,
         "--build-path", CACHE, "--output-dir", OUT, INPUT])
    elapsed = time.time() - start
    DELIVER.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in ("gun_mouse.ino.bin", "gun_mouse.ino.bootloader.bin", "gun_mouse.ino.partitions.bin",
                 "gun_mouse.ino.merged.bin"):
        src = OUT / name
        if src.exists():
            shutil.copyfile(src, DELIVER / name)
            files[name] = {"bytes": src.stat().st_size, "sha256": sha(src)}
    if "gun_mouse.ino.merged.bin" not in files:
        raise SystemExit("缺少合并烧录文件")
    record = {
        "fqbn": FQBN, "arduino_cli": str(CLI), "compile_seconds": round(elapsed, 1),
        "sources": {p.name: sha(p) for p in sorted(sources)},
        "files": files,
        "flash": "用合并文件写入地址 0x0（已含引导、分区表、升级选择区与应用）",
        "build_dirs": str(ASCII_WORK),
    }
    (DELIVER / "固件文件校验.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
