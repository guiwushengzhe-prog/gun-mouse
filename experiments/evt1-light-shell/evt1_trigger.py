"""SS-01GL (straight hinge lever) trigger contact and switch holder for EVT-1.

The 30 g experiment was drawn for SS-01GL13 (simulated roller lever).  The
switch the user actually bought is SS-01GL, the same switch the main-branch
economy build uses.  Its body and mounting holes are identical; only the lever
differs, so this module applies the economy-build datums to the experiment's
nut-locked contact:

* contact screw axis Z -15.5 -> -19.02 (GL actuation point, 19.6 mm from the
  body's left end, config/economy-trigger.json)
* switch body bottom X -19.0 -> -17.1 (GL operating height 10.9-12.5 mm from
  the bottom lands on the same X as GL13's 13.6+-0.8 did)
* adjustment range (-1.5, 2.0) -> (-1.5, 1.2) so the cup head keeps >=0.3 mm
  from the GL body top at full press

The trigger keeps every slide, stop, spring and touch-cover surface of the
reviewed source trigger; only the contact ROI moves.  The holder is the
experiment's holder translated +1.9 mm in X, so its card, bosses, nut pockets
and washer stack are unchanged.
"""
from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
EXP = HERE.parent / "30g-onepiece-test-shell"
sys.path.insert(0, str(EXP))
import trigger_parts as tp  # noqa: E402
import trigger_holder as th  # noqa: E402
from trigger_parts import box, cyl_x, hex_prism_x, single  # noqa: E402

V = cq.Vector
SWITCH_MODEL = "SS-01GL"
AXIS_Y = 0.0
AXIS_Z = -19.02
GL13_AXIS_Z = tp.AXIS_Z
FACE_X, TRAVEL = tp.FACE_X, tp.TRAVEL
ADJUST_RANGE = (-1.5, 1.2)
HEAD_D, HEAD_K, SCREW_L = tp.HEAD_D, tp.HEAD_K, tp.SCREW_L
SHAFT_CLEARANCE_D = tp.SHAFT_CLEARANCE_D
NUT_AF, NUT_K, POCKET_AF = tp.NUT_AF, tp.NUT_K, tp.POCKET_AF
FIXED_NUT_X, JAM_NUT_X = tp.FIXED_NUT_X, tp.JAM_NUT_X
HOLDER_SHIFT_X = 1.9
SWITCH_BOTTOM_X = th.SWITCH_BOTTOM_X + HOLDER_SHIFT_X
BODY_LEFT_Z = th.BODY_LEFT_Z
HOLES = [(x + HOLDER_SHIFT_X, z) for x, z in th.HOLES]
CARD_X = tuple(x + HOLDER_SHIFT_X for x in th.CARD_X)
# SS-01GL datasheet values in assembly X (bottom + height), see economy config.
GL_OPERATING_X = (SWITCH_BOTTOM_X + 10.9, SWITCH_BOTTOM_X + 12.5)
GL_FREE_X_MAX = SWITCH_BOTTOM_X + 16.5
GL_BODY_TOP_X = SWITCH_BOTTOM_X + 9.5
GL_OVERTRAVEL_MIN = 1.2


