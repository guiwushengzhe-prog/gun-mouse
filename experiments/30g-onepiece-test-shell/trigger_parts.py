"""EVT-A straight trigger with M2 x 10 socket-head contact and two M2 nuts.

All builders return assembled-coordinate CadQuery solids, in mm. The SS-01GL13
contact coordinates, 4.1 mm stroke, spring bore and touch-cover interface are
preserved; the new hand-solder switch holder replaces the daughter PCB.
No resin thread or machine-screw self tapping is required.  A fixed side-loaded
M2 nut takes the thread; a second accessible nut jams against it after setting.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent / "sources/扳机端接基准.step"
SOURCE_SHA256 = "3d4ae2f49bee34298d8de59f097785d632cf17c41b90ec30b2827c073e9fd166"
V = cq.Vector
AXIS_Y, AXIS_Z = 0.0, -15.5
FACE_X, TRAVEL = -2.0, 4.1
ADJUST_RANGE = (-1.5, 2.0)
HEAD_D, HEAD_K, SCREW_L = 4.0, 2.1, 10.0
SHAFT_CLEARANCE_D = 2.3
NUT_AF, NUT_K, POCKET_AF = 4.0, 1.6, 4.3
FIXED_NUT_X, JAM_NUT_X = 5.4, 3.8


def box(x0, x1, y0, y1, z0, z1):
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    z0, z1 = sorted((z0, z1))
    return cq.Solid.makeBox(x1-x0, y1-y0, z1-z0, V(x0, y0, z0))


def cyl_x(y, z, r, x0, x1):
    x0, x1 = sorted((x0, x1))
    return cq.Solid.makeCylinder(r, x1-x0, V(x0, y, z), V(1, 0, 0))


def hex_prism_x(y, z, af, x0, x1, corner_deg=0.0):
    r = af / math.sqrt(3.0)
    points = [V(x0, y+r*math.cos(math.radians(corner_deg+60*i)),
                z+r*math.sin(math.radians(corner_deg+60*i))) for i in range(6)]
    wire = cq.Wire.makePolygon(points, close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), V(x1-x0, 0, 0))


def single(shape, label):
    shape = shape.clean()
    solids = shape.Solids()
    if not shape.isValid() or len(solids) != 1:
        raise ValueError(f"{label} is not one valid solid")
    return solids[0]


def _cfg():
    return json.loads((ROOT / "config/pcb-shell-v1.json").read_text(encoding="utf-8"))


def _prism_xz(points, y0, y1):
    wire = cq.Wire.makePolygon([V(x, y0, z) for x, z in points], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), V(0, y1-y0, 0))


def build_touch_cover(offset_x=0.0):
    """Original PCB-Shell-V1 touch cover, with its original 0.15 mm edge gaps."""
    tr = _cfg()["trigger"]
    bl, ct = tr["blade"], tr["touch_cover_thickness"]
    z0, z1 = bl["z"]
    w = bl["width_y"] / 2
    def face_x(z):
        return 8.0 + (2.0-8.0)*(z+4.0)/(-32.0+4.0)
    def xf(z):
        return face_x(z) + bl["gap_to_grip"] + bl["thickness"]
    a, b = z1-3.15, z0+3.15
    cover = _prism_xz([(xf(a)-ct, a), (xf(a), a),
                      (xf(b), b), (xf(b)-ct, b)], -w+1.35, w-1.35)
    return single(cover.translate(V(offset_x, 0, 0)), "touch cover")


def build_trigger(offset_x=0.0, lightweight=True):
    """Keep original guide/stop/spring surfaces, replace the thread/contact ROI."""
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError("Precheck trigger source differs from reviewed baseline")
    t = cq.importers.importStep(str(SOURCE)).val()
    # Replace the original fixed contact and the central wire channel, as EVT-A.
    t = t.cut(box(-2.01, -0.5, -2.51, 2.51, -17.01, -12.99))
    t = t.fuse(box(-0.5, 3.0, -0.75, 0.75, -13.25, -12.0))
    t = t.fuse(box(-1.5, 0.0, -0.75, 0.75, -12.0, -11.9))
    t = t.cut(box(-3.0, 3.6, 2.7, 4.1, -13.2, -11.9))
    t = t.cut(box(2.6, 3.6, -0.7, 4.1, -13.2, -11.9))
    # Cup head is 0.7 mm taller than the old external hex head.  Max exit
    # position is x=1.6; the back of the new slot is x=1.8 (0.2 mm clearance).
    t = t.cut(box(-0.6, 1.8, -2.5, 2.5, -17.9, -13.0))
    t = t.cut(box(-0.6, 1.8, 2.5, 5.1, -17.9, -14.2))
    t = t.cut(cyl_x(AXIS_Y, AXIS_Z, SHAFT_CLEARANCE_D/2, 1.7, 11.9))
    # Fixed nut slides in from +Y.  Its pair of Z flats remains constrained;
    # the 4.3 mm entry height is smaller than a rotated M2 nut's 4.62 mm span.
    pocket = hex_prism_x(0, AXIS_Z, POCKET_AF, FIXED_NUT_X, 7.3)
    entry = box(FIXED_NUT_X, 7.3, 0, 5.1, AXIS_Z-POCKET_AF/2, AXIS_Z+POCKET_AF/2)
    t = t.cut(pocket).cut(entry)
    # Front nut is free to rotate.  Accessible from +Y with a 4 mm wrench or
    # a narrow nut-setting tool, it jams against the fixed nut at X=5.4.
    chamber = cyl_x(0, AXIS_Z, 2.6, 3.5, FIXED_NUT_X)
    access = box(3.5, FIXED_NUT_X, 0, 5.1, AXIS_Z-2.6, AXIS_Z+2.6)
    t = t.cut(chamber).cut(access)
    if lightweight:
        # Through window between the screw/nut envelope and spring bore.
        # Retain >=1.2 mm ligament on either side of the window in Z.
        window = box(3.0, 12.0, -5.1, 5.1, -21.0, -19.35)
        window = cq.Workplane().add(window).edges("|Y").fillet(0.65).val()
        t = t.cut(window)
        # Side-open blade window. Keep a 1.2 mm rear load rail, 2.4 mm of
        # front material (>=1.35 mm under the existing 1.05 mm foil recess),
        # and the original upper wire route / lower fingertip end.
        def blade_back_x(z):
            return 8.0+(2.0-8.0)*(z+4.0)/(-32.0+4.0)+5.2
        lo,hi=-30.5,-7.0
        blade_window=_prism_xz([(blade_back_x(hi)+1.2,hi),
                               (blade_back_x(hi)+6.5-2.4,hi),
                               (blade_back_x(lo)+6.5-2.4,lo),
                               (blade_back_x(lo)+1.2,lo)],-5.1,5.1)
        blade_window=cq.Workplane().add(blade_window).edges("|Y").fillet(.55).val()
        t=t.cut(blade_window)
    return single(t.translate(V(offset_x, 0, 0)), "M2-nut trigger")


def screw(delta=0.0, offset_x=0.0):
    """Conservative cup envelope: diameter 4.0, head 2.1, under-head length 10."""
    if not ADJUST_RANGE[0]-1e-9 <= delta <= ADJUST_RANGE[1]+1e-9:
        raise ValueError("Adjustment outside the permitted interval")
    face = FACE_X-delta
    head = cyl_x(0, AXIS_Z, HEAD_D/2, face, face+HEAD_K)
    socket = hex_prism_x(0, AXIS_Z, 1.5, face-0.01, face+1.0, 90.0)
    shank = cyl_x(0, AXIS_Z, 1.0, face+HEAD_K, face+HEAD_K+SCREW_L)
    return single(head.cut(socket).fuse(shank).translate(V(offset_x, 0, 0)), "M2x10 contact screw")


def nut(which="fixed", offset_x=0.0, corner_deg=0.0):
    """Unthreaded clearance model; screw/nut thread engagement is intentional."""
    if which not in ("fixed", "jam"):
        raise ValueError("which must be 'fixed' or 'jam'")
    x = FIXED_NUT_X if which == "fixed" else JAM_NUT_X
    n = hex_prism_x(0, AXIS_Z, NUT_AF, x, x+NUT_K, corner_deg)
    n = n.cut(cyl_x(0, AXIS_Z, 1.0, x-0.01, x+NUT_K+0.01))
    return single(n.translate(V(offset_x, 0, 0)), which+" M2 nut")


def screw_motion_envelope():
    """Full Cartesian product of the adjustment and the 4.1 mm trigger stroke."""
    lo, hi = ADJUST_RANGE
    head = cyl_x(0, AXIS_Z, HEAD_D/2, FACE_X-hi-TRAVEL, FACE_X-lo+HEAD_K)
    shaft = cyl_x(0, AXIS_Z, 1.0, FACE_X-hi+HEAD_K-TRAVEL, FACE_X-lo+HEAD_K+SCREW_L)
    return single(head.fuse(shaft), "contact screw sweep")


def interface_metadata():
    return {
        "coordinate_system": "original assembled X-forward/Y-left/Z-up, mm",
        "switch": "SS-01GL13 solder-lug switch in trigger_holder; original EVT-A contact coordinates, no daughter PCB",
        "travel_mm": TRAVEL, "press_translation_mm": [-TRAVEL, 0, 0],
        "guide_bar_y": [-5.0, 5.0], "guide_bar_z": [-28.0, -12.0],
        "spring": {"axis_yz": [0.0, -24.5], "trigger_bore_d": 4.6,
                   "bore_x": [-0.5, 8.5], "existing_spring": "OD4, wire0.3, free15"},
        "return_tooth": {"x": [-1.5, 0.0], "z": [-12.0, -10.5]},
        "hard_stop": {"pressed_trigger_rear_x": -4.6, "spring_seat_face_x": -4.6},
        "hardware": {"M2x10_DIN912": 1, "M2x20_DIN912": 0, "M2_hex_nuts_AF4_K1.6": 2,
                     "head_check_d_k_mm": [HEAD_D, HEAD_K]},
        "contact": {"axis_yz": [0.0, AXIS_Z], "nominal_face_x": FACE_X,
                    "adjust_delta_mm": list(ADJUST_RANGE), "positive_delta": "further toward switch",
                    "socket_af_depth_mm": [1.5, 1.0],
                    "socket_max_corner_d_mm": 1.5*2/math.sqrt(3),
                    "GL13_contact": "R1.3 simulated roller / formed stainless lever, not a rotating wheel",
                    "GL13_lever_width_nominal_min_mm": [3.6, 3.2],
                    "centered_lateral_overlap_beyond_socket_per_side_min_mm":
                        (3.2-1.5*2/math.sqrt(3))/2,
                    "contact_evidence": "Omron SS datasheet p6: lever width3.6, unmarked tolerance±0.4. The lever bridges the recess laterally; exact contact still requires a sample check.",
                    "source": "https://omronfs.omron.com/ja_JP/ecb/products/pdf/ss.pdf"},
        "side_access_keepout": {"x": [3.5-TRAVEL, 7.3], "y": [5.0, 8.0],
                                 "z": [AXIS_Z-2.6, AXIS_Z+2.6],
                                 "reason": "side-loaded nuts and visual access; not proof that a long axial hex driver fits behind the installed switch"},
        "fixed_nut_slot_x": [FIXED_NUT_X, 7.3], "jam_nut_chamber_x": [3.5, FIXED_NUT_X],
        "shaft_tip_x_at_adjust_limits": [FACE_X-d+HEAD_K+SCREW_L for d in ADJUST_RANGE],
        "calibration": [
            "Install both M2 nuts before the M2x10 screw; slide the fixed nut through the +Y side port.",
            "Leave the +Y trigger gate off and connect the touch wire only after setting. Install the trigger and spring; test with a 1.0 mm gauge at the spring-seat stop.",
            "Fully release; withdraw the trigger and spring through the open +Y side. Adjust the screw outside the frame with an ordinary 1.5 mm hex driver; 1/8 turn is 0.05 mm for M2x0.4. Reinstall and repeat until NO just closes with the 1.0 mm gauge.",
            "Withdraw again; hold the hex driver to preserve the setting and use a thin 4 mm nut wrench (thickness<=1.8 mm) to tighten the front nut against the trapped rear nut. Reinstall the trigger and spring.",
            "After locking, repeat from fully released: 0.8 mm gauge must close, 1.2 mm gauge must stay open.",
            "Remove gauge; verify full-press closure and immediate release opening; install the +Y gate and connect the touch wire; repeat both gauge checks and free return."
        ],
        "axial_driver_boundary": {
            "nearest_switch_body_x_conservative": -8.4,
            "available_external_length_at_rest_mm": "6.4-delta",
            "available_external_length_at_1mm_gauge_mm": "3.3-delta",
            "available_external_length_at_full_press_mm": "2.3-delta",
            "range_note": "delta in [-1.5,2.0]; at the 1mm gauge the worst gap is only1.3mm. An ordinary long L-key must not be used in place.",
            "method": "remove and adjust trigger outside the frame, then reinstall and check"
        },
        "source": {"path": str(SOURCE.relative_to(ROOT)), "sha256": SOURCE_SHA256},
        "lightweight_blade": {"side_window_z": [-30.5,-7.0],
                              "rear_rail_mm":1.2,"front_material_mm":2.4,
                              "material_below_touch_recess_min_mm":1.35,
                              "preserved":"slide bars, return tooth, spring bore, screw/nut seats, touch wire channel, cover recess"},
        "parking_anchor_candidates": [[18.0,5.0,-6.5],[11.9,5.0,-30.8]],
        "parking_anchor_boundary": "Use a nearby nonfunctional outside blade surface after checking the exact face; do not touch slide/stop/foil/nut/spring surfaces",
        "boundary": "resin fit, printed nut-slot grip and actual switch adjustment require first-sample verification"
    }


def validate_internal():
    trigger = build_trigger()
    rows = {}
    for delta in ADJUST_RANGE + (0.0,):
        s = screw(delta)
        rows[f"screw_delta_{delta:+.1f}_vs_resin_mm3"] = trigger.intersect(s).Volume()
    for which in ("fixed", "jam"):
        rows[f"{which}_nut_vs_resin_mm3"] = trigger.intersect(nut(which)).Volume()
    for angle in range(0, 61, 5):
        rows[f"jam_nut_angle_{angle}_vs_resin_mm3"] = trigger.intersect(nut("jam", corner_deg=angle)).Volume()
    rotating_nut_envelope = cyl_x(0, AXIS_Z, NUT_AF/math.sqrt(3), JAM_NUT_X, JAM_NUT_X+NUT_K)
    rows["jam_nut_all_rotations_envelope_vs_resin_mm3"] = trigger.intersect(rotating_nut_envelope).Volume()
    rows["cover_vs_trigger_mm3"] = trigger.intersect(build_touch_cover()).Volume()
    if max(rows.values()) > 0.001:
        raise ValueError("Trigger internals interfere: " + json.dumps(rows))
    return {"valid": trigger.isValid(), "solids": len(trigger.Solids()),
            "trigger_volume_mm3": trigger.Volume(), "cover_volume_mm3": build_touch_cover().Volume(),
            "clearance_overlaps_mm3": rows,
            "minimum_screw_tip_projection_beyond_fixed_nut_mm":
                FACE_X-ADJUST_RANGE[1]+HEAD_K+SCREW_L-(FIXED_NUT_X+NUT_K),
            "interface": interface_metadata()}


def validate_fixed_references(refs):
    """Check real bare-board geometry and static envelopes, excluding SW4 lever.

    The full SW4 top envelope includes the deforming GL13 lever, so a contact
    overlap with it is not a rigid-body clearance test.  A separately identified
    conservative body prism uses the official 10.2 mm body envelope height plus
    the unmarked 0.4 mm tolerance.  That prism is labelled nominal/assumed.
    """
    trigger = build_trigger()
    envelope = screw_motion_envelope()
    stationary = {key: refs[key] for key in ("pcb_board", "battery", "dev_board", "imu", "daughter_board") if key in refs}
    for part in refs["component_envelopes"]:
        if part["ref"] == "SW4" and part["side"] == "top":
            bb = part["shape"].BoundingBox()
            body = box(-19.0, -19.0+10.2+0.4, bb.ymin, bb.ymax, bb.zmin, bb.zmax)
            stationary["SS01GL13_rigid_body_assumed_with_0.4mm_tolerance"] = body
        else:
            stationary[f"{part['ref']}_{part['side']}_static_envelope"] = part["shape"]
    if "daughter_board" not in refs:
        # A current carrier has no SW4 component. Include the separate GL13
        # fixture explicitly instead of accidentally omitting the switch.
        from trigger_holder import build_holder, switch_body_tolerance_envelope, mount_hardware
        stationary["SS01GL13_rigid_body_assumed_with_0.4mm_tolerance"]=switch_body_tolerance_envelope()
        stationary["trigger_holder"]=build_holder()
        bolts,nuts=mount_hardware()
        for i,shape in enumerate(bolts+nuts):
            stationary[f"switch_mount_hardware_{i}"]=shape
    report = {}
    # The bound d(midpoint)>=travel/2 proves the entire linear motion cannot
    # intersect the target.  A conservative exact screw sweep covers all stroke
    # positions and all adjustment positions, without discrete-pose sampling.
    mid = trigger.translate(V(-TRAVEL/2, 0, 0))
    for name, shape in stationary.items():
        screw_overlap = envelope.intersect(shape).Volume()
        midpoint_distance = float(mid.distance(shape))
        if screw_overlap > 0.001 or midpoint_distance+1e-7 < TRAVEL/2:
            raise ValueError(f"{name}: clearance certificate failed")
        report[name] = {"screw_all_adjustment_and_motion_overlap_mm3": screw_overlap,
                        "screw_envelope_min_distance_mm": float(envelope.distance(shape)),
                        "trigger_all_motion_distance_bound_margin_mm": midpoint_distance-TRAVEL/2}
    return {"fixed_reference_clearances": report,
            "boundary": "The switch body is a dimensioned conservative prism; the lever motion and physical contact are not proved by a static library bounding box."}


if __name__ == "__main__":
    print(json.dumps(validate_internal(), ensure_ascii=False, indent=2))
