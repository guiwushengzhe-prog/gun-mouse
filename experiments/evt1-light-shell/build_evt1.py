"""EVT-1 light shell: closed grip + windowed upper body around the 30 g carrier.

Two shell halves split at Y=5.35 replace the 13-part open skeleton.  The
carrier PCB, SuperMini/GY modules, trigger slide datums, joystick cap and the
right-button switch are unchanged; the trigger contact and holder follow the
SS-01GL the user bought (evt1_trigger.py).

Printed parts (assembly coordinates, one STEP/STL each, no sprue tree):
  shell_right  - deep half: battery pocket, SuperMini pocket + front USB-C
                 opening, trigger rails/stop, holder groove, screw heads
  shell_left   - shallow half: joystick cone, right-button bezel, trigger
                 gate, holder groove, PCB clamp posts with nut pockets
  imu_cradle   - GY-601N1 cradle with the H1 carrier clamp leg
  trigger, switch_holder, right_cap, joystick_cap
(no printed touch cover: copper foil tape goes straight into the trigger's
front recess; the 0.9 and 1.5 mm covers failed the print shop's size check)

Run from this directory with CadQuery 2.7:  python build_evt1.py
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
EXP = HERE.parent / "30g-onepiece-test-shell"
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
sys.path.insert(0, str(EXP))
sys.path.insert(0, str(HERE))
from build_shell import outline_wire, fillet_y_faces, cone_y  # noqa: E402
import build_skeleton as sk  # noqa: E402
import evt1_trigger as et  # noqa: E402

V = cq.Vector
box, cyl_y, cyl_x = sk.box, sk.cyl_y, sk.cyl_x
E = json.loads((HERE / "evt1-config.json").read_text(encoding="utf-8"))
CFG = sk.CFG
CARRIER = sk.CARRIER
OUT = HERE / "generated"

SH = E["shell"]
W, WU = SH["wall_mm"], SH["upper_wall_mm"]
YR, YS, YL = SH["y_right_outer"], SH["y_split"], SH["y_left_outer"]
FR = SH["edge_fillet_mm"]
TOP = CARRIER["pcb"]["top_face_y"]
BACK = TOP - CARRIER["pcb"]["thickness"]
HOLES = {h["id"]: tuple(h["xz"]) for h in CARRIER["pcb"]["mount_holes"]}
SC = E["screws"]
BIG = 400.0


def fused(shapes):
    shapes = [s for s in shapes if s is not None]
    return shapes[0].fuse(*shapes[1:]).clean() if len(shapes) > 1 else shapes[0]


def single(shape, label):
    s = shape.clean()
    if not s.isValid() or len(s.Solids()) != 1:
        info = [(round(x.Volume(), 3), [round(v, 2) for v in (x.BoundingBox().xmin, x.BoundingBox().xmax,
                 x.BoundingBox().ymin, x.BoundingBox().ymax, x.BoundingBox().zmin, x.BoundingBox().zmax)])
                for x in s.Solids()]
        raise ValueError(f"{label}: invalid/disconnected ({len(s.Solids())} solids) {info}")
    return s.Solids()[0]


def half_y(lo, hi):
    return box(-BIG, BIG, lo, hi, -BIG, BIG)


# ---------------------------------------------------------------- skin

def _prism(points, y0, y1, fillet, inset=0.0):
    wire = outline_wire(points, y0)
    if inset:
        wire = wire.offset2D(-inset, "arc")[0]
    solid = cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), V(0, y1 - y0, 0))
    return fillet_y_faces(solid, fillet)


def _cavity(extra=0.0):
    """Inner cavity: 1.0 mm wall in the grip/trigger zone, 0.8 mm above it."""
    full, upper = SH["outline_full_xz_r"], SH["outline_upper_xz_r"]
    a, b = W + extra, WU + extra
    return fused([_prism(full, YR + a, YL - a, max(FR - a, .5), a),
                  _prism(upper, YR + b, YL - b, max(FR - b, .5), b)])


class Skin:
    """Outer envelope (33.6 mm thick), inner cavity and their difference."""

    def __init__(self):
        self.outer = _prism(SH["outline_full_xz_r"], YR, YL, FR)
        self.inner = _cavity()
        # The lip starts 0.02 mm inside the cavity wall so the halves never share faces.
        self.inner_lip_outer = _cavity(.02)
        self.inner_lip = _cavity(SH["split_lip"]["thickness"] + .02)
        self.hollow = self.outer.cut(self.inner).clean()

    def keep_inside(self, solid):
        return solid.intersect(self.outer)

    def lip(self):
        lip = SH["split_lip"]
        band = half_y(YS - lip["below_split"], YS + lip["above_split"])
        return self.inner_lip_outer.cut(self.inner_lip).intersect(band)

    def lip_relief(self):
        """Lid-side clearance for the tub's lip (lip + clearance)."""
        lip = SH["split_lip"]
        deeper = _cavity(lip["thickness"] + .02 + lip["clearance"])
        band = half_y(YS - .01, YS + lip["above_split"] + lip["clearance"])
        return self.inner.cut(deeper).intersect(band)


