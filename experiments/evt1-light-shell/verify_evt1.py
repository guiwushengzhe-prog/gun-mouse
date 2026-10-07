"""EVT-1 assembly verification: interference, motion, fasteners, paths, USB.

Reuses the 30 g experiment's generic checkers (verify_open_frame.py) with an
EVT-1 part set and reference layout.  Everything is nominal CAD against
nominal/conservative component envelopes; resin fit, strength, switch feel,
RF range and charging temperature still need the first print.

    python verify_evt1.py            # build parts in memory, write generated/assembly-check.json
    python verify_evt1.py --from-generated
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import time
from itertools import combinations
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
EXP = HERE.parent / "30g-onepiece-test-shell"
sys.path.insert(0, str(EXP))
sys.path.insert(0, str(HERE))
import verify_open_frame as vof  # noqa: E402
import reference_models as rm  # noqa: E402
import build_evt1 as be  # noqa: E402
import evt1_trigger as et  # noqa: E402

V = cq.Vector
box, cyl_y, cyl_x = rm.box, rm.cyl_y, be.cyl_x
E = be.E
EPS = vof.EPS_VOLUME
OUT = HERE / "generated"


# ---------------------------------------------------------------- references

def assembly_cfg():
    """EVT-1 module placement in the reference_models schema."""
    base = json.loads((EXP / "open-frame-config.json").read_text(encoding="utf-8"))
    cfg = copy.deepcopy(base)
    sm, im, bt = E["supermini"], E["imu"], E["battery"]
    bx, bz, by = sm["board_x"], sm["board_z"], sm["board_y"]
    tc, rx = sm["top_components"], sm["usb_receptacle"]
    cfg["reference_boxes"] = {
        "battery": bt["bounds"],
        "dev_board": [bx[0], bx[1], by[0], by[1], bz[0], bz[1]],
        "imu": [im["board_x"][0], im["board_x"][1], im["board_y"][0], im["board_y"][1],
                im["board_z"][0], im["board_z"][1]]}
    cfg["module_envelopes"] = [
        {"ref": "SuperMini-top", "board_group": "dev_board", "side": "top",
         "bounds": [tc["x"][0], tc["x"][1], tc["y"][0], tc["y"][1], tc["z"][0], tc["z"][1]],
         "provenance": "EVT-1: 30 g allowance rotated 180 deg about Y and moved to the nose"},
        {"ref": "SuperMini-back-wire", "board_group": "dev_board", "side": "back",
         "bounds": [bx[0] + 1.0, bx[1] - 1.0, sm["back_wire_y"][0], sm["back_wire_y"][1], bz[0] + 1.6, bz[1] - 1.6],
         "provenance": "Back solder/wire allowance 2.0 mm, kept off the 1.6 mm edge ledges"},
        {"ref": "SuperMini-USB", "board_group": "dev_board", "side": "top",
         "bounds": [rx["x"][0], rx["x"][1], rx["y"][0], rx["y"][1], rx["z"][0], rx["z"][1]],
         "provenance": "Conservative 2.5 mm USB-C overhang toward the front wall"},
        {"ref": "GY601-top", "board_group": "imu", "side": "top",
         "bounds": [-21, -2.4, 9, 11.8, 21.1, 36.9], "provenance": "Unchanged from the 30 g layout"},
        {"ref": "GY601-wire", "board_group": "imu", "side": "top",
         "bounds": [-12, -3, 11.8, 14, 20.1, 23.1], "provenance": "Unchanged from the 30 g layout"}]
    return cfg


def references():
    refs = rm.build_references(be.CARRIER, assembly_cfg())
    # reference_models adds the SS-01GL13 at X -19; EVT-1 uses SS-01GL at -17.1.
    refs["trigger_switch"] = et.switch_rigid()
    env = et.switch_body_tolerance_envelope()
    for x, z in et.HOLES:
        env = env.cut(cyl_y(x, z, 2.35 / 2, -3.7, 3.7))
    refs["component_envelopes"] = [e for e in refs["component_envelopes"]
                                   if e["ref"] != "SS01GL13-body-tolerance"]
    refs["component_envelopes"].append({
        "shape": env, "ref": "SS01GL-body-tolerance", "side": "all", "board_group": "trigger_switch",
        "bounds_mm": list(vof.bounds(env)), "conservative": True,
        "provenance": "Omron SS body +/-0.4 mm, at the economy-build SS-01GL datum (bottom X -17.1)"})
    return refs


def envelopes_by_ref(refs, ref):
    return [e for e in refs["component_envelopes"] if e["ref"] == ref]


# ---------------------------------------------------------------- helpers

def pair(a, b):
    return vof.shape_pair(a, b)


def clear(a, b):
    return vof.volume_overlap(a, b) <= EPS


def compound(shapes):
    return cq.Compound.makeCompound(list(shapes))


def accessory_shapes():
    """Wire corridors and purchased parts that are not separate references."""
    sw = E["battery_switch"]
    x0, x1 = sw["body_x"]
    y0, y1 = sw["body_y"]
    z0, z1 = sw["body_z"]
    yc, zc = (y0 + y1) / 2, (z0 + z1) / 2
    a_y, a_z = sw["actuator_envelope_yz"]
    trav = sw["actuator_travel_z"]
    switch_body = box(x0, x1, y0, y1, z0, z1)
    actuator = box(x0 - sw["actuator_height"], x0, yc - a_y / 2, yc + a_y / 2,
                   zc - trav / 2 - a_z / 2, zc + trav / 2 + a_z / 2)
    pins = box(x1, sw["pins_x"][1], yc - .9, yc + .9, z0 + 1.0, z1 - 1.0)
    return {
        # Touch wire: leaves the trigger's +Y groove behind the bar, through the
        # gate slot, over the gate and holder groove, down to J_TOUCH.
        "touch_wire_exit": box(-6.0, -1.6, 2.7, 9.6, -14.0, -11.5),
        "touch_wire_run": box(-24.6, -1.0, 8.9, 10.6, -14.0, -11.5),
        "touch_wire_drop": box(-26.3, -24.6, -1.5, 10.6, -18.6, -11.5),
        # SS-01GL lead corridor (economy shift applied) to J_TRIG.
        "switch_leads": et.terminal_wire_envelope(),
        "switch_leads_to_J_TRIG": box(-26.4, -22.3, -1.5, 2.3, -12.5, -0.5),
        "battery_switch_body": switch_body,
        "battery_switch_actuator_full_travel": actuator,
        "battery_switch_pins": pins,
    }


def fasteners():
    rows = []
    hole_nut = {"H1": "imu_cradle"}
    for hid, (x, z) in be.HOLES.items():
        seat = be.SC["pcb_M2x20_seat_y"]
        rows.append({"id": "PCB_" + hid, "seat": [x, seat, z], "axis": [0, 1, 0], "length": 20,
                     "head_d": 4, "head_h": 2.1, "nuts": [{"near_from_seat": .55 - seat, "angle": 30}],
                     "nut_part": hole_nut.get(hid, "shell_left")})
    for x, z in be.SC["shell_only_xz"]:
        seat = be.SC["shell_only_M2x20_seat_y"]
        tip = seat + 20
        rows.append({"id": f"shell_{x:g}_{z:g}", "seat": [x, seat, z], "axis": [0, 1, 0], "length": 20,
                     "head_d": 4, "head_h": 2.1,
                     "nuts": [{"near_from_seat": (tip - 2.6 + .1) - seat, "angle": 30}],
                     "nut_part": "shell_left"})
    for s in et.hardware_seats():
        rows.append({"id": s["id"], "seat": s["seat"], "axis": s["axis"], "length": 20, "head_d": 4,
                     "head_h": 2.1, "nuts": [{"near_from_seat": 11.2, "angle": 0}],
                     "tool_removed_parts": ["shell_left"],
                     "tool_access_note": "Tightened on the bench before the holder is dropped in"})
    face = et.FACE_X
    rows.append({"id": "trigger_contact", "seat": [face + et.HEAD_K, 0, et.AXIS_Z], "axis": [1, 0, 0],
                 "length": 10, "head_d": 4, "head_h": 2.1,
                 "nuts": [{"near_from_seat": et.JAM_NUT_X - (face + et.HEAD_K), "angle": 0},
                          {"near_from_seat": et.FIXED_NUT_X - (face + et.HEAD_K), "angle": 0}],
                 "tool_removed_parts": ["shell_left", "shell_right", "switch_holder"],
                 "tool_removed_references": ["trigger_switch"],
                 "tool_access_note": "Adjusted with the trigger lifted out of the right shell (left shell off)"})
    return rows


# ---------------------------------------------------------------- checks

def static_checks(parts, refs):
    result = {"part_pairs": {}, "part_vs_reference": {}, "part_vs_envelopes": {}}
    for a, b in combinations(parts, 2):
        result["part_pairs"][f"{a}/{b}"] = pair(parts[a], parts[b])
    fixed = {k: v for k, v in refs.items() if isinstance(v, cq.Shape)}
    for p, s in parts.items():
        for r, ref in fixed.items():
            result["part_vs_reference"][f"{p}/{r}"] = pair(s, ref)
    allowed = {("right_cap", "SW2", 1), ("joystick_cap", "SW1", 1)}
    hits = []
    for p, s in parts.items():
        for env in refs["component_envelopes"]:
            pr = pair(s, env["shape"])
            if not pr["clear_of_volume_interference"]:
                hits.append({"part": p, "ref": env["ref"], "side": env["side"], "pad": env.get("pad"),
                             "sub_envelope": env.get("sub_envelope"),
                             "allowed_contact": (p, env["ref"], env.get("sub_envelope")) in allowed, **pr})
    result["part_vs_envelopes"] = hits
    result["pass"] = (all(v["clear_of_volume_interference"] for v in result["part_pairs"].values())
                      and all(v["clear_of_volume_interference"] for v in result["part_vs_reference"].values())
                      and all(h["allowed_contact"] for h in hits))
    return result


def accessory_checks(parts, refs, acc):
    out = {}
    fixed = {k: v for k, v in refs.items() if isinstance(v, cq.Shape)}
    for name, shape in acc.items():
        row = {}
        for p, s in parts.items():
            pr = pair(shape, s)
            if not pr["clear_of_volume_interference"]:
                row[f"part/{p}"] = pr
        for r, ref in fixed.items():
            if name.startswith("switch_leads") and r == "trigger_switch":
                continue
            pr = pair(shape, ref)
            if not pr["clear_of_volume_interference"]:
                row[f"ref/{r}"] = pr
        out[name] = {"collisions": row, "clear": not row}
    # The trigger touch exit corridor must clear the trigger at both ends of travel.
    for t in (0.0, et.TRAVEL):
        moved = parts["trigger"].translate(V(-t, 0, 0))
        out[f"touch_wire_exit_vs_trigger_at_{t}"] = {"clear": clear(acc["touch_wire_exit"].cut(
            box(-6.0, -1.6, 2.7, 5.35, -14.0, -11.5)), moved)}
    out["pass"] = all(v["clear"] for v in out.values() if isinstance(v, dict))
    return out


def motion_checks(parts, refs):
    others = lambda skip: {k: v for k, v in parts.items() if k not in skip}  # noqa: E731
    fixed = {k: v for k, v in refs.items() if isinstance(v, cq.Shape)}
    env = refs["component_envelopes"]
    states = {}

    def check(label, shape, skip_parts, skip_env=(), active=None):
        hits = {}
        for k, s in others(skip_parts).items():
            pr = pair(shape, s)
            if not pr["clear_of_volume_interference"]:
                hits[f"part/{k}"] = pr
        for k, s in fixed.items():
            pr = pair(shape, s)
            if not pr["clear_of_volume_interference"]:
                hits[f"ref/{k}"] = pr
        for e in env:
            if (e["ref"], e.get("sub_envelope")) in skip_env:
                continue
            target = e["shape"]
            if active and e["ref"] == active["ref"] and e.get("sub_envelope") == active["sub"]:
                target = target.cut(box(*active["bounds"]))
            pr = pair(shape, target)
            if not pr["clear_of_volume_interference"]:
                hits[f"env/{e['ref']}/{e['side']}/{e.get('sub_envelope', e.get('pad'))}"] = pr
        states[label] = {"collisions": hits, "clear": not hits}

    for t in (0.0, et.TRAVEL / 2, et.TRAVEL):
        check(f"trigger_{t:.2f}", parts["trigger"].translate(V(-t, 0, 0)), {"trigger"})
    # Right cap: tip preloads the D2FC plunger (sub-envelope 1) by design.
    active = {"ref": "SW2", "sub": 0, "bounds": [-31.45, -30.65, 4.77, 4.97, -3, -1]}
    for t in (0.0, 0.4, 0.8):
        check(f"right_cap_{t:.1f}", parts["right_cap"].translate(V(0, -t, 0)), {"right_cap"},
              skip_env={("SW2", 1)}, active=active)
    js = be.CFG["joystick"]
    jx, jz = js["shaft_xz"]
    pivot = V(jx, be.TOP + js["pivot_above_pcb_assumed"], jz)
    for elev in (0.0, 0.7):
        for press in (0.0, 0.9):
            for az in range(0, 360, 45):
                a = math.radians(az)
                shape = parts["joystick_cap"].translate(V(0, elev - press, 0))
                shape = shape.rotate(pivot, pivot + V(math.sin(a), 0, -math.cos(a)), js["stop_angle_deg"])
                check(f"joystick_e{elev}_p{press}_az{az}", shape, {"joystick_cap"}, skip_env={("SW1", 1)})
    return {"states": states, "state_count": len(states),
            "pass": all(s["clear"] for s in states.values()),
            "joystick_pivot_assumed_mm": [pivot.x, pivot.y, pivot.z]}


def joystick_stop_check(parts):
    """The left-shell cone must stop the cap stem at 20 deg, as the old ring did."""
    js = be.CFG["joystick"]
    jx, jz = js["shaft_xz"]
    pivot = V(jx, be.TOP + js["pivot_above_pcb_assumed"], jz)
    rows = {}
    for deg in (20.0, 20.5):
        worst = 0.0
        for az in range(0, 360, 30):
            a = math.radians(az)
            cap = parts["joystick_cap"].rotate(pivot, pivot + V(math.sin(a), 0, -math.cos(a)), deg)
            worst = max(worst, vof.volume_overlap(cap, parts["shell_left"]))
        rows[f"tilt_{deg}"] = round(worst, 4)
    return {"max_overlap_mm3_by_tilt": rows, "stops_at_20_deg": rows["tilt_20.0"] <= EPS < rows["tilt_20.5"]}


def contact_adjustment_check(parts, refs):
    sweep = et.screw_motion_envelope()
    hits = {}
    for k, s in parts.items():
        if k == "trigger":
            continue
        pr = pair(sweep, s)
        if not pr["clear_of_volume_interference"]:
            hits[f"part/{k}"] = pr
    for k, s in refs.items():
        if isinstance(s, cq.Shape):
            pr = pair(sweep, s)
            if not pr["clear_of_volume_interference"]:
                hits[f"ref/{k}"] = pr
    return {"collisions": hits, "pass": not hits, "contact_budget": et.contact_budget()}


def pcb_clamps(parts, refs):
    cfg = be.CARRIER
    top, back = be.TOP, be.BACK
    out = {}
    for hole in cfg["pcb"]["mount_holes"]:
        x, z = hole["xz"]
        clamp = parts["imu_cradle"] if hole["id"] == "H1" else parts["shell_left"]
        annulus = cyl_y(x, z, 2.5, back - .1, top + .1).cut(cyl_y(x, z, hole["d"] / 2 + .05, back - .2, top + .2))
        local = refs["pcb_board"].intersect(annulus)
        front = annulus.intersect(box(x - 3, x + 3, top, top + .1, z - 3, z + 3))
        rear = annulus.intersect(box(x - 3, x + 3, back - .1, back, z - 3, z + 3))
        out[hole["id"]] = {
            "rear_support": "shell_right", "front_clamp": "imu_cradle" if hole["id"] == "H1" else "shell_left",
            "rear_band_mm3": round(vof.volume_overlap(parts["shell_right"], rear), 4),
            "front_band_mm3": round(vof.volume_overlap(clamp, front), 4),
            "rear_gap_mm": round(parts["shell_right"].distance(local), 5),
            "front_gap_mm": round(clamp.distance(local), 5)}
        r = out[hole["id"]]
        r["clamped"] = r["rear_band_mm3"] > .01 and r["front_band_mm3"] > .01 and max(r["rear_gap_mm"], r["front_gap_mm"]) <= 1e-4
    out["pass"] = all(v["clamped"] for k, v in out.items() if k != "pass")
    return out


def fastener_checks(parts, refs, rows):
    res = vof._fasteners(parts, refs, rows)
    out = {}
    for spec in rows:
        r = res[spec["id"]]
        shapes = vof.fastener_shapes(spec)
        nut_part = spec.get("nut_part")
        seated = None
        if nut_part:
            # Each nut must sit inside a pocket of its part (no resin overlap).
            seated = all(clear(shapes[k], parts[nut_part]) for k in shapes if k.startswith("nut"))
        coll = {k: v for k, v in r["printed_part_collisions"].items()
                if not (spec["id"] == "trigger_contact" and k.endswith("/trigger") and k.startswith("tool"))}
        out[spec["id"]] = {"length": spec["length"], "fixed_reference_collisions": r["fixed_reference_collisions"],
                           "printed_part_collisions": coll, "nut_engagement": r["nut_engagement"],
                           "component_envelope_collisions": r["component_envelope_collisions"],
                           "nut_in_pocket_of": nut_part, "nut_clear_of_resin": seated}
        ok = (not r["fixed_reference_collisions"] and not coll
              and all(n["full_nut_engagement"] for n in r["nut_engagement"]) and seated is not False)
        out[spec["id"]]["pass"] = ok
    out["counts"] = {"M2x20": sum(1 for s in rows if s["length"] == 20),
                     "M2x10": sum(1 for s in rows if s["length"] == 10),
                     "M2_nuts": sum(len(s.get("nuts", [])) for s in rows)}
    out["pass"] = all(v["pass"] for k, v in out.items() if isinstance(v, dict) and "pass" in v)
    return out


def usb_checks(parts, refs):
    sm = E["supermini"]
    rx = sm["usb_receptacle"]
    yc = (rx["y"][0] + rx["y"][1]) / 2
    zc = (rx["z"][0] + rx["z"][1]) / 2
    mouth = rx["x"][1]
    out = {"receptacle_mouth_x": mouth, "front_outer_x": max(p[0] for p in be.SH["outline_full_xz_r"])}
    plugs = {"usb_c_spec_max_overmold_12.35x6.5": (12.35, 6.5), "slim_overmold_10.5x5.0": (10.5, 5.0)}
    fixed = {k: v for k, v in refs.items() if isinstance(v, cq.Shape) and k != "dev_board"}
    for name, (w, t) in plugs.items():
        over = box(mouth, mouth + 25, yc - t / 2, yc + t / 2, zc - w / 2, zc + w / 2)
        metal = box(mouth - 6.6, mouth, yc - 1.3, yc + 1.3, zc - 4.2, zc + 4.2)
        hits = {}
        for k, s in parts.items():
            for label, shape in (("overmold", over), ("metal", metal)):
                pr = pair(shape, s)
                if not pr["clear_of_volume_interference"]:
                    hits[f"{label}/part/{k}"] = pr
        for k, s in fixed.items():
            pr = pair(over, s)
            if not pr["clear_of_volume_interference"]:
                hits[f"overmold/ref/{k}"] = pr
        for e in refs["component_envelopes"]:
            if e["board_group"] == "dev_board":
                continue
            pr = pair(over, e["shape"])
            if not pr["clear_of_volume_interference"]:
                hits[f"overmold/env/{e['ref']}"] = pr
        out[name] = {"mated_collisions": hits, "plug_reaches_full_depth": not hits}
    out["pass"] = all(v["plug_reaches_full_depth"] for k, v in out.items() if isinstance(v, dict))
    out["note"] = ("Receptacle mouth uses the conservative 2.5 mm overhang (inner wall face); "
                   "the opening admits the USB-C maximum overmold, so recess depth does not limit mating.")
    return out


SEAT_STANDOFF = 0.05


def path_checks(parts, refs):
    """Straight assembly/service paths, proven with the continuous distance bound."""
    t0 = time.time()
    fixed_all = {k: v for k, v in refs.items() if isinstance(v, cq.Shape)}
    env_all = {f"env:{e['ref']}:{e['side']}:{i}": e["shape"] for i, e in enumerate(refs["component_envelopes"])}
    bolts, nuts = et.mount_hardware()
    holder_sub = compound([parts["switch_holder"], fixed_all["trigger_switch"], *bolts, *nuts])
    carrier = compound([fixed_all["pcb_board"]] + [e["shape"] for e in refs["component_envelopes"]
                                                  if e["board_group"] == "carrier"])
    # The right cap preloads the spring-loaded D2FC plunger by design (0.15 mm).
    carrier_no_plunger = compound([fixed_all["pcb_board"]] + [
        e["shape"] for e in refs["component_envelopes"]
        if e["board_group"] == "carrier" and not (e["ref"] == "SW2" and e.get("sub_envelope") == 1)])
    imu_sub = compound([parts["imu_cradle"], fixed_all["imu"]]
                       + [e["shape"] for e in refs["component_envelopes"] if e["board_group"] == "imu"])
    sm_sub = compound([fixed_all["dev_board"]]
                      + [e["shape"] for e in refs["component_envelopes"] if e["board_group"] == "dev_board"])
    trig_sub = compound([parts["trigger"], et.screw(0.0), et.nut("fixed"), et.nut("jam")])
    sw_env = [e["shape"] for e in refs["component_envelopes"] if e["board_group"] == "trigger_switch"]
    acc = accessory_shapes()
    switch_sub = compound([acc["battery_switch_body"], acc["battery_switch_actuator_full_travel"],
                           acc["battery_switch_pins"]])
    lift = 45.0
    paths = [
        ("battery_into_right_shell", fixed_all["battery"], {"shell_right": parts["shell_right"]}),
        ("supermini_into_nose_pocket", sm_sub, {"shell_right": parts["shell_right"], "battery": fixed_all["battery"]}),
        ("switch_holder_subassembly", holder_sub, {"shell_right": parts["shell_right"],
                                                   "battery": fixed_all["battery"]}),
        ("trigger_lift_out_for_calibration", trig_sub.translate(V(-0.15, 0, 0)),
         {"shell_right": parts["shell_right"], "holder": parts["switch_holder"],
          "switch": fixed_all["trigger_switch"], **{f"switch_env_{i}": s for i, s in enumerate(sw_env)},
          **{f"holder_hw_{i}": s for i, s in enumerate(bolts + nuts)}, "carrier": carrier, "imu": imu_sub}),
        ("carrier_onto_bosses", carrier, {"shell_right": parts["shell_right"], "battery": fixed_all["battery"],
                                          "supermini": sm_sub, "holder": holder_sub,
                                          "trigger": trig_sub}),
        ("imu_cradle_and_gy", imu_sub, {"shell_right": parts["shell_right"], "carrier": carrier,
                                        "supermini": sm_sub, "holder": holder_sub}),
        ("battery_switch_after_carrier", switch_sub,
         {"shell_right": parts["shell_right"], "carrier": carrier, "battery": fixed_all["battery"]}),
        ("left_shell_with_right_cap", compound([parts["shell_left"], parts["right_cap"]]),
         {"shell_right": parts["shell_right"], "battery": fixed_all["battery"], "supermini": sm_sub,
          "holder": holder_sub, "trigger": trig_sub, "carrier": carrier_no_plunger, "imu": imu_sub,
          "battery_switch": switch_sub}),
        ("joystick_cap_onto_shaft", parts["joystick_cap"],
         {"shell_left": parts["shell_left"], "shell_right": parts["shell_right"]}),
    ]
    out = {"method": f"Each part/subassembly translated along -Y from {lift} mm above its seat to "
                     f"{SEAT_STANDOFF} mm above it (continuous distance-bound proof); the seated pose itself "
                     "is covered by the static interference check, where landing faces touch at zero gap."}
    for name, moving, obstacles in paths:
        start = moving.translate(V(0, lift, 0))
        t1 = time.time()
        cert = vof.continuous_translation_clearance(start, obstacles, [0, -(lift - SEAT_STANDOFF), 0],
                                                    max_depth=12)
        out[name] = {"direction": "-Y (installed from the open +Y side)", "travel_mm": lift - SEAT_STANDOFF,
                     "entire_path_clear": cert["entire_linear_stroke_clear"],
                     "seconds": round(time.time() - t1, 1),
                     "obstacles": {k: {"proved": v["continuous_clearance_proved"],
                                       "failures": v["failures_or_unproved_intervals"][:3]}
                                   for k, v in cert["obstacles"].items()}}
        print(f"  path {name}: {out[name]['entire_path_clear']} ({out[name]['seconds']} s)", flush=True)
    out["pass"] = all(v["entire_path_clear"] for v in out.values() if isinstance(v, dict))
    out["seconds"] = round(time.time() - t0, 1)
    return out


def mass_table(parts):
    dens = E["materials_g_cm3"]
    vols = {k: s.Volume() for k, s in parts.items()}
    total = sum(vols.values())
    return {"parts_mm3": {k: round(v, 2) for k, v in vols.items()}, "total_mm3": round(total, 2),
            "mass_g": {k: round(total * d / 1000, 2) for k, d in dens.items()},
            "density_note": "Resin density is the print shop's number; weigh the first print to find it."}


def run(parts):
    t0 = time.time()
    refs = references()
    acc = accessory_shapes()
    rows = fasteners()
    report = {"scope": "EVT-1 light shell: nominal CAD vs nominal/conservative references",
              "parts": {k: {"valid": s.isValid(), "solids": len(s.Solids()), "bounds_mm": list(vof.bounds(s))}
                        for k, s in parts.items()}}
    steps = [("static", lambda: static_checks(parts, refs)),
             ("accessories", lambda: accessory_checks(parts, refs, acc)),
             ("motion", lambda: motion_checks(parts, refs)),
             ("joystick_cone_stop", lambda: joystick_stop_check(parts)),
             ("trigger_contact_adjust_and_stroke", lambda: contact_adjustment_check(parts, refs)),
             ("pcb_clamps", lambda: pcb_clamps(parts, refs)),
             ("fasteners", lambda: fastener_checks(parts, refs, rows)),
             ("usb_c_access", lambda: usb_checks(parts, refs)),
             ("trigger_internal", lambda: et.validate_internal()),
             ("assembly_paths", lambda: path_checks(parts, refs)),
             ("mass", lambda: mass_table(parts))]
    for name, fn in steps:
        t1 = time.time()
        report[name] = fn()
        print(f"{name}: pass={report[name].get('pass', '-')} ({time.time() - t1:.1f} s)", flush=True)
    flags = {k: report[k]["pass"] for k in ("static", "accessories", "motion", "trigger_contact_adjust_and_stroke",
                                            "pcb_clamps", "fasteners", "usb_c_access", "trigger_internal",
                                            "assembly_paths")}
    flags["joystick_cone_stop"] = report["joystick_cone_stop"]["stops_at_20_deg"]
    flags["all_parts_single_valid_solid"] = all(v["valid"] and v["solids"] == 1 for v in report["parts"].values())
    report["pass_flags"] = flags
    report["all_pass"] = all(flags.values())
    report["not_verified"] = [
        "Resin strength, creep and drop; printed tolerances and nut-pocket fit",
        "Actual SS-01GL operating point (calibrated with the 0.8/1.0/1.2 gauges)",
        "Module dimensions of the purchased SuperMini/GY/battery/slide switch",
        "BLE range with the hand on the grip; charge current and TP4054/battery temperature with BOOST",
        "Touch false-trigger margin with the palm on the closed grip",
        "Flexible wire routing beyond the declared corridors"]
    report["runtime_s"] = round(time.time() - t0, 1)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-generated", action="store_true")
    ap.add_argument("--output", default=str(OUT / "assembly-check.json"))
    args = ap.parse_args()
    if args.from_generated:
        names = json.loads((OUT / "part-volumes.json").read_text(encoding="utf-8"))["parts"]
        parts = {k: cq.importers.importStep(str(OUT / f"{k}.step")).val() for k in names}
    else:
        _, parts = be.build_parts()
    report = run(parts)
    if args.from_generated:
        report["parts_source_sha256"] = {f"{k}.step": hashlib.sha256((OUT / f"{k}.step").read_bytes()).hexdigest()
                                         for k in parts}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n",
                                 encoding="utf-8")
    print(json.dumps({"all_pass": report["all_pass"], **report["pass_flags"]}, indent=1))
    if not report["all_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
