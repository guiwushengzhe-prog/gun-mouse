"""SS-01GL13 solder-lug switch in the original EVT-A contact coordinates.

The original daughter board is replaced by a printed card and two M2x20 screws.
The switch body/lever are nominal datasheet envelopes, not measured STEP data.
The original -15.5 contact axis and 4.1 mm trigger motion are retained.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cadquery as cq

from trigger_parts import box, single, build_trigger, screw_motion_envelope

V = cq.Vector
HERE = Path(__file__).resolve().parent
SWITCH_BOTTOM_X = -19.0
# This datum reproduces the original three solder-lug centres -1.021,
# -9.819, -17.119 from SW4's repository footprint at ab=[0,-9.07].
BODY_LEFT_Z = 0.579
HOLES = [(SWITCH_BOTTOM_X + 2.9, BODY_LEFT_Z-d) for d in (5.1,14.6)]
CARD_X = (-20.6,-19.0)
CARD_Y = (-7.0,7.0)
CARD_Z = (-21.2,2.5)
BOSS_Y = (-6.4,6.4)
NUT_Y = (-6.4,-4.8)
SCREW_LENGTH = 20.0
HEAD_D, HEAD_K = 4.0,2.1


def cyl_y(x,z,r,y0,y1):
    return cq.Solid.makeCylinder(r,y1-y0,V(x,y0,z),V(0,1,0))


def hex_y(x,z,af,y0,y1,corner_deg=0.0):
    r=af/math.sqrt(3)
    pts=[V(x+r*math.cos(math.radians(corner_deg+60*i)),y0,
           z+r*math.sin(math.radians(corner_deg+60*i))) for i in range(6)]
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(cq.Wire.makePolygon(pts,close=True)),
                                 V(0,y1-y0,0))


def switch_rigid():
    """Nominal body, true mounting holes and solder lugs from Omron drawing."""
    xb,zl=SWITCH_BOTTOM_X,BODY_LEFT_Z
    shape=box(xb,xb+9.5,-3.2,3.2,zl-19.8,zl)
    shape=shape.fuse(box(xb+9.5,xb+10.2,-3.2,3.2,zl-8,zl))
    for (x,z),d in zip(HOLES,(2.5,2.35)):
        shape=shape.cut(cyl_y(x,z,d/2,-3.3,3.3))
    for off in (1.6,10.4,17.7):
        z=zl-off
        shape=shape.fuse(box(xb-3.5,xb+.01,-1.6,1.6,z-.25,z+.25))
    return single(shape,"SS-01GL13 nominal rigid body and solder lugs")


def switch_body_tolerance_envelope():
    """Static +/-0.4 envelope excluding the flexible GL13 contact lever."""
    return box(-19.0,-8.4,-3.6,3.6,BODY_LEFT_Z-20.2,BODY_LEFT_Z+.4)


def build_holder():
    """Open bracket; terminal soldering is performed before inserting the card."""
    h=box(*CARD_X,*CARD_Y,*CARD_Z)
    # Cover the explicit +/-0.4 body envelope plus 0.2 mm on each side.
    # Location is provided by the screws and bottom, not cavity friction.
    for y0,y1 in ((-5.4,-3.8),(3.8,5.4)):
        # Only reach the two screw bosses; an unnecessary tall wall around the
        # top of the switch would add ~0.35 cm3 without locating another datum.
        h=h.fuse(box(-20.6,-13.1,y0,y1,*CARD_Z))
    # End fences prevent rotation around the two clearance holes.
    h=h.fuse(box(-20.6,-17.8,-5.4,5.4,-21.2,BODY_LEFT_Z-19.8-.4-.2))
    h=h.fuse(box(-20.6,-17.8,-5.4,5.4,BODY_LEFT_Z+.4+.2,2.5))
    for x,z in HOLES:
        h=h.fuse(cyl_y(x,z,3.0,-6.4,-3.8),cyl_y(x,z,3.0,3.8,6.4))
        h=h.cut(cyl_y(x,z,1.15,-6.6,6.6))
        # The nut enters from -Y and is restrained by its 4.3 mm AF pocket.
        h=h.cut(hex_y(x,z,4.3,-6.5,-4.7))
    # One continuous 4.6 mm wide opening for all three solder lugs. It extends
    # to the lower edge so the two insulated leads can leave without threading
    # through a closed hole. Both outer card rails remain 4.7 mm wide.
    h=h.cut(box(-21.0,-18.95,-2.3,2.3,-21.3,1.0))
    return single(h,"SS-01GL13 open solder-wire holder")


def mount_hardware():
    """Socket recess and nut bore are explicit; shaft thread is an envelope."""
    bolts,nuts=[],[]
    for x,z in HOLES:
        seat=BOSS_Y[1]
        head=cyl_y(x,z,HEAD_D/2,seat,seat+HEAD_K)
        socket=hex_y(x,z,1.5,seat+HEAD_K-1.0,seat+HEAD_K+.01,90)
        shaft=cyl_y(x,z,1.0,seat-SCREW_LENGTH,seat)
        bolts.append(single(head.cut(socket).fuse(shaft),"M2x20 switch screw"))
        n=hex_y(x,z,4.0,*NUT_Y)
        nuts.append(single(n.cut(cyl_y(x,z,1.0,-6.5,-4.7)),"M2 switch mounting nut"))
    return bolts,nuts


def mount_spacers():
    """Nominal 6.4 mm switch: two 0.3 mm M2 flat washers on each side/hole.

    For a wider actual switch reduce washer count. Never bend the resin bracket
    to force a too-thick washer stack into the measured cavity. These nominal
    metal rings are not printed parts and are excluded from resin mass.
    """
    spacers=[]
    for x,z in HOLES:
        for y0,y1 in ((-3.8,-3.2),(3.2,3.8)):
            spacer=cyl_y(x,z,2.5,y0,y1).cut(cyl_y(x,z,1.1,y0-.01,y1+.01))
            spacers.append(single(spacer,"nominal two M2x0.3 washer stack"))
    return spacers


def terminal_wire_envelope():
    """Reserve solder/lead route on the +Y side of the switch terminals.

    The positive-Y route stays clear of the carrier top at Y=-1.63 and admits
    real lug length/solder thickness without imposing an impractically narrow
    X-only constraint. This is a corridor, not a measured flexible wire solid.
    """
    return box(-24.2,-21.0,.3,2.3,-21.2,-.5)


def interface_metadata():
    return {
        "switch":"Omron SS-01GL13 solder-lug version, not SS-01GL or GL13-2 PCB pins",
        "switch_source":"https://www.fa.omron.co.jp/product/item/SS-01GL13/",
        "datasheet":"research/Omron-SS-datasheet.pdf",
        "coordinate_system":"Original assembled XYZ, mm",
        "switch_bottom_x":SWITCH_BOTTOM_X,"switch_body_left_z":BODY_LEFT_Z,
        "mount_holes_xz":HOLES,"mount_hole_d_mm":[2.5,2.35],
        "contact_axis_yz":[0,-15.5],"trigger_travel_mm":4.1,
        "card_bounds":{"x":CARD_X,"y":CARD_Y,"z":CARD_Z},
        "frame_slot":{"x":[-20.75,-18.85],"y_edges":[-7,7],"z":[-21.45,2.75]},
        "insertion":"Through the open +Y side; retain -Y end stop and fit removable +Y gate",
        "slot_retention":"Card X and Z movement is blocked by slot lips, +/-Y by end stop and gate; do not rely on friction",
        "holder_bounds":[-20.6,-13.1,-7,7,-21.2,2.5],
        "hardware":{"M2x10":0,"M2x20":2,"M2_hex_nuts_AF4_K1.6":2},
        "assembly_shims":{"M2_flat_washers_nominal":8,"washer_id_od_k_mm":[2.2,5.0,.3],
                          "position":"Between switch side face and bracket at each mounting hole; nominal two washers per side/hole",
                          "count_boundary":"Fit measured switch:0..2 nominal0.3mm washers per side/hole plus0.1/0.2mm thin shims if needed; same total stack at both holes on a side. Switch must not wobble after light tightening. Do not force bracket walls inward to fill nominal1.2mm total gap"},
        "hardware_seats":[{"id":f"trigger_switch_{i+1}","seat":[x,6.4,z],
                           "axis":[0,-1,0],"length":20,"head_d":4,"head_k":2.1,
                           "nut_near_from_seat":11.2,"nut_far_from_seat":12.8,
                           "screw_tip_y":-13.6,"projection_beyond_nut_mm":7.2}
                          for i,(x,z) in enumerate(HOLES)],
        "screw_tip_boundary":"M2x20 projects to Y=-13.6; frame must shield tips from fingers and reserve full shaft corridor",
        "head_tool_boundary":"Tighten both mounting screws with the holder outside the frame, then insert complete assembly",
        "wire_reserved_bounds":[-24.2,-21.0,.3,2.3,-21.2,-.5],
        "wiring":"Solder COM to GND and NO to trigger input; NC unconnected. Identify terminals by moulded COM/NO/NC and continuity, not wire colour",
        "soldering":"Solder insulated leads on the +Y side of terminal lugs outside bracket first, fit heatshrink, retain whole lead route within Y>=0.3 and X>=-24.2 until it leaves the holder; do not bend the lug root",
        "fit_boundary":"Side cavity +/-3.8 covers labelled +/-3.6 body envelope plus0.2 each side; end fences also clear +/-0.4 nominal body envelope. Resin shrinkage and card sliding fit require a first-sample check",
        "print":"Card plane parallel to print bed, tilted/raised for resin drainage; support non-contact card backside. Keep switch seat, nut holes and card slide edges free of support scars",
        "parking_anchor_candidates":[[-15.0,5.4,-20.5],[-15.0,-5.4,-20.5]],
        "parking_anchor_note":"External lower side-wall faces, away from screw bores and card contact. Do not bridge terminal window, screw bores or slot contact faces",
    }


def validate_internal():
    holder=build_holder();rigid=switch_rigid();bolts,nuts=mount_hardware()
    sweep=screw_motion_envelope();trigger=build_trigger()
    checks={"holder_vs_switch_rigid":holder.intersect(rigid).Volume(),
            "holder_vs_contact_screw_sweep":holder.intersect(sweep).Volume(),
            "switch_rigid_vs_contact_screw_sweep":rigid.intersect(sweep).Volume(),
            "reserved_wire_vs_holder":terminal_wire_envelope().intersect(holder).Volume()}
    # The outer tolerance body has no holes; remove the intentional screw-hole
    # cylinders only when comparing it to the bracket's outer cavity.
    worst=switch_body_tolerance_envelope()
    checks["holder_vs_switch_body_tolerance_envelope"]=holder.intersect(worst).Volume()
    for i,(bolt,nut) in enumerate(zip(bolts,nuts)):
        checks[f"holder_vs_mount_bolt_{i+1}"]=holder.intersect(bolt).Volume()
        checks[f"holder_vs_mount_nut_{i+1}"]=holder.intersect(nut).Volume()
        checks[f"switch_rigid_vs_mount_bolt_{i+1}"]=rigid.intersect(bolt).Volume()
        checks[f"contact_screw_sweep_vs_mount_bolt_{i+1}"]=sweep.intersect(bolt).Volume()
    for i,spacer in enumerate(mount_spacers()):
        checks[f"nominal_washer_stack_{i+1}_vs_holder"]=holder.intersect(spacer).Volume()
        checks[f"nominal_washer_stack_{i+1}_vs_switch"]=rigid.intersect(spacer).Volume()
    # Mid-pose distance bound proves clearance through the entire translation.
    mid=trigger.translate(V(-2.05,0,0))
    fixed={"holder":holder,"switch_rigid":rigid,
           **{f"mount_bolt_{i+1}":b for i,b in enumerate(bolts)}}
    distances={key:mid.distance(shape) for key,shape in fixed.items()}
    if max(checks.values())>.001:
        raise ValueError("Holder interference: "+json.dumps(checks))
    if min(distances.values())<=2.05:
        raise ValueError("Cannot prove full-stroke trigger clearance: "+json.dumps(distances))
    return {"valid":holder.isValid(),"solids":len(holder.Solids()),
            "holder_volume_mm3":holder.Volume(),"holder_mass_g_at_1.35":holder.Volume()*1.35/1000,
            "holder_mass_g_at_1.45":holder.Volume()*1.45/1000,
            "overlap_mm3":checks,"trigger_midpoint_distances_mm":distances,
            "trigger_motion_proof":"minimum midpoint distance > 4.1/2; translation cannot intersect any fixed solid",
            "interface":interface_metadata()}


if __name__=="__main__":
    report=validate_internal()
    (HERE/"trigger-holder-validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