# ---------------------------------------------------------------- helpers

def nut_pocket(shape, x, z, y0, y1, entry_dir=(1, 0)):
    pocket = sk.hex_y(x, z, SC["nut_pocket_af"], y0, y1)
    dx, dz = entry_dir
    if dx:
        entry = box(x, x + dx * 4.5, y0, y1, z - 2.15, z + 2.15)
    else:
        entry = box(x - 2.15, x + 2.15, y0, y1, z, z + dz * 4.5)
    return shape.cut(pocket).cut(entry)


def counterbore(x, z, seat_y):
    return fused([cyl_y(x, z, SC["counterbore_d"] / 2, YR - 1, seat_y),
                  cyl_y(x, z, SC["clearance_d"] / 2, YR - 1, YS + 30)])


def rib_xz(points, width, y0, y1):
    return sk.chain(points, width, y0, y1)


# ---------------------------------------------------------------- right shell

TR_CARD = et.holder_groove_x()
SW_HOLES = et.HOLES


def trigger_channel_right():
    """Experiment rails/stop/spring seat; they stay entirely in the right half."""
    pieces = [box(-5.6, 14, -7.0, 5.35, -30, -28.35),          # bottom rail
              box(0, 14, -7.0, 5.35, -11.65, -9.8),            # upper rail, rear face = rest stop
              box(-8.6, 14, -7.0, -5.35, -31.0, -10.6)]        # -Y side wall
    stop = box(-8.6, -4.6, -5.35, 5.35, -28.5, -21.2)
    stop = stop.cut(box(-8.7, -6.2, -3.8, 3.8, -27.4, -22.3))
    # GL cup head passes 0.18 mm above the stop top; relieve as in the economy build.
    stop = stop.cut(box(-8.7, -4.5, -2.6, 2.6, -21.65, -21.1))
    pieces += [stop, cyl_x(0, -24.5, 1.4, -4.61, -3.3), box(-11, -7, -7, 5.35, -32, -30)]
    # Ribs tie the -Y side wall, stop and rails to the shell's right wall.
    for x in (-6.5, 1.0):
        pieces.append(box(x - .4, x + .4, YR + W - .5, -6.9, -31.0, -10.6))
    pieces.append(box(-9.6, -8.4, YR + W - .5, -6.9, -32, -21.2))
    # -Y holder groove for the SS-01GL card (holder shifted +1.9 mm).
    x0, x1 = TR_CARD
    rib = box(x0 - 1.25, x1 + 1.45, -8.6, -5.6, -22.5, 3.75)
    rib = rib.cut(box(x0, x1, -7.3, -5.5, -21.45, 2.75))
    pieces += [rib, box(x0 - 1.25, x1 + 1.45, YR + W - .5, -8.5, -22.5, -21.45),
               box(x0 - 1.25, x1 + 1.45, YR + W - .5, -8.5, 2.75, 3.75)]
    return pieces


def battery_pocket():
    x0, x1, y0, y1, z0, z1 = E["battery"]["bounds"]
    c = E["battery"]["pocket_clearance"]
    t = 1.2
    floor = YR + W - .5
    rail = y0 + 3.0                  # low rails: the cell drops in along -Y
    pieces = [box(x0 - c - t, x0 - c, floor, rail, z0 - c - t, -33.0),
              box(x1 + c, x1 + c + t, floor, rail, z0 - c - t, -33.0),
              box(x0 - c - t, x1 + c + t, floor, rail, z0 - c - t, z0 - c)]
    # Thin floor ribs keep the pouch 0.3 mm off the 1 mm skin.
    for z in (-78.0, -60.0, -42.0):
        pieces.append(box(x0 - c, x1 + c, floor, y0 - .02, z - .6, z + .6))
    # Top corner stops; the middle stays open for the battery leads.
    for a, b in ((x0 - c, x0 + 4.0), (x1 - 4.0, x1 + c)):
        pieces.append(box(a, b, floor, rail, z1 + c, z1 + c + 1.2))
    return pieces


