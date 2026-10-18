"""最终版的共用布局，主板与壳件生成器均读取这里，毫米。"""
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"shell/最终装配版"
RELEASE = ROOT/"release/2026-10-18-最终版"
PASSIVE_CENTERS = {
    "R_TRIG": (-45.08, -12.0), "R_TOUCH": (-40.0, -15.5),
    "R_BAT_H": (-45.08, -19.0), "R_BAT_L": (-40.0, -22.5),
    "C_JOY_X": (-45.08, -26.0), "C_JOY_Y": (-40.0, -29.5),
    "C_TRIG": (-45.08, -33.0), "C_BAT": (-40.0, -36.5),
}
LOCAL = (-36.5, -4.0)
SEAT_Y = 5.34
NUT_Y = (-14.06, -12.46)
WIRE_HOLES = {"J_TRIG": {"1": (-25.5, -14.54), "2": (-25.5, -12.0)},
              "J_TOUCH": {"1": (-25.5, -22.0), "2": (-25.5, -19.46)}}


def move_passives(config):
    config = deepcopy(config)
    def shift(value, dx, dz):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("xz") and isinstance(item, list) and len(item) == 2:
                    value[key] = [item[0]+dx, item[1]+dz]
                elif key in {"x", "z"} and isinstance(item, list) and len(item) == 2:
                    value[key] = [v+(dx if key == "x" else dz) for v in item]
                else:
                    shift(item, dx, dz)
        elif isinstance(value, list):
            for item in value:
                shift(item, dx, dz)
    for part in config["parts"]:
        if part["ref"] in PASSIVE_CENTERS:
            old, target = part["position_xz"], PASSIVE_CENTERS[part["ref"]]
            shift(part, target[0]-old[0], target[1]-old[1])
        if part["ref"] in WIRE_HOLES:
            holes = WIRE_HOLES[part["ref"]]
            center = [sum(p[i] for p in holes.values())/len(holes) for i in (0, 1)]
            old = part["position_xz"]
            shift(part, center[0]-old[0], center[1]-old[1])
            for pad in part["pads"]:
                pad["xz"] = list(holes[pad["number"]])
    return config