def build_trigger(offset_x=0.0):
    """Experiment trigger with the nut-locked contact moved to the GL axis."""
    digest = hashlib.sha256(tp.SOURCE.read_bytes()).hexdigest()
    if digest != tp.SOURCE_SHA256:
        raise ValueError("Trigger source differs from the reviewed baseline")
    t = cq.importers.importStep(str(tp.SOURCE)).val()
    # Same EVT-A replacement of the original fixed contact and wire channel.
    t = t.cut(box(-2.01, -0.5, -2.51, 2.51, -17.01, -12.99))
    t = t.fuse(box(-0.5, 3.0, -0.75, 0.75, -13.25, -12.0))
    t = t.fuse(box(-1.5, 0.0, -0.75, 0.75, -12.0, -11.9))
    t = t.cut(box(-3.0, 3.6, 2.7, 4.1, -13.2, -11.9))
    t = t.cut(box(2.6, 3.6, -0.7, 4.1, -13.2, -11.9))
    # Cup-head slot, identical to the experiment but centred on the GL axis.
    dz = AXIS_Z - GL13_AXIS_Z
    t = t.cut(box(-0.6, 1.8, -2.5, 2.5, -17.9 + dz, -13.0 + dz))
    t = t.cut(box(-0.6, 1.8, 2.5, 5.1, -17.9 + dz, -14.2 + dz))
    t = t.cut(cyl_x(AXIS_Y, AXIS_Z, SHAFT_CLEARANCE_D / 2, 1.7, 11.9))
    pocket = hex_prism_x(0, AXIS_Z, POCKET_AF, FIXED_NUT_X, 7.3)
    entry = box(FIXED_NUT_X, 7.3, 0, 5.1, AXIS_Z - POCKET_AF / 2, AXIS_Z + POCKET_AF / 2)
    t = t.cut(pocket).cut(entry)
    chamber = cyl_x(0, AXIS_Z, 2.6, 3.5, FIXED_NUT_X)
    access = box(3.5, FIXED_NUT_X, 0, 5.1, AXIS_Z - 2.6, AXIS_Z + 2.6)
    t = t.cut(chamber).cut(access)
    # The experiment's Z=-21..-19.35 lightening window would cut the GL nut
    # pocket, so it is omitted.  The side-open blade window is kept.
    def blade_back_x(z):
        return 8.0 + (2.0 - 8.0) * (z + 4.0) / (-32.0 + 4.0) + 5.2
    lo, hi = -30.5, -7.0
    blade_window = tp._prism_xz([(blade_back_x(hi) + 1.2, hi), (blade_back_x(hi) + 6.5 - 2.4, hi),
                                 (blade_back_x(lo) + 6.5 - 2.4, lo), (blade_back_x(lo) + 1.2, lo)],
                                -5.1, 5.1)
    blade_window = cq.Workplane().add(blade_window).edges("|Y").fillet(.55).val()
    t = t.cut(blade_window)
    return single(t.translate(V(offset_x, 0, 0)), "SS-01GL M2-nut trigger")


def screw(delta=0.0, offset_x=0.0):
    if not ADJUST_RANGE[0] - 1e-9 <= delta <= ADJUST_RANGE[1] + 1e-9:
        raise ValueError("Adjustment outside the permitted interval")
    face = FACE_X - delta
    head = cyl_x(0, AXIS_Z, HEAD_D / 2, face, face + HEAD_K)
    socket = hex_prism_x(0, AXIS_Z, 1.5, face - 0.01, face + 1.0, 90.0)
    shank = cyl_x(0, AXIS_Z, 1.0, face + HEAD_K, face + HEAD_K + SCREW_L)
    return single(head.cut(socket).fuse(shank).translate(V(offset_x, 0, 0)), "M2x10 contact screw")


def nut(which="fixed", offset_x=0.0, corner_deg=0.0):
    x = FIXED_NUT_X if which == "fixed" else JAM_NUT_X
    n = hex_prism_x(0, AXIS_Z, NUT_AF, x, x + NUT_K, corner_deg)
    n = n.cut(cyl_x(0, AXIS_Z, 1.0, x - 0.01, x + NUT_K + 0.01))
    return single(n.translate(V(offset_x, 0, 0)), which + " M2 nut")


def screw_motion_envelope():
    lo, hi = ADJUST_RANGE
    head = cyl_x(0, AXIS_Z, HEAD_D / 2, FACE_X - hi - TRAVEL, FACE_X - lo + HEAD_K)
    shaft = cyl_x(0, AXIS_Z, 1.0, FACE_X - hi + HEAD_K - TRAVEL, FACE_X - lo + HEAD_K + SCREW_L)
    return single(head.fuse(shaft), "contact screw sweep")


def _shift(shape):
    return shape.translate(V(HOLDER_SHIFT_X, 0, 0))


def build_holder():
    return single(_shift(th.build_holder()), "SS-01GL holder")


def switch_rigid():
    return single(_shift(th.switch_rigid()), "SS-01GL nominal rigid body and solder lugs")


def switch_body_tolerance_envelope():
    return _shift(th.switch_body_tolerance_envelope())


def mount_hardware():
    bolts, nuts = th.mount_hardware()
    return [_shift(b) for b in bolts], [_shift(n) for n in nuts]


def mount_spacers():
    return [_shift(s) for s in th.mount_spacers()]


def terminal_wire_envelope():
    return _shift(th.terminal_wire_envelope())


def holder_groove_x():
    """Shell groove for the 1.6 mm card: card X +/-0.15 mm."""
    return (CARD_X[0] - 0.15, CARD_X[1] + 0.15)


def hardware_seats():
    return [{"id": f"trigger_switch_{i+1}", "seat": [x, th.BOSS_Y[1], z], "axis": [0, -1, 0],
             "length": 20, "head_d": 4, "head_h": 2.1, "nut_near_from_seat": 11.2,
             "nut_thickness": 1.6, "screw_tip_y": th.BOSS_Y[1] - 20}
            for i, (x, z) in enumerate(HOLES)]