def supermini_pocket():
    sm = E["supermini"]
    bx0, bx1 = sm["board_x"]
    bz0, bz1 = sm["board_z"]
    by0, by1 = sm["board_y"]
    floor = YR + W - .5
    pieces = []
    for za, zb, la, lb in ((bz0 - 1.4, bz0 - .2, bz0 - .2, bz0 + .6),
                           (bz1 + .2, bz1 + 1.4, bz1 - .6, bz1 + .2)):
        # Side wall (Z retention) and narrow ledge under the 0.6 mm free edge.
        for xa, xb in ((bx0 + 1.0, bx0 + 7.0), (bx1 - 7.0, bx1 - 1.0)):
            pieces.append(box(xa, xb, floor, by1 + .4, za, zb))
        pieces.append(box(bx0 + 1.0, bx1 - 1.0, floor, by0, la + (.2 if la < bz0 else 0), lb - (.2 if lb > bz1 else 0)))
    # Antenna-end stops take the plug insertion force; the board drops in
    # straight along -Y and three left-shell posts hold it down.
    for za, zb in ((bz0 - 1.4, bz0 + 3.0), (bz1 - 3.0, bz1 + 1.4)):
        pieces.append(box(bx0 - 2.0, bx0 - .2, floor, by1 + .4, za, zb))
        pieces.append(box(bx0 - .2, bx0 + .6, floor, by0, za, zb))
    # USB-end stops beside the receptacle take the cable pull-out force.
    rx = sm["usb_receptacle"]
    for za, zb in ((bz0 - 1.4, rx["z"][0] - .6), (rx["z"][1] + .6, bz1 + 1.4)):
        pieces.append(box(bx1 + .2, rx["x"][1] + 1.2, floor, by1 + .4, za, zb))
        pieces.append(box(bx1 - .6, bx1 + .2, floor, by0, za, zb))
    return pieces


def usb_opening():
    sm = E["supermini"]["usb_opening"]
    y, z = sm["centre_yz"]
    w, h = sm["w_z"], sm["h_y"]
    slot = box(15.0, 30, y - h / 2, y + h / 2, z - w / 2, z + w / 2)
    return cq.Workplane().add(slot).edges("|X").fillet(sm["corner_r"]).val()


def pcb_boss_right(hid):
    x, z = HOLES[hid]
    return fused([cyl_y(x, z, 3.2, YR + W - .5, -15.0), cyl_y(x, z, 2.6, -15.1, BACK)])


def shell_only_boss_right(x, z):
    return cyl_y(x, z, 3.0, YR + W - .5, YS)


CRADLE_Y = (5.6, 7.8)


def imu_locating_posts():
    """Two tabs hang from the top wall above the carrier edge (Z 40) and one
    post stands at the nose; the cradle rests on them at Y 5.6."""
    im = E["imu"]
    z0, z1 = im["support_tab_z"]
    # Below the split the tab runs into the top wall; above it, it stays clear of the left half.
    pieces = [box(a, b, YR + W - .5, YS, z0, z1) for a, b in im["support_tabs_x"]]
    pieces += [box(a, b, YS - .4, CRADLE_Y[0], z0, z0 + 2.0) for a, b in im["support_tabs_x"]]
    x, z = im["front_post_xz"]
    pieces += [cyl_y(x, z, 1.8, YR + W - .5, CRADLE_Y[0]), cyl_y(x, z, .8, CRADLE_Y[0] - .1, CRADLE_Y[1] - .6)]
    return pieces


CARRIER_REAR_X = min(p[0] for p in CARRIER["pcb"]["outline_xz"])


