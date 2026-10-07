"""Build a SuperMini hand-soldered open frame with M2x10/M2x20 socket screws.

Assembly-coordinate solids are independent of print parking/packing transforms.
Run with Python + CadQuery; no EDA desktop and no missing skeleton STL needed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
sys.path.insert(0, str(HERE))
from build_shell import box, cyl_x, cyl_y, cone_y, outline_wire, build_knob
from trigger_parts import build_trigger, build_touch_cover, interface_metadata
from trigger_holder import build_holder, interface_metadata as holder_metadata

V = cq.Vector
CFG = json.loads((ROOT / "config" / "pcb-shell-v1.json").read_text(encoding="utf-8"))
# Controls retain the proven original assembly datums. Only the hand-soldered
# carrier shape and mounting pattern change; no old EVT-A electronics are used.
CFG = copy.deepcopy(CFG)
CARRIER = json.loads((HERE / "carrier-config.json").read_text(encoding="utf-8"))
CFG["board"]["mount_holes"] = CARRIER["pcb"]["mount_holes"]
CFG["board"]["thickness"] = CARRIER["pcb"]["thickness"]
CFG["board"]["top_face_y"] = CARRIER["pcb"]["top_face_y"]
OPT = json.loads((HERE / "open-frame-config.json").read_text(encoding="utf-8"))
OUT = HERE / "generated"


def fused(shapes):
    shapes = list(shapes)
    return shapes[0].fuse(*shapes[1:]).clean() if len(shapes) > 1 else shapes[0]


def single(shape, label):
    s = shape.clean()
    if not s.isValid() or len(s.Solids()) != 1:
        for i, item in enumerate(s.Solids()):
            bb=item.BoundingBox()
            print(label,i,item.Volume(),[bb.xmin,bb.xmax,bb.ymin,bb.ymax,bb.zmin,bb.zmax],flush=True)
        OUT.mkdir(parents=True,exist_ok=True)
        cq.exporters.export(s,str(OUT/(label.replace(" ","_")+"-debug.step")))
        raise ValueError(f"{label}: invalid/disconnected ({len(s.Solids())} solids)")
    return s.Solids()[0]


def beam(a, b, width, y0, y1, soften=False):
    dx, dz = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dz)
    if length < 1e-6:
        return cyl_y(*a, width / 2, y0, y1)
    nx, nz = -dz / length * width / 2, dx / length * width / 2
    pts = [(a[0]+nx, a[1]+nz), (b[0]+nx, b[1]+nz),
           (b[0]-nx, b[1]-nz), (a[0]-nx, a[1]-nz)]
    w = cq.Wire.makePolygon([V(x, y0, z) for x, z in pts], close=True)
    bar = cq.Solid.extrudeLinear(cq.Face.makeFromWires(w), V(0, y1-y0, 0))
    s = fused([bar, cyl_y(*a, width/2, y0, y1), cyl_y(*b, width/2, y0, y1)])
    if soften:
        s = cq.Workplane().add(s).faces(">Y or <Y").edges().fillet(.45).val()
    return s


def chain(points, width, y0, y1, soften=False):
    return fused(beam(a, b, width, y0, y1, soften) for a, b in zip(points, points[1:]))


def hex_y(x, z, af, y0, y1):
    r = af / math.sqrt(3)
    wire = cq.Wire.makePolygon([V(x+r*math.cos(math.radians(30+60*i)), y0,
                                 z+r*math.sin(math.radians(30+60*i))) for i in range(6)], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), V(0, y1-y0, 0))


def cyl_z(x,y,r,z0,z1):
    return cq.Solid.makeCylinder(r,z1-z0,V(x,y,z0),V(0,0,1))


def hex_z(x,y,af,z0,z1):
    r=af/math.sqrt(3)
    w=cq.Wire.makePolygon([V(x+r*math.cos(math.radians(30+60*i)),
                           y+r*math.sin(math.radians(30+60*i)),z0)
                          for i in range(6)],close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(w),V(0,0,z1-z0))


def nut_pocket_y(shape, x, z, y0, y1):
    pocket = hex_y(x, z, 4.3, y0, y1)
    # A side-loading slot; flats guide the nut, eliminating resin threading.
    entry = box(x, x+4.5, y0, y1, z-2.15, z+2.15)
    return shape.cut(pocket).cut(entry)


def mounting_post(x,z,y0,y1,nut_y):
    # Full nut carrier is local; the lightly loaded connecting stem is hollow.
    s=fused([cyl_y(x,z,1.9,y0,y1),
             cyl_y(x,z,2.8,nut_y[0]-.5,min(nut_y[1]+.5,y1)),
             cyl_y(x,z,2.8,y1-1.2,y1)])
    s=s.cut(cyl_y(x,z,1.2,y0-.1,y1+.1))
    return nut_pocket_y(s,x,z,*nut_y)


def build_supermini_clamp():
    # Thin retainers contact only the unsoldered 0.6mm long board edges.
    pieces=[box(-2.0,2.0,-8,-6.1,13.1,14.6),
            box(1.0,5.0,-8,-6.1,31.4,32.9)]
    for x,z in OPT["module_mounts"]["supermini"]["centres_xz"]:
        pieces.append(cyl_y(x,z,2.8,-8,-6.1))
    # Bridge lies outside the PCB, component and rear USB connection envelopes.
    pieces.append(box(12.4,14,-8,-6.1,11.4,34.6))
    for x,z in OPT["module_mounts"]["supermini"]["centres_xz"]:
        pieces.append(box(x,13.2,-8,-6.1,z-.8,z+.8))
    s=fused(pieces)
    for x,z in OPT["module_mounts"]["supermini"]["centres_xz"]:
        s=s.cut(cyl_y(x,z,1.2,-8.1,-6.0))
    for z0,z1 in ((14,14.7),(31.3,32)):
        s=s.fuse(box(11.5,12.6,-9.6,-6.1,z0,z1))
    for z0,z1 in ((13.3,14),(32,32.7)):
        s=s.fuse(box(11.3,12.6,-9.6,-7.8,z0,z1))
    return single(s,"SuperMini clamp")


def build_imu_clamp():
    pieces=[beam((-24.6,43.1),(-22.1,38.1),2.0,9,10.6),
            beam((15,8),(-1.4,20.1),2.0,9,10.6),
            box(-22.7,-21.4,9,10.6,20.0,38.5),
            box(-2.0,-.7,9,10.6,19.5,38.0),
            beam((-22,38.4),(-1.4,38.4),1.8,9,10.6)]
    for x,z in OPT["module_mounts"]["imu"]["centres_xz"]:
        pieces.append(cyl_y(x,z,2.8,9,10.6))
    s=fused(pieces)
    for x,z in OPT["module_mounts"]["imu"]["centres_xz"]:
        s=s.cut(cyl_y(x,z,1.2,8.9,10.7))
    return single(s,"IMU clamp")


def build_imu_cradle():
    # Separate cradle installs after the carrier, leaving its +Y path open.
    pieces=[beam((-24.6,43.1),(-22,37.9),2.2,5.6,7.8),
            beam((15,8),(-1.4,20.1),2.2,5.6,7.8),
            box(-23.1,-21.8,5.6,7.8,20.0,38.6),
            box(-1.6,-.3,5.6,7.8,19.4,38.6),
            beam((-22.6,38.6),(-1.0,38.6),2.0,5.6,7.8)]
    for x,z in OPT["module_mounts"]["imu"]["centres_xz"]:
        pieces.append(cyl_y(x,z,2.8,5.6,7.8))
    for x0,x1 in ((-22,-21.3),(-2.1,-1.4)):
        for z0,z1 in ((19.4,20.1),(37.9,38.6)):
            pieces.append(box(x0,x1,7.0,9.0,z0,z1))
    s=fused(pieces)
    for x,z in OPT["module_mounts"]["imu"]["centres_xz"]:
        s=s.cut(cyl_y(x,z,1.2,5.5,9.1))
    return single(s,"IMU cradle")


def clamp(x, z):
    top = CFG["board"]["top_face_y"]
    c = cyl_y(x, z, 3.3, top, OPT["pcb_clamp_top_y"])
    c = c.cut(cyl_y(x, z, 1.2, top-.1, 20.1))
    c = nut_pocket_y(c, x, z, *OPT["nut_pocket"]["y"])
    if (x,z)==(-27,-27):
        # C_RAIL's 6x2mm body ends at X=-29. Relieve the left cap edge;
        # form its leads away by >=0.3mm for real nut/component clearance.
        c=c.cut(box(x-4,-28.8,top-.1,OPT["pcb_clamp_top_y"]+.1,z-4,z+4))
    return single(c, "PCB clamp")


def build_right_cap():
    # Reduced mass face/open flange, preserving original EVT-A tip/lip datum.
    x, z = CFG["right_button"]["xz"]
    top = CFG["board"]["top_face_y"]
    body = box(x-7, x+7, 16.0, 20.8, z-4.5, z+4.5)
    flange = box(x-8.4, x+8.4, 16.0, 17.6, z-5.9, z+5.9)
    lip = box(x-7.8, x+7.8, 20.8, 21.95, z-5.3, z+5.3)
    lip = cq.Workplane().add(lip).faces(">Y").edges().fillet(.6).val()
    stem = box(x-1.9, x+3.1, top+8.30, 16.05, z-2, z+2)
    tip=box(x+1.55,x+2.35,top+7.30,top+8.35,z-1.0,z+1.0)
    s = fused([body, flange, lip, stem,tip])
    # Keep the face, stem and outer guide sleeve. Open two interior pockets.
    for a,b in ((x-5.5,x-1.9), (x+3.1,x+5.5)):
        s = s.cut(box(a,b,15.9,20.0,z-3.0,z+3.0))
    for a,b in ((z-3.4,z-2.0),(z+2.0,z+3.4)):
        s=s.cut(box(x-5.5,x+5.5,15.9,20.0,a,b))
    return single(s, "right cap")


def build_light_knob():
    knob_cfg=copy.deepcopy(CFG)
    # Blind-hole roof matches the shortest specified shaft. This keeps the
    # stem at Y>=13.75, allowing the specified 0.9mm maximum centre press
    # together with 20deg tilt. Actual shortest-shaft engagement is 3.57mm.
    knob_cfg["joystick"]["shaft_engage"]=3.37
    s=build_knob(knob_cfg,tip_above_pcb=18.75)
    x,z=CFG["joystick"]["shaft_xz"]
    # Radial under-cap pockets retain the shaft tube and 1.2mm face skin.
    for angle in (0,90,180,270):
        pocket=box(x+4.1,x+6.9,24.9,26.35,z-1.5,z+1.5)
        pocket=pocket.rotate((x,0,z),(x,1,z),angle)
        s=s.cut(pocket)
    return single(s,"joystick cap")


def build_control_bridge():
    pieces = [clamp(-56,36), clamp(-51,-4)]
    for x,z in ((-56,36),(-51,-4)):
        p = cyl_y(x,z,2.2,2.6,20.0).cut(cyl_y(x,z,1.2,2.5,20.1))
        pieces.append(p)
    pieces.extend([beam((-56,36),(-51,-4),3.0,17.6,20.0),
                   beam((-56,36),(-43,28),3.0,17.6,20.0),
                   beam((-51,-4),(-42.1,-2),3.0,17.6,20.0)])
    x,z = CFG["right_button"]["xz"]
    collar = box(x-9.3,x+9.3,17.6,20,z-6.8,z+6.8).cut(
        box(x-7.3,x+7.3,17.5,20.1,z-4.8,z+4.8))
    # The flanged cap slides in from +X. A removable M2x20 vertical keeper
    # closes this U-guide after insertion; a closed collar cannot be assembled.
    collar=collar.cut(box(x+7.29,x+9.4,17.5,20.1,z-6.9,z+6.1))
    keeper_x,keeper_y=x+8.1,18.8
    keeper=fused([cyl_z(keeper_x,keeper_y,2.8,z+6.0,z+10.5),
                  cyl_z(keeper_x,keeper_y,3.2,z+8.5,z+10.5),
                  cyl_z(keeper_x,keeper_y,3.2,z-9.4,z-6.6)])
    keeper=keeper.cut(cyl_z(keeper_x,keeper_y,1.2,z-9.5,z+10.6))
    keeper=keeper.cut(hex_z(keeper_x,keeper_y,4.3,z+8.5,z+10.1))
    keeper=keeper.cut(box(keeper_x-2.15,keeper_x+2.15,keeper_y,keeper_y+4,
                          z+8.5,z+10.1))
    collar=collar.fuse(keeper).cut(cyl_z(keeper_x,keeper_y,1.2,z-9.5,z+10.6))
    pieces.append(collar)
    js = CFG["joystick"]
    x,z = js["shaft_xz"]
    pivot = CFG["board"]["top_face_y"]+js["pivot_above_pcb_assumed"]
    tan = math.tan(math.radians(js["stop_angle_deg"]))
    stem_r = js["knob"]["stem_d"]/2/math.cos(math.radians(20))
    rin = (17.6-pivot)*tan+stem_r
    rout = (20-pivot)*tan+stem_r
    ring = cyl_y(x,z,10.8,17.6,20.0).cut(cone_y(x,z,rin,rout+.02,17.59,20.01))
    pieces.append(ring)
    s=fused(pieces)
    for x,z in ((-56,36),(-51,-4)):
        s=s.cut(cyl_y(x,z,1.2,-1.8,20.1))
    return single(s, "control bridge")


def build_frame():
    y0,y1 = OPT["right_plane_y"]
    w,gw = OPT["beam_width_mm"],OPT["grip_beam_width_mm"]
    outline = [(-62,5),(-64,36),(-54,43),(10,43),(16,36),(16,13),
               (10,10),(8,-4),(2,-32),(-8,-85),(-19,-96),(-49,-96),
               (-61,-85),(-55,-17),(-62,5)]
    pieces = [chain(outline,w,y0,y1,True)]
    # Keep the +Y trigger/gate entry open above the actual grip area.
    grip = [(1.5,-35),(-8,-85),(-19,-96),(-49,-96),(-61,-85),(-64,-42),(-64,5)]
    ly0,ly1 = OPT["left_grip_plane_y"]
    pieces.append(chain(grip,gw,ly0,ly1,True))
    # Six transverse ties keep the rear grip outside the carrier insertion path.
    for x,z in ((1.5,-35),(-62,5),(-.6,-46),(-63.5,-49),(-18,-94),(-50,-94)):
        pieces.append(cyl_y(x,z,1.6,y1-.3,ly1))
    pieces.append(beam((-63.5,-49),(-57.8,-49),3.0,y0,y1))
    mounts = CFG["board"]["mount_holes"]
    support_paths = {"H1":[(-12,36),(10,43)], "H2":[(-56,36),(-54,43)],
                     "H3":[(-51,-4),(-62,5)], "H4":[(-27,-27),(-55,-17)]}
    back = CFG["board"]["top_face_y"]-CFG["board"]["thickness"]
    for h in mounts:
        x,z = h["xz"]
        pieces.append(chain(support_paths[h["id"]],w,y0,y1))
        pieces.append(cyl_y(x,z,OPT["pcb_boss_radius_mm"],y0,y1))
        # Narrow post above the head seat clears the battery by >=0.2mm at H3.
        pieces.append(cyl_y(x,z,2.6,y1-.1,back))
    # Four spaced mounting holes support the 1.6mm FR4 carrier; no extra
    # resin contacts are placed under through-hole solder joints.
    # Battery pocket: increased lateral clearance, three thin floor strips.
    bt = OPT["battery_pocket"]
    px0,px1 = bt["x"]; pz0,pz1=bt["z"]; by=bt["back_y"]
    for z in (-74,-58,-42):
        pieces.append(box(px0,px1,by-1.2,by,z-1.5,z+1.5))
        for x in (px0,px1):
            pieces.append(cyl_y(x,z,1.6,y1-.1,by))
    # Vertical edge beams connect the battery supports to frame and bosses.
    pieces.extend([beam((px0,-84),(px0,-32),1.8,y0,y1),
                   beam((px1,-84),(px1,-32),1.8,y0,y1),
                   beam((px0,-84),(-49.5,-88),3,y0,y1),
                   beam((px1,-84),(-17,-85),3,y0,y1),
                   beam((px0,-32),(-55,-17),3,y0,y1),
                   beam((px1,-32),(-12,-32),3,y0,y1)])
    for x in (px0-.8,px1+.8):
        for z in (pz0+2.5,pz1-2.5):
            pieces.append(box(x-.8,x+.8,y1,back-1.2,z-2.5,z+2.5))
    for z in (pz0-.7,pz1+.7):
        pieces.append(box(px0-.5,px1+.5,by-1.4,by+1.2,z-.7,z+.7))
    # Original trigger slide datums, clipped to original front silhouette.
    face = cq.Face.makeFromWires(outline_wire(CFG["shell"]["outline_xz"],-30))
    original_outline = cq.Solid.extrudeLinear(face,V(0,60,0))
    bottom = box(-5.6,14,-7.0,5.35,-30,-28.35).intersect(original_outline)
    upper = box(0,14,-7.0,5.35,-11.65,-9.8).intersect(original_outline)
    side = box(-8.6,14,-7.0,-5.35,-31.0,-10.6).intersect(original_outline)
    stop = box(-8.6,-4.6,-5.35,5.35,-28.5,-21.2)
    stop=stop.cut(box(-8.7,-6.2,-3.8,3.8,-27.4,-22.3))
    pieces.extend([bottom,upper,side,stop,cyl_x(0,-24.5,1.4,-4.61,-3.3)])
    pieces.append(box(-11,-7,-7,5.35,-32,-30))
    for z in (7.0,-33.0):
        pieces.append(box(-12.4,-10.0,y1,-5.35,z-3,z+3))
        pieces.append(fused([cyl_y(-9.6,z,2.2,-5.5,5.35),
                             cyl_y(-9.6,z,3,-.9,1.4),
                             cyl_y(-9.6,z,3,4.35,5.35)]))
    pieces.extend([beam((-12,-8),(-12,36),3.4,y0,y1),
                   beam((-12,-33),(2,-32),3.4,y0,y1)])
    # GL13 hand-wired holder enters along -Y from the open +Y side. Only the
    # far-side groove is fixed; its other groove belongs to the removable gate.
    xt=CFG["board"]["daughter"]["assembled_top_face_x"]
    xb=xt-CFG["board"]["thickness"]
    rib=box(xb-1.4,xt+1.6,-8.6,-5.6,-22.5,3.75)
    rib=rib.cut(box(xb-.15,xt+.15,-7.3,-5.5,-21.45,2.75))
    pieces.append(rib)
    pieces.append(box(xb-1.4,xt+1.6,y1,-8.5,-22.5,-21.45))
    pieces.append(beam((-20,-22),(-12,-33),3,y0,y1))
    # SuperMini sits on clear board-edge ledges; its underside BAT wires stay
    # unobstructed while the board is inserted laterally from +X.
    for x,z in OPT["module_mounts"]["supermini"]["centres_xz"]:
        pieces.append(mounting_post(x,z,y1-.1,-8,OPT["module_mounts"]["supermini"]["nut_y"]))
        pieces.append(beam((x,z),(10,10) if z<20 else (10,43),2.6,y0,y1))
    # GY module support edges sit above the main board; posts cross Y only
    # outside its outline, and outside the SuperMini board and antenna.
    for x,z in OPT["module_mounts"]["imu"]["centres_xz"]:
        pieces.append(mounting_post(x,z,y1-.1,5.6,OPT["module_mounts"]["imu"]["nut_y"]))
    pieces.append(beam((15,8),(10,10),3.0,y0,y1))
    s = fused(pieces)
    # Four M2x20 seats and bores: all machine screws with side-loaded nuts.
    for h in mounts:
        x,z=h["xz"]
        s=s.cut(cyl_y(x,z,1.2,y0-.1,back+.1))
        s=s.cut(cyl_y(x,z,2.2,y0-.1,OPT["pcb_bolt_seat_y"]))
    for z in (7.0,-33.0):
        s=s.cut(cyl_y(-9.6,z,1.2,-5.6,5.5))
        s=nut_pocket_y(s,-9.6,z,-.7,1.2)
    # Switch-hole bosses and the long M2x20 tips need clear guide-side windows.
    for z in (-4.521,-14.021):
        s=s.cut(cyl_y(-16.1,z,3.3,-13.7,8.6))
    s=s.cut(box(-12,11.5,-9.6,-7.9,14,32))
    for group in ("supermini","imu"):
        for x,z in OPT["module_mounts"][group]["centres_xz"]:
            s=s.cut(cyl_y(x,z,1.2,y0-.1,10.7))
    # Positive corner stops retain modules when USB cables pull on them.
    # They touch board edges only, and leave the USB and RF antenna open.
    for x0,x1 in ((-12.7,-12),):
        for z0,z1 in ((14,14.7),(31.3,32)):
            s=s.fuse(box(x0,x1,-10.7,-7.8,z0,z1))
            s=s.fuse(box(x0-.2,x1+.2,-10.7,-9.6,z0-.3,z1+.3))
    # Narrow insulated feet attach the corner stops to the central seat.
    for z0,z1 in ((14,14.6),(31.4,32)):
        s=s.fuse(box(-12.7,12.2,-10.7,-9.6,z0,z1))
    s=s.fuse(box(-1,1,-10.7,-9.6,12.8,14.2))
    s=s.fuse(box(2,4,-10.7,-9.6,31.8,33.0))
    for z0,z1 in ((13.3,14),(32,32.7)):
        s=s.fuse(box(-12.7,-11.8,-10.7,-7.8,z0,z1))
    # Two pairs of strap slots; straps wrap battery without squeezing PCB.
    for z in (-73,-43):
        for x in (px0-1,px1+1):
            s=s.cut(box(x-1.0,x+1.0,y0-.1,by+.5,z-2.6,z+2.6))
    return single(s,"main frame")


def build_trigger_gate():
    s=box(-8.4,7.0,5.35,7.65,-30,-9.8)
    for z in (7.0,-33.0):
        s=s.fuse(cyl_y(-9.6,z,3,5.35,7.65))
        s=s.fuse(box(-10,-7.4,5.35,7.65,min(z,-10),max(z,-30)))
    # Side adjustment/nut access stays open over the complete stroke.
    s=s.cut(box(-.8,7.1,5.2,7.8,-18.3,-12.7))
    s=s.cut(box(-5.4,4.0,5.2,7.8,-26.4,-20.4))
    # Removable +Y card groove: end stop at Y=7.3 and 0.15mm X clearance.
    g=box(-22,-17.4,5.6,8.6,-22.5,3.75)
    g=g.cut(box(-20.75,-18.85,5.5,7.3,-21.45,2.75))
    for z in (-4.521,-14.021):
        g=g.cut(cyl_y(-16.1,z,3.3,5.5,8.7))
    s=s.fuse(g)
    s=s.fuse(box(-22.0,-8.0,5.6,7.65,2.8,5.0))
    s=s.fuse(box(-10.2,-7.8,5.35,7.65,-10.2,5.0))
    for z in (7.0,-33.0):
        s=s.cut(cyl_y(-9.6,z,1.2,5.2,7.8))
    return single(s,"trigger side gate")


def build_parts():
    parts={"frame":build_frame(),"control_bridge":build_control_bridge(),
           "trigger_gate":build_trigger_gate(),"trigger":build_trigger(),
           "touch_cover":build_touch_cover(),"right_cap":build_right_cap(),
           "joystick_cap":build_light_knob(),
           "supermini_clamp":build_supermini_clamp(),"imu_cradle":build_imu_cradle(),
           "imu_clamp":build_imu_clamp(),
           "trigger_holder":build_holder()}
    for h in CFG["board"]["mount_holes"]:
        if h["id"] not in ("H2","H3"):
            parts["pcb_clamp_"+h["id"]]=clamp(*h["xz"])
    return parts


def fasteners():
    result=[]
    for h in CFG["board"]["mount_holes"]:
        x,z=h["xz"]
        result.append({"id":"PCB_"+h["id"],"seat":[x,-15.6,z],"axis":[0,1,0],"length":20,
                       "head_d":4,"head_h":2.1,"nut_near_from_seat":16.15,"nut_thickness":1.6})
    for z in (7.0,-33.0):
        result.append({"id":"gate_"+str(z),"seat":[-9.6,7.65,z],"axis":[0,-1,0],"length":10,
                       "head_d":4,"head_h":2.1,"nut_near_from_seat":6.45,"nut_thickness":1.6})
    for group in ("supermini","imu"):
        mount=OPT["module_mounts"][group]
        for i,(x,z) in enumerate(mount["centres_xz"]):
            result.append({"id":group+"_"+str(i+1),"seat":[x,mount["seat_y"],z],
                           "axis":[0,-1,0],"length":mount["screw_length"],
                           "head_d":4,"head_h":2.1,"nut_near_from_seat":mount["seat_y"]-mount["nut_y"][1],
                           "nut_thickness":1.6})
    for h in holder_metadata()["hardware_seats"]:
        result.append({**h,"head_h":h["head_k"],"nut_thickness":1.6,"nut_angle":0})
    x,z=CFG["right_button"]["xz"]
    result.append({"id":"right_cap_keeper","seat":[x+8.1,18.8,z-9.4],
                   "axis":[0,0,1],"length":20,"head_d":4,"head_h":2.1,
                   "nut_near_from_seat":17.9,"nut_thickness":1.6,"nut_angle":30})
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--measure",action="store_true")
    args=parser.parse_args()
    parts=build_parts()
    OUT.mkdir(parents=True,exist_ok=True)
    summary={name:{"volume_mm3":s.Volume(),"valid":s.isValid(),"solids":len(s.Solids())} for name,s in parts.items()}
    volume=sum(s.Volume() for s in parts.values())
    print(json.dumps({"parts":summary,"all_print_parts_volume_mm3":volume,
                      "mass_g_at_1_35_without_sprues":volume*.00135},ensure_ascii=False,indent=2),flush=True)
    for name,shape in parts.items():
        cq.exporters.export(shape,str(OUT/(name+".step")))
    (OUT/"part-volumes.json").write_text(json.dumps(summary,indent=2)+"\n")
    if not args.measure:
        from verify_open_frame import complete_validation
        report=complete_validation(parts,cfg=CARRIER,assembly_cfg=OPT,fasteners=fasteners())
        report["parts_source_sha256"]={name+".step":hashlib.sha256((OUT/(name+".step")).read_bytes()).hexdigest() for name in parts}
        (OUT/"assembly-check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps({"exact_geometry_pass":report["exact_geometry_pass"],
                          "conservative_envelope_review_clear":report["conservative_envelope_review_clear"]},indent=2),flush=True)
        if not report["exact_geometry_pass"] or not report["conservative_envelope_review_clear"]:
            raise SystemExit("Complete assembly validation failed; see generated/assembly-check.json")


if __name__=="__main__":
    main()
