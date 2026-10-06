"""从正式主板网表和厂家 V1.4 排针定义生成固件引脚，不修改电路。"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "config" / "pcb-shell-v1.json"
# YD-ESP32-S3 电路图 V1.4；仅列本设计用到的引脚。
PIN_GPIO = {
    "J1": {"4": 4, "5": 5, "6": 6, "8": 15, "9": 16,
           "12": 8, "15": 9, "16": 10, "17": 11, "20": 14},
    "J2": {"4": 1, "5": 2, "19": 20, "20": 19},
}
EXPECTED = {"JOY_X", "JOY_Y", "JOY_SW", "BTN_R", "TRIG", "SDA", "SCL",
            "IMU_INT1", "IMU_INT2", "TOUCH", "VBAT_ADC", "VBUS_DET", "USB_DP", "USB_DN"}


def main():
    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    parts = {p["ref"]: p for p in config["parts"]}
    mapping = {}
    for ref, pins in PIN_GPIO.items():
        for pin, gpio in pins.items():
            net = parts[ref]["nets"].get(pin)
            if net not in EXPECTED or net in mapping:
                raise ValueError(f"排针网表已变化，需要重新核对厂家图纸：{ref}.{pin}={net}")
            if f"IO{gpio}" not in config["firmware_pins"]:
                raise ValueError(f"正式配置没有IO{gpio}说明")
            mapping[net] = gpio
    if set(mapping) != EXPECTED:
        raise ValueError("固件接口有缺项")
    target = ROOT / "firmware" / "gun_mouse" / "board_pins.h"
    text = ["#pragma once", "", "// 由 generate_board_pins.py 从正式主板配置生成，禁止手工改引脚。",
            "// 排针编号依据厂家 YD-ESP32-S3 电路图 V1.4。",
            "// 配置SHA256: " + hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            "namespace GunMouse {", "namespace Pins {"]
    text += [f"constexpr int {net} = {gpio};" for net, gpio in sorted(mapping.items())]
    text += ["// VBUS_DET使用模拟采样；触摸S3读数触摸时上升。",
             "}  // namespace Pins", "}  // namespace GunMouse", ""]
    target.write_text("\n".join(text), encoding="utf-8")
    print(json.dumps(mapping, ensure_ascii=False))


if __name__ == "__main__":
    main()