def switch_pocket_right():
    """Ledge and end walls only behind the carrier's rear edge, so the carrier
    still drops in; the switch goes in after the carrier."""
    sw = E["battery_switch"]
    x0, x1 = sw["body_x"]
    y0, y1 = sw["body_y"]
    z0, z1 = sw["body_z"]
    xe = CARRIER_REAR_X - .25
    shell = box(x0 - .5, xe, y0 - 1.2, YS, z0 - 1.2, z1 + 1.2)
    return shell.cut(box(x0 - 1, x1 + .1, y0 - .1, YS + 1, z0 - .1, z1 + .1))


def _switch_pin_slot():
    """Terminals leave through the +X wall; its Y edges still stop the body."""
    sw = E["battery_switch"]
    y0, y1 = sw["body_y"]
    z0, z1 = sw["body_z"]
    yc = (y0 + y1) / 2
    return box(sw["body_x"][1] - .2, sw["body_x"][1] + 1.4, yc - 1.1, yc + 1.1, z0 + .6, z1 - .6)


def switch_cuts():
    sw = E["battery_switch"]
    ay, az = sw["actuator_envelope_yz"]
    y0, y1 = sw["body_y"]
    z0, z1 = sw["body_z"]
    yc, zc = (y0 + y1) / 2, (z0 + z1) / 2
    travel = sw["actuator_travel_z"]
    slot = box(-70, sw["body_x"][0] + .5, yc - ay / 2 - .2, yc + ay / 2 + .2,
               zc - travel / 2 - az / 2 - .2, zc + travel / 2 + az / 2 + .2)
    return slot


def windows(side):
    spec = SH["windows_xz"]
    r = spec["corner_r"]
    cuts = []
    for x0, x1, z0, z1 in spec[side]:
        y0, y1 = (YR - 1, YR + W + .05) if side == "right" else (YL - W - .05, YL + 1)
        w = box(x0, x1, y0, y1, z0, z1)
        cuts.append(cq.Workplane().add(w).edges("|Y").fillet(r).val())
    return cuts


def vent_slots():
    spec = SH["vent_slots_right"]
    x0, x1 = spec["x"]
    w = spec["width"]
    cuts = []
    for z in spec["z_centres"]:
        slot = box(x0, x1, YR - 1, YR + W + .05, z - w / 2, z + w / 2)
        cuts.append(cq.Workplane().add(slot).edges("|Y").fillet(w / 2 - .01).val())
    return cuts


def build_right(skin):
    shell = skin.hollow.intersect(half_y(-BIG, YS))
    adds = trigger_channel_right() + battery_pocket() + supermini_pocket() + imu_locating_posts()
    for hid in HOLES:
        adds.append(pcb_boss_right(hid))
    for x, z in SC["shell_only_xz"]:
        adds.append(shell_only_boss_right(x, z))
    adds.append(switch_pocket_right())
    adds = [skin.keep_inside(a) for a in adds]
    shell = fused([shell, skin.lip()] + adds)
    cuts = windows("right") + vent_slots() + [usb_opening(), switch_cuts(),
            # Trigger bar window through the front wall (V1 datum); it also
            # removes the split lip above it so the trigger lifts straight out.
            box(-0.5, 16, -5.35, YS + 2.0, -28.35, -11.65)]
    for hid in HOLES:
        x, z = HOLES[hid]
        cuts.append(counterbore(x, z, SC["pcb_M2x20_seat_y"]))
    for x, z in SC["shell_only_xz"]:
        cuts.append(counterbore(x, z, SC["shell_only_M2x20_seat_y"]))
    # The split lip would block the SuperMini's receptacle as it drops in.
    sm = E["supermini"]
    front_inner = max(p[0] for p in SH["outline_full_xz_r"]) - WU - .01
    cuts.append(box(sm["board_x"][1] - .5, front_inner, YS - 1.5, YS + 2,
                    sm["board_z"][0] - 1.5, sm["board_z"][1] + 1.5))
    sw = E["battery_switch"]
    cuts.append(box(sw["body_x"][0] - 1, sw["body_x"][1] + .1, sw["body_y"][0] - .1, sw["body_y"][1] + .1,
                    sw["body_z"][0] - .1, sw["body_z"][1] + .1))
    # SS-01GL holder screw tips (Y -13.6) and nuts need clear corridors.
    for x, z in SW_HOLES:
        cuts.append(cyl_y(x, z, 3.3, -13.9, YS + .1))
    for c in cuts:
        shell = shell.cut(c)
    return single(shell, "shell_right")


