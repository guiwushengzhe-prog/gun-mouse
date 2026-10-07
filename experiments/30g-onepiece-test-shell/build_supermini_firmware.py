"""Portable Arduino CLI build of the isolated 30g SuperMini firmware (Python 3.9+)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE / "firmware"
SKETCH = FIRMWARE / "gun_mouse_supermini"
BUILD_CONFIG = FIRMWARE / "build-config.json"
BOARD_CONFIG = HERE / "carrier-config.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args, **kwargs):
    print(">", " ".join(map(str, args)), flush=True)
    try:
        return subprocess.run(list(map(str, args)), check=True, **kwargs)
    except subprocess.CalledProcessError as error:
        if kwargs.get("capture_output"):
            print((error.stdout or "") + (error.stderr or ""), end="", flush=True)
        raise SystemExit(error.returncode) from error


def generate_pins(check=False):
    run([os.sys.executable, FIRMWARE / "generate_board_pins.py", *(["--check"] if check else [])])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default=os.environ.get("ARDUINO_CLI", "arduino-cli"))
    parser.add_argument("--gxx", default=os.environ.get("CXX", "g++"))
    parser.add_argument("--work-dir", type=Path, default=Path(tempfile.gettempdir()) / "GunMouseSuperMiniBuild")
    parser.add_argument("--arduino-home", type=Path, help="isolated data/downloads/user dirs (default: work-dir/toolchain)")
    parser.add_argument("--config-file", type=Path, help="reuse a supplied Arduino CLI YAML instead of generating one")
    parser.add_argument("--proxy", help="HTTP proxy for Arduino CLI downloads, if required")
    parser.add_argument("--install-core", action="store_true", help="download the pinned official core into the selected dirs")
    parser.add_argument("--host-only", action="store_true")
    parser.add_argument("--skip-host-tests", action="store_true", help="only when g++ is unavailable; manifest records tests as skipped")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if not str(work).isascii():
        raise SystemExit("Use an ASCII --work-dir so the ESP32 linker handles source/cache paths on Windows")
    work.mkdir(parents=True, exist_ok=True)
    generate_pins()
    config = json.loads(BUILD_CONFIG.read_text(encoding="utf-8"))
    host_result = "skipped by --skip-host-tests"
    if not args.skip_host_tests:
        exe = work / ("test_firmware_logic.exe" if os.name == "nt" else "test_firmware_logic")
        run([args.gxx, "-std=c++17", "-O1", "-Wall", "-Wextra", f"-I{SKETCH}",
             FIRMWARE / "tests" / "test_firmware_logic.cpp", "-o", exe])
        run([exe])
        host_result = "passed"
    if args.host_only:
        return

    cli_config = args.config_file
    if cli_config is None:
        arduino_home = (args.arduino_home or work / "toolchain").resolve()
        cli_config = work / "arduino-cli.yaml"
        directories = {key: str(arduino_home / key) for key in ("data", "downloads", "user")}
        for directory in directories.values():
            Path(directory).mkdir(parents=True, exist_ok=True)
        yaml = "board_manager:\n  additional_urls:\n    - " + config["package_url"] + "\ndirectories:\n"
        yaml += "".join(f"  {key}: {json.dumps(value)}\n" for key, value in directories.items())
        if args.proxy:
            yaml += "network:\n  proxy: " + json.dumps(args.proxy) + "\n"
        cli_config.write_text(yaml, encoding="utf-8")
    cli_base = [args.cli, "--config-file", cli_config]
    if args.install_core:
        run(cli_base + ["core", "update-index"])
        run(cli_base + ["core", "install", config["arduino_core"]])
    core_list = json.loads(run(cli_base + ["core", "list", "--format", "json"], capture_output=True, text=True).stdout)
    installed = {p["id"]: p.get("installed_version") for p in core_list["platforms"]}
    required_id, required_version = config["arduino_core"].split("@")
    if installed.get(required_id) != required_version:
        raise SystemExit("Install the pinned ESP32 core using --install-core; core version differs or is missing")
    # Copy source into an ASCII directory without touching baseline firmware or creating duplicate .ino files.
    compile_input = work / "input" / SKETCH.name
    compile_input.mkdir(parents=True, exist_ok=True)
    sources = sorted(p for p in SKETCH.iterdir() if p.suffix in (".ino", ".h", ".cpp"))
    for stale in compile_input.iterdir():
        if stale.is_file() and stale.name not in {p.name for p in sources}:
            stale.unlink()
    for source in sources:
        target = compile_input / source.name
        if not target.exists() or source.read_bytes() != target.read_bytes():
            shutil.copyfile(source, target)
    carrier_hash = sha(BOARD_CONFIG)
    source_hashes = {p.name: sha(p) for p in sources}
    output = work / "output"
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    compiled = run(cli_base + ["compile", "--jobs", args.jobs, "--fqbn", config["fqbn"],
                               "--build-path", work / "cache", "--output-dir", output, compile_input],
                   capture_output=True, text=True)
    compile_log = compiled.stdout + compiled.stderr
    print(compile_log, end="", flush=True)
    (FIRMWARE / "build-log.txt").write_text(compile_log, encoding="utf-8")
    elapsed = round(time.monotonic() - started, 1)
    generate_pins(check=True)
    if carrier_hash != sha(BOARD_CONFIG) or source_hashes != {p.name: sha(p) for p in sources}:
        raise SystemExit("Source/config changed during compile; run the build again before using the image")
    deliver = FIRMWARE / "bin"
    deliver.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for suffix in (".bin", ".bootloader.bin", ".partitions.bin", ".merged.bin"):
        name = SKETCH.name + ".ino" + suffix
        source = output / name
        if source.exists():
            target = deliver / name
            shutil.copyfile(source, target)
            artifacts[name] = {"bytes": target.stat().st_size, "sha256": sha(target)}
    if not any(name.endswith(".merged.bin") for name in artifacts):
        raise SystemExit("Arduino CLI did not produce the merged flash image")
    version = run(cli_base + ["version", "--format", "json"], capture_output=True, text=True)
    record = {
        "board": config["board"], "arduino_core": config["arduino_core"], "fqbn": config["fqbn"],
        "arduino_cli": json.loads(version.stdout), "compile_seconds": elapsed, "host_logic_tests": host_result,
        "host_test_source_sha256": sha(FIRMWARE / "tests" / "test_firmware_logic.cpp"),
        "carrier_config_sha256": carrier_hash, "build_config_sha256": sha(BUILD_CONFIG),
        "source_sha256": source_hashes, "artifacts": artifacts,
        "flash_address_merged": "0x0", "hardware_verified": False,
        "limits": "Compiled and host-tested only. Real board power, touch, ADC and BLE tests are pending."
    }
    (FIRMWARE / "build-manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
