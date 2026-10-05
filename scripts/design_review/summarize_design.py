"""重算现有设计的确定几何/电气关系；不把估算当作实物验收。"""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    cfg_path = ROOT / "config" / "pcb-shell-v1.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    route_path = ROOT / "evidence" / "formal-validation" / "baseline-routes.json"
    routes = json.loads(route_path.read_text(encoding="utf-8"))["value"]
    if routes["units"] != "mil":
        raise ValueError("布线快照单位变化，需重新核对")
    usb = {}
    for net in ("USB_DP", "USB_DN"):
        lines = [line for line in routes["lines"] if line["net"] == net]
        usb[net] = {"segments": len(lines),
                    "length_mm": sum(math.hypot(l["x2"] - l["x1"], l["y2"] - l["y1"]) * .0254 for l in lines),
                    "layers": sorted({l["layer"] for l in lines}),
                    "vias": sum(v["net"] == net for v in routes["vias"])}
    tr = cfg["trigger"]["switch_contact_from_board"]
    travel = tr["rest"] - tr["stop"]
    # 原厂SS-01GL13动作后最小保证余行程；另有安装/打印公差，未含在此。
    guaranteed_ot = 1.2
    stop_lower = tr["operate_max"] - guaranteed_ot
    stop_upper = tr["operate_min"]
    rb = cfg["right_button"]
    right_stop = rb["plunger_top_above_pcb"] + .02 - .85
    bt = cfg["battery"]
    thickness, width, length = bt["fits_up_to"]
    battery_clearance = [round(value, 10) for value in (
        bt["pocket_thickness"] - thickness,
        bt["pocket_xz_max"][0] - bt["pocket_xz_min"][0] - width,
        bt["pocket_xz_max"][1] - bt["pocket_xz_min"][1] - length)]
    scenarios = []
    for current in (80, 120, 180, 250):
        scenarios.append({"assumed_average_system_ma": current,
                          "assumed_capacity_fraction": .8,
                          "estimated_runtime_hours": 700 * .8 / current,
                          "usb_input_ma_at_360ma_charge_and_3ma_overhead": 360 + current + 3,
                          "ldo_loss_w_at_4p7v": (4.7 - 3.3) * current / 1000})
    result = {
        "manufacturing_finalized": False,
        "pcb_sha256": hashlib.sha256((ROOT / "pcb" / "gun-mouse-v1" / "pcb" / "PCB1.epcb2").read_bytes()).hexdigest(),
        "configuration_sha256": hashlib.sha256(cfg_path.read_bytes()).hexdigest(),
        "route_snapshot_sha256": hashlib.sha256(route_path.read_bytes()).hexdigest(),
        "usb_routes": usb,
        "usb_length_difference_mm": abs(usb["USB_DP"]["length_mm"] - usb["USB_DN"]["length_mm"]),
        "trigger": {"travel_mm": travel, "existing_stop_height_mm": tr["stop"],
                    "required_stop_lower_bound_mm": stop_lower, "required_stop_upper_bound_mm": stop_upper,
                    "fixed_stop_satisfies_guaranteed_switch_range": stop_lower <= stop_upper,
                    "current_earliest_switch_overtravel_mm": tr["operate_max"] - tr["stop"],
                    "current_latest_switch_operating_margin_mm": tr["operate_min"] - tr["stop"],
                    "adjustment_target_ot_mm_candidate": [.85, 1.05],
                    "tip_adjustment_range_mm_switch_tolerance_only":
                        [tr["operate_min"] - 1.05 - tr["stop"], tr["operate_max"] - .85 - tr["stop"]],
                    "note": "未含安装基准、焊接、槽内浮动和打印误差；没有证明现有开关已损坏。"},
        "right_button": {"existing_stop_height_mm": right_stop,
                         "operating_height_range_mm": [6.7, 7.1],
                         "guaranteed_minimum_ot_mm": .2,
                         "fixed_stop_required_range_mm": [6.9, 6.7],
                         "fixed_stop_satisfies_guaranteed_switch_range": False,
                         "note": "原厂公开索引参数；订货准确规格与实装基准待确认。"},
        "battery_maximum_placeholder_clearances_mm": {"thickness": battery_clearance[0],
                                                    "width": battery_clearance[1], "length": battery_clearance[2]},
        "spring": {"free_length_mm": cfg["trigger"]["spring"]["free_length"],
                   "rest_installed_length_mm": 9 + travel, "pressed_installed_length_mm": 9,
                   "note": "9mm座距来自现有机构切面；缺弹簧刚度、圈数、材料和压实高度，不计算弹力。"},
        "usb_digital_detection": {"input_v_at_4p75v_usb": 4.75 / 2,
                                  "guaranteed_high_v_at_3p3v_supply": .75 * 3.3,
                                  "digital_detection_guaranteed": 4.75 / 2 >= .75 * 3.3,
                                  "decision": "IO2采用校准后的模拟电压读取；关机输入隔离另议。"},
        "power_scenarios_not_measured": scenarios,
        "charger_loss_w_at_5v_and_360ma": {"battery_3p0v": (5 - 3.0) * .36,
                                          "battery_3p7v": (5 - 3.7) * .36},
        "estimate_boundary": "电流、0.8容量利用率、4.7V系统电源均为情景假设，非实测续航、发热或USB功率授权。",
    }
    out = ROOT / "evidence" / "design-review-v1" / "设计计算.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