# ---------------------------------------------------------------- left shell

def control_pads():
    """Local wall Y 17.6..20 around the joystick cone and the button bezel."""
    y0, y1 = SH["control_wall_y"]
    jx, jz = CFG["joystick"]["shaft_xz"]
    bx, bz = CFG["right_button"]["xz"]
    return [cyl_y(jx, jz, 10.8, y0, y1 - .3), box(bx - 9.3, bx + 9.3, y0, y1 - .3, bz - 6.8, bz + 6.8)]


def control_cuts():
    js = CFG["joystick"]
    jx, jz = js["shaft_xz"]
    pivot = TOP + js["pivot_above_pcb_assumed"]
    tan = math.tan(math.radians(js["stop_angle_deg"]))
    stem_r = js["knob"]["stem_d"] / 2 / math.cos(math.radians(js["stop_angle_deg"]))
    def r(y):
        return (y - pivot) * tan + stem_r
    y0, y1 = SH["control_wall_y"]
    cone = cone_y(jx, jz, r(y0 - 2.0), r(y1 + 1.0), y0 - 2.0, y1 + 1.0)
    bx, bz = CFG["right_button"]["xz"]
    bezel = box(bx - 7.3, bx + 7.3, y0 - 3, YL + 3, bz - 4.8, bz + 4.8)
    # Flange stroke space under the bezel (X/Z of the 16.8 x 11.8 flange + 0.3).
    fy0 = E["right_cap"]["flange_y"][0] - E["right_cap"]["travel"] - .4
    flange = box(bx - 8.7, bx + 8.7, fy0, y0, bz - 6.2, bz + 6.2)
    return [cone, bezel, flange]


def clamp_post_left(hid):
    x, z = HOLES[hid]
    foot = cyl_y(x, z, 3.3, TOP, 3.1)
    if (x, z) == (-27, -27):
        # C_RAIL capacitor body ends at X=-29: same relief as the experiment.
        foot = foot.cut(box(x - 4, -28.8, TOP - .1, 3.2, z - 4, z + 4))
    post = cyl_y(x, z, 2.2 if hid != "H4" else 2.6, 3.0, YL - .3)
    if hid == "H4":
        post = post.cut(box(x - 4, -28.8, 2.9, YL, z - 4, z + 4))
    return fused([foot, post])


def shell_only_boss_left(x, z):
    return cyl_y(x, z, 3.0, YS, YL - .3)


def imu_press_pads():
    im = E["imu"]
    x0, x1 = im["board_x"]
    z0, z1 = im["board_z"]
    top = im["board_y"][1]
    pads = []
    # Posts stand just outside each board corner; a 0.9 mm foot reaches over
    # the corner's free edge, clear of the 2.8 mm component envelope.
    for sx, sz in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        cx = x0 if sx < 0 else x1
        cz = z0 if sz < 0 else z1
        px, pz = cx + sx * .7, cz + sz * .7
        # One block from the post centre to 0.9 mm over the corner: no edge-only contacts.
        fx = (px, cx - sx * .9)
        fz = (pz, cz - sz * .9)
        pads.append(box(min(fx), max(fx), top + .05, top + 1.0, min(fz), max(fz)))
        pads.append(cyl_y(px, pz, 1.0, top + .6, YL - .3))
    return pads


def supermini_press_posts():
    """Feet on the 1 mm free board edge; the antenna end has one post because
    the GY module sits above its upper corner."""
    sm = E["supermini"]
    bx0, bx1 = sm["board_x"]
    bz0, bz1 = sm["board_z"]
    by1 = sm["board_y"][1]
    posts = []
    for px, pz in sm["hold_down_posts_xz"]:
        fx = (bx1 - .9, bx1 - .1) if px > 0 else (bx0 + .1, bx0 + .9)
        fz = (pz - .4, pz + .4)
        r = 1.2 if px > 0 else .9
        ctop = sm["top_components"]["y"][1]
        posts.append(box(*fx, by1 + .05, ctop + .5, *fz))
        posts.append(box(min(fx[0], px), max(fx[1], px), ctop + .3, ctop + .5, min(fz[0], pz), max(fz[1], pz)))
        posts.append(cyl_y(px, pz, r, ctop + .3, YL - .3))
    return posts