def contact_budget():
    """Datasheet stack-up of the GL contact against the 4.1 mm stroke."""
    rows = {}
    for delta in (ADJUST_RANGE[0], 0.0, ADJUST_RANGE[1]):
        rest = FACE_X - delta
        press = rest - TRAVEL
        rows[f"delta_{delta:+.1f}"] = {
            "face_x_rest": round(rest, 3), "face_x_full_press": round(press, 3),
            "clear_of_GL_body_top_at_full_press_mm": round(press - GL_BODY_TOP_X, 3),
            "reaches_earliest_OP": press <= GL_OPERATING_X[1] + 1e-9,
            "reaches_latest_OP": press <= GL_OPERATING_X[0] + 1e-9,
            "rest_face_before_earliest_OP_mm": round(rest - GL_OPERATING_X[1], 3)}
    # Calibration target: closes at 3.1 mm (1.0 mm gauge), 1.0 mm to the hard stop.
    need = [round(FACE_X - 3.1 - op, 3) for op in GL_OPERATING_X]
    return {"switch": SWITCH_MODEL, "axis_z": AXIS_Z, "switch_bottom_x": SWITCH_BOTTOM_X,
            "operating_x_range": [round(v, 3) for v in GL_OPERATING_X],
            "free_x_max": round(GL_FREE_X_MAX, 3), "body_top_x": round(GL_BODY_TOP_X, 3),
            "adjust_range": list(ADJUST_RANGE), "per_delta": rows,
            "delta_needed_to_close_at_3.1mm_for_OP_extremes": need,
            "calibration_inside_range": all(ADJUST_RANGE[0] <= d <= ADJUST_RANGE[1] for d in need),
            "overtravel_after_calibrated_close_mm": round(TRAVEL - 3.1, 3),
            "overtravel_within_GL_minimum": TRAVEL - 3.1 <= GL_OVERTRAVEL_MIN}


def validate_internal():
    trigger = build_trigger()
    rows = {}
    for delta in (ADJUST_RANGE[0], 0.0, ADJUST_RANGE[1]):
        rows[f"screw_delta_{delta:+.1f}_vs_resin_mm3"] = trigger.intersect(screw(delta)).Volume()
    for which in ("fixed", "jam"):
        rows[f"{which}_nut_vs_resin_mm3"] = trigger.intersect(nut(which)).Volume()
    spin = cyl_x(0, AXIS_Z, NUT_AF / math.sqrt(3), JAM_NUT_X, JAM_NUT_X + NUT_K)
    rows["jam_nut_all_rotations_envelope_vs_resin_mm3"] = trigger.intersect(spin).Volume()
    # Resin left between the GL nut cavities and the spring bore (top Z=-22.2).
    cavity_low = AXIS_Z - max(2.6, POCKET_AF / math.sqrt(3))
    holder, rigid = build_holder(), switch_rigid()
    sweep = screw_motion_envelope()
    bolts, nuts = mount_hardware()
    rows["holder_vs_switch_rigid_mm3"] = holder.intersect(rigid).Volume()
    rows["holder_vs_switch_tolerance_mm3"] = holder.intersect(switch_body_tolerance_envelope()).Volume()
    rows["holder_vs_contact_sweep_mm3"] = holder.intersect(sweep).Volume()
    rows["switch_vs_contact_sweep_mm3"] = rigid.intersect(sweep).Volume()
    for i, (b, n) in enumerate(zip(bolts, nuts)):
        rows[f"holder_vs_bolt_{i+1}_mm3"] = holder.intersect(b).Volume()
        rows[f"holder_vs_nut_{i+1}_mm3"] = holder.intersect(n).Volume()
        rows[f"contact_sweep_vs_bolt_{i+1}_mm3"] = sweep.intersect(b).Volume()
    mid = trigger.translate(V(-TRAVEL / 2, 0, 0))
    distances = {"holder": mid.distance(holder), "switch_rigid": mid.distance(rigid),
                 **{f"bolt_{i+1}": mid.distance(b) for i, b in enumerate(bolts)}}
    ok = max(rows.values()) <= 1e-3 and min(distances.values()) > TRAVEL / 2
    return {"pass": ok, "trigger_volume_mm3": trigger.Volume(), "holder_volume_mm3": holder.Volume(),
            "overlaps_mm3": rows, "trigger_midstroke_distance_mm": distances,
            "resin_between_nut_cavity_and_spring_bore_mm": round(cavity_low - (-22.2), 3),
            "contact_budget": contact_budget()}


if __name__ == "__main__":
    import json
    print(json.dumps(validate_internal(), ensure_ascii=False, indent=2))
