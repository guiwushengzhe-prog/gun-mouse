"""Render EVT-1 previews with the 30 g experiment's VTK renderer.

    python render_evt1.py        # reads generated/*.step, writes generated/renders/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
EXP = HERE.parent / "30g-onepiece-test-shell"
sys.path.insert(0, str(EXP))
sys.path.insert(0, str(HERE))
import render_open_frame as rof  # noqa: E402
import verify_evt1 as ve  # noqa: E402

OUT = HERE / "generated"
OFFSETS = {"shell_left": (0, 55, 0), "shell_right": (0, -45, 0), "imu_cradle": (0, 30, 10),
           "imu": (0, 32, 10), "trigger": (26, 0, 0),
           "switch_holder": (-22, 12, 0), "trigger_switch": (-22, 12, 0), "right_cap": (0, 70, 0),
           "joystick_cap": (0, 78, 0), "pcb_board": (0, 8, 0), "battery": (0, -30, 0), "dev_board": (0, -20, 0)}
_base_explode = rof._explode


def _explode(name, kind, daughter=False, board_group=None):
    if kind == "component":
        group = {"carrier": "pcb_board", "dev_board": "dev_board", "imu": "imu",
                 "trigger_switch": "trigger_switch"}.get(board_group)
        if group in OFFSETS:
            return OFFSETS[group]
    return OFFSETS.get(name, _base_explode(name, kind, daughter, board_group))


def main():
    names = json.loads((OUT / "part-volumes.json").read_text(encoding="utf-8"))["parts"]
    parts = {k: cq.importers.importStep(str(OUT / f"{k}.step")).val() for k in names}
    refs = ve.references()
    rof._explode = _explode
    rof.VIEW_SPECS = (
        ("outside-left", "EVT-1 / LEFT (THUMB) SIDE", (0.28, 1.0, 0.20), False),
        ("outside-right", "EVT-1 / RIGHT (PALM) SIDE", (0.28, -1.0, 0.20), False),
        ("outside-front", "EVT-1 / FRONT: USB-C", (1.0, -0.55, 0.35), False),
    )
    rof.render_parts(parts, out_dir=OUT / "renders", references=refs)
    inner = {k: v for k, v in parts.items() if k != "shell_left"}
    rof.VIEW_SPECS = (
        ("inside-left", "EVT-1 / LEFT SHELL REMOVED", (0.28, 1.0, 0.20), False),
        ("exploded", "EVT-1 / EXPLODED", (0.65, 1.5, 0.45), True),
    )
    meta = rof.render_parts(inner, out_dir=OUT / "renders-inside", references=refs)
    print(json.dumps({k: v["path"] for k, v in meta["images"].items()}, indent=1))


if __name__ == "__main__":
    main()