def battery_press_pads():
    x0, x1, y0, y1, z0, z1 = E["battery"]["bounds"]
    pads = []
    for x in (x0 + 7, x1 - 7):
        for z in (-76.0, -52.0):
            pads.append(box(x - 2, x + 2, y1 + .3, y1 + 1.3, z - 2, z + 2))
            pads.append(cyl_y(x, z, 1.5, y1 + 1.2, YL - .3))
    return pads


def gate_left():
    """Experiment trigger gate + +Y holder groove, tied to the left wall."""
    s = box(-8.4, 7.0, 5.35, 7.65, -30, -9.8)
    s = s.cut(box(-.8, 7.1, 5.2, 7.8, -18.3, -12.7))
    s = s.cut(box(-5.4, 4.0, 5.2, 7.8, -26.4, -20.4))
    x0, x1 = TR_CARD
    g = box(x0 - 1.25, x1 + 1.45, 5.6, 8.6, -22.5, 3.75)
    g = g.cut(box(x0, x1, 5.5, 7.3, -21.45, 2.75))
    pieces = [s, g, box(x0 - 1.25, -8.0, 5.6, 7.65, 2.8, 5.0), box(-10.2, -7.8, 5.35, 7.65, -10.2, 5.0)]
    # Ties to the lid face (inner face Y 14.6 in the grip zone).
    # The touch wire runs over the gate at Z -15..-10.5; ties leave that band open.
    for x, z0, z1 in ((-7.0, -30, -15.5), (2.0, -30, -21), (x0 - .6, -22.5, -15.5), (x0 - .6, 0.0, 3.75)):
        pieces.append(box(x - .6, x + .6, 7.5, YL - .3, z0, z1))
    return pieces


def touch_wire_slot():
    """Notch open at the gate's top edge: the already-soldered touch wire lies
    in it when the left half is lowered, then runs over the gate to J_TOUCH."""
    return [box(-6.5, -1.5, 5.2, 7.8, -14.5, -9.6)]


def switch_pocket_left():
    sw = E["battery_switch"]
    x0, x1 = sw["body_x"]
    y0, y1 = sw["body_y"]
    z0, z1 = sw["body_z"]
    shell = box(x0 - .5, x1 + 1.2, YS, y1 + 1.2, z0 - 1.2, z1 + 1.2)
    shell = shell.cut(box(x0 - 1, x1 + .1, YS - 1, y1 + .1, z0 - .1, z1 + .1))
    return shell.cut(_switch_pin_slot())


def build_left(skin):
    shell = skin.hollow.intersect(half_y(YS, BIG))
    adds = control_pads() + imu_press_pads() + supermini_press_posts() + battery_press_pads() + gate_left()
    for hid in ("H2", "H3", "H4"):
        adds.append(clamp_post_left(hid))
    for x, z in SC["shell_only_xz"]:
        adds.append(shell_only_boss_left(x, z))
    adds.append(switch_pocket_left())
    adds = [skin.keep_inside(a) for a in adds]
    shell = fused([shell] + adds)
    cuts = control_cuts() + touch_wire_slot() + windows("left") + [skin.lip_relief(), switch_cuts()]
    for hid in ("H2", "H3", "H4"):
        x, z = HOLES[hid]
        cuts.append(cyl_y(x, z, 1.2, TOP - .1, 4.6))
    for x, z in SC["shell_only_xz"]:
        cuts.append(cyl_y(x, z, 1.2, YS - .1, 10.5))
    for c in cuts:
        shell = shell.cut(c)
    for hid in ("H2", "H3", "H4"):
        x, z = HOLES[hid]
        shell = nut_pocket(shell, x, z, .55, 2.45)
    for x, z in SC["shell_only_xz"]:
        tip = SC["shell_only_M2x20_seat_y"] + 20
        shell = nut_pocket(shell, x, z, tip - 2.6, tip - .8, entry_dir=(-1, 0) if x > 0 else (1, 0))
    for x, z in SW_HOLES:
        shell = shell.cut(cyl_y(x, z, 3.3, 5.5, 8.8))
    return single(shell, "shell_left")


# ---------------------------------------------------------------- small parts

def build_imu_cradle(skin=None):
    """Frame under the GY's 1 mm free edges with corner stops, the H1 carrier
    clamp leg (nut pocket), two top pads on the shell tabs and a nose foot."""
    im = E["imu"]
    x0, x1 = im["board_x"]
    z0, z1 = im["board_z"]
    y0, y1 = CRADLE_Y
    by0 = im["board_y"][0]
    pieces = [box(x0 - 1.1, x0 + .8, y0, y1, z0 - 1.1, z1 + 1.1),        # left rail
              box(x1 - .8, x1 + 1.1, y0, y1, z0 - 1.1, z1 + 1.1),        # right rail
              box(x0 - 1.1, x1 + 1.1, y0, y1, z1 - .8, z1 + 1.1),        # top rail
              box(x0 - 1.1, x1 + 1.1, y0, y1, z0 - 1.1, z0 + .8)]        # bottom rail
    # Corner stops locate the board edges (0.1 mm per side).
    for cx, sx in ((x0, -1), (x1, 1)):
        for cz, sz in ((z0, -1), (z1, 1)):
            pieces.append(box(min(cx + sx * .1, cx + sx * 1.1), max(cx + sx * .1, cx + sx * 1.1), y1 - .1,
                              by0 + 1.0, min(cz - sz * 2.5, cz + sz * 1.1), max(cz - sz * 2.5, cz + sz * 1.1)))
            pieces.append(box(min(cx - sx * 2.5, cx + sx * 1.1), max(cx - sx * 2.5, cx + sx * 1.1), y1 - .1,
                              by0 + 1.0, min(cz + sz * .1, cz + sz * 1.1), max(cz + sz * .1, cz + sz * 1.1)))
    tz0 = im["support_tab_z"][0]
    for a, b in im["support_tabs_x"]:
        pieces.append(box(a, b, y0, y1, z1, tz0 + 1.6))
    fx, fz = im["front_post_xz"]
    pieces += [sk.beam((x1 + .2, z0 - .2), (fx, fz), 2.4, y0, y1), cyl_y(fx, fz, 1.8, y0, y1)]
    x, z = HOLES["H1"]
    pieces += [cyl_y(x, z, 3.3, TOP, 3.1), cyl_y(x, z, 2.4, 3.0, y1 - .2)]
    s = fused(pieces)
    # Keep the bottom face of the GY clear between the edge rails.
    s = s.cut(box(x0 + .8, x1 - .8, y1 - .2, y1 + 3, z0 + .8, z1 - .8))
    s = s.cut(cyl_y(fx, fz, .95, y0 - .1, y1 + .1))
    s = s.cut(cyl_y(x, z, 1.2, TOP - .1, 4.6))
    s = nut_pocket(s, x, z, .55, 2.45)
    if skin is not None:
        lip = SH["split_lip"]
        s = s.intersect(_cavity(lip["thickness"] + lip["clearance"]))
    return single(s, "imu_cradle")


def build_right_cap():
    """Experiment cap without the outer lip: it passes the bezel from inside;
    the flange keeps it in, the D2FC bottoming limits travel (normal mouse)."""
    x, z = CFG["right_button"]["xz"]
    rc = E["right_cap"]
    f0, f1 = rc["flange_y"]
    face = rc["face_y"]
    solid_from = SH["control_wall_y"][1] - .2     # 1.7 mm solid face
    top = TOP
    body = box(x - 7, x + 7, f0, face, z - 4.5, z + 4.5)
    body = cq.Workplane().add(body).faces(">Y").edges().fillet(1.0).val()
    flange = box(x - 8.4, x + 8.4, f0, f1, z - 5.9, z + 5.9)
    # Same stem/tip datums as the experiment: tip at top+7.30 (0.15 preload).
    stem = box(x - 1.9, x + 3.1, top + 8.30, f0 + .05, z - 2, z + 2)
    tip = box(x + 1.55, x + 2.35, top + 7.30, top + 8.35, z - 1.0, z + 1.0)
    s = fused([body, flange, stem, tip])
    for a, b in ((x - 5.5, x - 1.9), (x + 3.1, x + 5.5)):
        s = s.cut(box(a, b, f0 - .1, solid_from, z - 3.0, z + 3.0))
    for a, b in ((z - 3.4, z - 2.0), (z + 2.0, z + 3.4)):
        s = s.cut(box(x - 5.5, x + 5.5, f0 - .1, solid_from, a, b))
    return single(s, "right cap")


def build_joystick_cap():
    """Experiment light knob with the disc lowered for the 15.6 mm face."""
    knob_cfg = copy.deepcopy(CFG)
    knob_cfg["joystick"]["shaft_engage"] = 3.37
    drop = knob_cfg["joystick"]["knob"]["cap_bottom_y"] - E["joystick_cap"]["cap_bottom_y"]
    knob_cfg["joystick"]["knob"]["cap_bottom_y"] = E["joystick_cap"]["cap_bottom_y"]
    s = sk.build_knob(knob_cfg, tip_above_pcb=18.75)
    x, z = CFG["joystick"]["shaft_xz"]
    for angle in (0, 90, 180, 270):
        pocket = box(x + 4.1, x + 6.9, 24.9 - drop, 26.35 - drop, z - 1.5, z + 1.5)
        s = s.cut(pocket.rotate((x, 0, z), (x, 1, z), angle))
    return single(s, "joystick cap")


def build_parts():
    skin = Skin()
    parts = {
        "shell_right": build_right(skin),
        "shell_left": build_left(skin),
        "imu_cradle": build_imu_cradle(skin),
        "trigger": et.build_trigger(),
        "switch_holder": et.build_holder(),
        "right_cap": build_right_cap(),
        "joystick_cap": build_joystick_cap(),
    }
    return skin, parts


def fasteners():
    rows = []
    for hid, (x, z) in HOLES.items():
        nut = "imu_cradle" if hid == "H1" else "shell_left"
        rows.append({"id": "PCB_" + hid, "type": "M2x20", "seat": [x, SC["pcb_M2x20_seat_y"], z],
                     "axis": [0, 1, 0], "length": 20, "head_d": 4, "head_h": 2.1,
                     "nut_y": [.55, 2.15], "nut_in": nut})
    for x, z in SC["shell_only_xz"]:
        seat = SC["shell_only_M2x20_seat_y"]
        rows.append({"id": f"shell_{x:g}_{z:g}", "type": "M2x20", "seat": [x, seat, z], "axis": [0, 1, 0],
                     "length": 20, "head_d": 4, "head_h": 2.1, "nut_y": [seat + 20 - 2.6 + .1, seat + 20 - .9],
                     "nut_in": "shell_left"})
    for s in et.hardware_seats():
        rows.append({**s, "type": "M2x20", "nut_y": [-6.4, -4.8], "nut_in": "switch_holder"})
    rows.append({"id": "trigger_contact", "type": "M2x10", "axis": [1, 0, 0], "length": 10,
                 "nut_in": "trigger", "nuts": 2})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args()
    skin, parts = build_parts()
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {k: {"volume_mm3": round(s.Volume(), 3), "valid": s.isValid(), "solids": len(s.Solids())}
               for k, s in parts.items()}
    total = sum(s.Volume() for s in parts.values())
    dens = E["materials_g_cm3"]
    report = {"parts": summary, "all_parts_volume_mm3": round(total, 3),
              "mass_g": {k: round(total * v / 1000, 2) for k, v in dens.items()}}
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not args.no_export:
        from print_pack import check_stl
        from clean_stl_zero_area import clean as drop_zero_area_triangles
        stl = {}
        for k, s in parts.items():
            cq.exporters.export(s, str(OUT / f"{k}.step"))
            path = OUT / f"{k}.stl"
            cq.exporters.export(s, str(path), tolerance=0.02, angularTolerance=0.1)
            # OCC leaves a few exactly-zero-area slivers on the large shells.
            drop_zero_area_triangles(path)
            c = check_stl(path)
            rel = abs(c["volume_mm3"] - s.Volume()) / s.Volume()
            stl[k] = {"watertight": c["watertight"], "bodies": c["connected_bodies"],
                      "mesh_vs_cad_volume": round(rel, 6),
                      "ok": c["watertight"] and c["connected_bodies"] == 1 and c["winding_consistent"] and rel < .005}
        report["stl_checks"] = stl
        if not all(v["ok"] for v in stl.values()):
            raise SystemExit("STL export check failed: " + json.dumps(stl))
        (OUT / "part-volumes.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
    return skin, parts


if __name__ == "__main__":
    main()
