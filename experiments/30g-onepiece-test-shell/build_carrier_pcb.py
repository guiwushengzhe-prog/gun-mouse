"""Generate the hand-soldered, all-THT S3 SuperMini carrier and fabrication files.

Run with system Python (KiCad 9 pcbnew), not the CadQuery interpreter:
  /usr/bin/python3 experiments/30g-onepiece-test-shell/build_carrier_pcb.py
  ... --config-only  # freeze geometry/pinmap without doing routing/exports

All component pads are explicitly defined from source geometry or conventional
THT lead pitches. Unknown module pin pitches are deliberately not footprints:
the SuperMini and GY-601N1 attach by individually labelled soldered wires.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import math
import os
import shutil
import subprocess
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape

for _key, _dir in (("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data")):
    os.environ.setdefault(_key, f"/tmp/gun-mouse-carrier/{_dir}")
    Path(os.environ[_key]).mkdir(parents=True, exist_ok=True)

import numpy as np
import pcbnew as pcb
from scipy.ndimage import distance_transform_edt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "pcb"
CONFIG = HERE / "carrier-config.json"
BOARD_FILE = OUT / "gun-mouse-supermini-carrier.kicad_pcb"
GRID = 0.254
TRACK_W = 0.30
CLEARANCE = 0.25
VIA_D, VIA_DRILL = 0.70, 0.30
MM = pcb.FromMM


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def kxy(xz):
    # Original library plane: u=-X, v=Z. KiCad's screen Y points down.
    return [-float(xz[0]) - 3.0, 45.0 - float(xz[1])]


def vec(xy):
    return pcb.VECTOR2I(MM(float(xy[0])), MM(float(xy[1])))


def pad(number, xz, net, drill=1.0, size=1.8, shape="circle"):
    return {"number": str(number), "xz": [round(float(v), 4) for v in xz], "net": net,
            "drill": [drill, drill] if isinstance(drill, (int, float)) else list(drill),
            "size": [size, size] if isinstance(size, (int, float)) else list(size), "shape": shape}


def default_config():
    old = json.loads((ROOT / "config/pcb-shell-v1.json").read_text(encoding="utf-8"))
    geometry = json.loads((ROOT / "config/pcb-parts-geometry.json").read_text(encoding="utf-8"))["parts"]
    parts = []
    # These two footprints are measured from the existing placed LCSC models;
    # pad positions and slotted holes are preserved, not guessed from body boxes.
    for ref in ("SW1", "SW2"):
        source = next(p for p in old["parts"] if p["ref"] == ref)
        geo = geometry[source["lcsc"]]
        x, z = source["xz"]
        pads = []
        for p in geo["pads"]:
            if not p.get("hole"):
                continue
            hole = p["hole"]
            d = hole[1:3]
            size = [round(v + .8, 4) for v in d]
            n = p["n"]
            net = source["nets"].get(n, "")
            pads.append(pad(n, [x-p["x"], z+p["y"]], net, d, size,
                            "oval" if hole[0] == "SLOT" else "circle"))
        npth = [{"xz": [round(x-p["x"], 4), round(z+p["y"], 4)], "d": p["d"]}
                for p in geo.get("npth", [])]
        b = geo["body"]
        parts.append({"ref": ref, "kind": "joystick" if ref == "SW1" else "microswitch",
                      "value": geo["mpn"], "position_xz": [x, z], "pads": pads, "npth": npth,
                      "envelope": {"x": [x-b["x"][1], x-b["x"][0]],
                                   "z": [z+b["y"][0], z+b["y"][1]],
                                   "y_above_board": b["z_top"], "lead_below_board": 1.0},
                      "envelope_basis": "Existing library maximum bounds, including moving shaft/plunger space; clip leads to <=1 mm below board",
                      "source": "config/pcb-parts-geometry.json, config/pcb-shell-v1.json",
                      "assembly": "THT hand solder; SW2 COM/NO verified with a meter before use", "populate": True})
        if ref == "SW1":
            parts[-1]["envelopes"] = [
                {"kind":"box","x":[x-b["x"][1],x-b["x"][0]],"z":[z+b["y"][0],z+b["y"][1]],
                 "y_above_board":[0,12.75],"source":"Alps official drawing: side VR max12.45 mm +0.3 mm allowance"},
                {"kind":"cylinder_y","xz":[-33,23],"radius":2.15,"y_above_board":[12.45,19.65],
                 "source":"Alps shaft nominal diameter4 mm +0.3 mm allowance, source tip-high19.65 mm"}]
            parts[-1]["envelope_basis"] = "Static body and narrow shaft split using official drawing, upper bounds retained separately; shaft pivot/motion needs physical check"
        else:
            parts[-1]["envelopes"] = [
                {"kind":"box","x":[x-b["x"][1],x-b["x"][0]],"z":[z+b["y"][0],z+b["y"][1]],
                 "y_above_board":[0,6.6],"source":"Omron D2FC official case height6.5+0.1 mm; recess beside plunger requires sample check"},
                {"kind":"box","x":[-31.65,-30.45],"z":[-3.45,-.55],"y_above_board":[6.5,7.45],
                 "source":"Omron D2FC drawing: plunger1.2x2.9 mm at globalX=-31.05,Z=-2; source tip-high7.45 mm"}]
            parts[-1]["envelope_basis"] = "Official 6.5+0.1 mm case and local movable plunger split; top recess must be checked on purchased sample"
            parts[-1]["assembly"] = "THT hand solder; pin1 COM,GND; pin2 NO,BTN_R; pin3 dummy mechanical terminal, no circuit connection"

    def wirebank(ref, x, z, nets, purpose):
        ps = [pad(i+1, [x, z-2.54*i], net) for i, net in enumerate(nets)]
        parts.append({"ref": ref, "kind": "wirebank", "value": "Labelled solder wires",
                      "position_xz": [x, z], "pads": ps, "npth": [],
                      "envelope": {"x": [x-1, x+1], "z": [z-2.54*(len(nets)-1)-1, z+1],
                                   "y_above_board": 2.0, "lead_below_board": 1.0},
                      "envelope_basis": "Solder joint and wire end allowance; no module connector pitch is assumed",
                      "purpose": purpose, "populate": True})

    wirebank("J_MCU", -56, -5, ["3V3", "GND", "JOY_X", "JOY_Y", "JOY_SW", "BTN_R", "TRIG",
                                 "SDA", "SCL", "TOUCH", "VBAT_ADC", "VBUS_DET"],
             "One wire per functional net to the verified SuperMini pinmap; no plug/socket on the carrier")
    wirebank("J_GY", -53, 10, ["3V3", "GND", "SCL", "SDA"],
             "GY-601N1 chip interface H2: VCC,GND,SCL,SDA; module already has I2C pullups")
    wirebank("J_TRIG", -25.5, -9, ["GND", "TRIG"], "External SS-01GL13 COM/NO, NC unconnected")
    wirebank("J_TOUCH", -25.5, -18, ["TOUCH_ELECTRODE", "GND"],
             "Insulated foil to TOUCH_ELECTRODE; second pad only optional cable shield, never the same foil")
    wirebank("J_BAT", -56, 25, ["BAT_RAW", "GND"], "Protected single-cell LiPo input")
    wirebank("J_SWITCH", -56, 17, ["BAT_RAW", "BAT_SW"], "External SPST battery-positive isolation switch")
    wirebank("J_MODULE_BAT", -13, 20, ["BAT_SW", "GND"], "SuperMini dedicated B+ and B- pads only")
    wirebank("J_MODULE_RAIL", -13, 12.5, ["VBUS_SHARED"],
             "SuperMini 5V/shared VBUS rail monitor only; not an external battery input")

    def resistor(ref, x, z, value, net1, net2, purpose):
        parts.append({"ref": ref, "kind": "resistor", "value": value, "position_xz": [x, z],
                      "pads": [pad(1, [x-3.81,z], net1, .8, 1.6), pad(2,[x+3.81,z],net2,.8,1.6)],
                      "npth": [], "envelope": {"x":[x-3.2,x+3.2],"z":[z-1.3,z+1.3],
                                                   "y_above_board":2.7,"lead_below_board":1.0},
                      "envelope_basis":"Purchase axial <=6.4x2.6 mm body, 7.62 mm formed lead pitch; clip tails <=1 mm",
                      "purpose": purpose, "populate": True})
    resistor("R_JOY", -47,-11,"3.3k", "3V3","JOY_SW","Joystick click external pullup")
    resistor("R_RIGHT", -37,-11,"3.3k", "3V3","BTN_R","Right button external pullup")
    resistor("R_TRIG", -47,-17,"3.3k", "3V3","TRIG","SS-01GL closed contact current approx 1 mA at 3.3 V")
    resistor("R_TOUCH", -37,-17,"510", "TOUCH_ELECTRODE","TOUCH","Touch series resistor, no pullup or parallel capacitor")
    resistor("R_BAT_H", -47,-23,"100k", "BAT_SW","VBAT_ADC","Battery switched-side divider upper")
    resistor("R_BAT_L", -37,-23,"100k", "VBAT_ADC","GND","Battery divider lower, scale=2")
    resistor("R_RAIL_H", -47,-29,"100k", "VBUS_SHARED","VBUS_DET","Shared rail divider upper; ADC inference, not digital USB state")
    resistor("R_RAIL_L", -37,-29,"100k", "VBUS_DET","GND","Shared rail divider lower, scale=2")

    def capacitor(ref,x,z,net,value="100n",purpose="ADC/contact filter"):
        parts.append({"ref":ref,"kind":"capacitor","value":value,"position_xz":[x,z],
                      "pads":[pad(1,[x-1.27,z],net,.8,1.6),pad(2,[x+1.27,z],"GND",.8,1.6)],"npth":[],
                      "envelope":{"x":[x-3,x+3],"z":[z-1,z+1],"y_above_board":7,"lead_below_board":1},
                      "envelope_basis":"Purchase ceramic THT 2.54 mm pitch <=6 mm wide, <=2 mm thick, <=7 mm installed height",
                      "purpose":purpose,"populate":True})
    capacitor("C_JOY_X",-49,24,"JOY_X")
    capacitor("C_JOY_Y",-49,17,"JOY_Y")
    capacitor("C_JOY_SW",-42,-8,"JOY_SW")
    capacitor("C_RIGHT",-32,-8,"BTN_R")
    capacitor("C_TRIG",-42,-14,"TRIG")
    capacitor("C_BAT",-42,-26,"VBAT_ADC")
    capacitor("C_RAIL",-32,-26,"VBUS_DET")

    return {
        "version":"supermini-tht-carrier-v1","units":"mm",
        "status":"Hand-soldered prototype; routing/DRC report controls fabrication readiness, module variant still requires physical power-path check",
        "pcb":{"outline_xz":[[-60,-42],[-23,-42],[-23,10],[-8,10],[-8,40],[-60,40]],
               "thickness":1.6,"top_face_y":-1.63,"max_size_mm":[52,82],"layers":2,"copper_oz":1,
               "mount_holes":[{"id":"H1","xz":[-12,36],"d":2.4},{"id":"H2","xz":[-56,36],"d":2.4},
                              {"id":"H3","xz":[-51,-4],"d":2.4},{"id":"H4","xz":[-27,-27],"d":2.4}],
               "mount_contact_radius":3.3,"trace_width_mm":TRACK_W,"clearance_mm":CLEARANCE,
               "via_d_drill_mm":[VIA_D,VIA_DRILL],"factory_smt":False,
               "kicad_mapping":"(Kx,Ky)=(-X-3,45-Z); top components face +Y in the assembly"},
        "firmware_pins":{"JOY_X":1,"JOY_Y":2,"JOY_SW":4,"BTN_R":12,"TRIG":8,"SDA":5,"SCL":6,"TOUCH":7,
                         "VBAT_ADC":9,"VBUS_DET":10},
        "mcu":{"name":"TENSTAR-style ESP32-S3 SuperMini, USB-C, two 9-pad sides",
               "chip":"ESP32-S3FH4R2","flash_mb":4,"psram_mb":2,"psram_mode":"qspi",
               "flash_size_mb":4,"native_usb_gpio":[19,20],"reserved_gpio":[3,43,44],
               "source":"TENSTAR product physical pin diagram; family circuit reference NOLOGO S3 schematic, do not substitute C3/ordinary ESP32"},
        "modules":{
            "mcu":{"name":"TENSTAR-style S3 SuperMini","x":[-12,11.5],"z":[14,32],"component_face_y":-8.0,
                   "board_thickness":1.6,"front_allowance":3.5,"back_wire_allowance":2.0,
                   "source":"TENSTAR family product diagram: 23.5x18 mm board; assembled allowance requires first-sample check",
                   "limits":"Direct solder wires, no Dupont housings; leave USB at X=-12 and ceramic antenna at X=11.5 unobstructed"},
            "imu":{"name":"GY-601N1-LSM6DSV16X","x":[-22,-1.4],"z":[20.1,37.9],"component_face_y":9.0,
                   "board_thickness":1.2,"front_allowance":5.0,"back_wire_allowance":0.0,
                   "source":"config/economy-mechanical.json; manufacturer GY-601N1 module manual 17.8x20.6x2.8",
                   "limits":"Remove tall headers; front component/solder-wire allowance <=5 mm, no unverified mounting holes"}},
        "battery":{"name":"Protected 1S LiPo <=8x31x52.5 mm, approx 600-700 mAh",
                   "center_xyz":[-37.7,-8.23,-58],"size_xyz":[31,8,52.5],
                   "source":"Maximum assembly dimensional allowance; protection/lead overhang requires physical check"},
        "power":{"logic_v":3.3,"battery_net":"BAT_SW","battery_switch":"BAT_RAW -> external SPST -> BAT_SW",
                 "low_battery_shutdown_mv":3600,"low_battery_delay_s":30,
                 "battery_divider":{"upper_ohm":100000,"lower_ohm":100000,"capacitor_f":1e-7,"scale":2},
                 "rail_divider":{"upper_ohm":100000,"lower_ohm":100000,"capacitor_f":1e-7,"scale":2},
                 "vbus_detection":{"mode":"adc_shared_rail_external_5v_inference","pin":10,"on_mv":4500,"off_mv":4300},
                 "module_reference":"BAT -> BAT60B diode -> shared USB VBUS/5V rail; TP4054-style charger; not XIAO load-sharing circuit",
                 "charge_current_ma":100,"charge_current_boost":"Keep BOOST open; do not assume 300 mA is appropriate",
                 "safety_limits":["Protected battery mandatory; family diagram has no protection IC",
                                  "Battery OFF before connecting computer USB; only powered wall chargers during battery operation",
                                  "Battery OFF disables battery charging but USB can keep the MCU running",
                                  "Check actual purchased module against B+/B-, diode OR and charger reference before wiring",
                                  "Shared 5V pin is also battery-powered below 4.2 V; never use it as a digital USB-present input"]},
        "parts":parts,
        "source_sha256":{str(p.relative_to(ROOT)):digest(p) for p in (ROOT/"config/pcb-shell-v1.json",ROOT/"config/pcb-parts-geometry.json")},
    }


def add_text(board, text, xy, size=.8, layer=pcb.F_SilkS):
    t=pcb.PCB_TEXT(board);t.SetText(text);t.SetPosition(vec(xy));t.SetTextSize(vec([size,size]));t.SetTextThickness(MM(.12))
    t.SetLayer(layer);board.Add(t);return t


def line(board,a,b,layer,width=.10):
    item=pcb.PCB_SHAPE(board);item.SetShape(pcb.SHAPE_T_SEGMENT);item.SetStart(vec(a));item.SetEnd(vec(b));item.SetLayer(layer);item.SetWidth(MM(width));board.Add(item)


def configure_default_netclass(board):
    # Set the live NET_SETTINGS object: KiCad 9 may supply its own Default class
    # when loading a minimal project JSON. Persist matching GUI routing defaults
    # as well as the independently enforced global minimum design rules.
    n=board.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
    n.SetClearance(MM(CLEARANCE));n.SetTrackWidth(MM(TRACK_W));n.SetViaDiameter(MM(VIA_D));n.SetViaDrill(MM(VIA_DRILL))


def new_board(config):
    board=pcb.BOARD();board.SetCopperLayerCount(2)
    # The native zone filler dereferences the project's net settings. Attach
    # a real headless project rather than leaving BOARD.GetProject() null.
    project_file=BOARD_FILE.with_suffix(".kicad_pro")
    write_json(project_file,{"meta":{"filename":project_file.name,"version":1},
                            "board":{"design_settings":{"rules":{"min_clearance":CLEARANCE,"min_track_width":.25,
                                    "min_copper_edge_clearance":.5,"min_hole_clearance":.25,"min_hole_to_hole":.25,
                                    "min_via_annular_width":.15,"min_via_diameter":.6,"min_through_hole_diameter":.25,
                                    "min_text_height":.8,"min_text_thickness":.10,"min_silk_clearance":.15}}},
                            "net_settings":{"meta":{"version":4},"classes":[{"name":"Default","clearance":CLEARANCE,
                                "track_width":TRACK_W,"via_diameter":VIA_D,"via_drill":VIA_DRILL}]}})
    global PROJECT_MANAGER
    PROJECT_MANAGER=pcb.SETTINGS_MANAGER(True);PROJECT_MANAGER.LoadProject(str(project_file))
    board.SetProject(PROJECT_MANAGER.GetProject(str(project_file)))
    configure_default_netclass(board)
    board.GetDesignSettings().m_MinClearance=MM(CLEARANCE)
    board.GetDesignSettings().m_TrackMinWidth=MM(.25)
    board.GetDesignSettings().m_CopperEdgeClearance=MM(.5)
    board.GetDesignSettings().m_MinSilkTextHeight=MM(.8)
    nets={}
    for name in sorted({p["net"] for part in config["parts"] for p in part["pads"] if p["net"]}):
        n=pcb.NETINFO_ITEM(board,name);board.Add(n);nets[name]=n
    outline=[kxy(v) for v in config["pcb"]["outline_xz"]]
    for a,b in zip(outline,outline[1:]+outline[:1]):line(board,a,b,pcb.Edge_Cuts,.05)
    pad_records=[]
    for part in config["parts"]:
        fp=pcb.FOOTPRINT(board);fp.SetReference(part["ref"]);fp.SetValue(part["value"])
        fp.SetFPID(pcb.LIB_ID("GunMouseHandSolder",part["ref"]));fp.SetPosition(vec(kxy(part["position_xz"])))
        fp.SetAttributes(pcb.FP_THROUGH_HOLE);fp.Reference().SetVisible(False);fp.Value().SetVisible(False)
        board.Add(fp)
        for info in part["pads"]:
            p=pcb.PAD(fp);p.SetNumber(info["number"]);p.SetPosition(vec(kxy(info["xz"])));p.SetSize(vec(info["size"]))
            p.SetDrillSize(vec(info["drill"]));p.SetAttribute(pcb.PAD_ATTRIB_PTH)
            p.SetShape(pcb.PAD_SHAPE_OVAL if info["shape"]=="oval" else pcb.PAD_SHAPE_CIRCLE)
            if abs(info["drill"][0]-info["drill"][1])>.001:p.SetDrillShape(pcb.PAD_DRILL_SHAPE_OBLONG)
            p.SetLayerSet(pcb.PAD.PTHMask())
            if info["net"]:p.SetNet(nets[info["net"]])
            # A surrounding signal fanout prevents meaningful thermal spokes
            # at this ground-wire hole. Its explicit ground neck is routed;
            # direct local pour avoids a nominal four-spoke isolated island.
            if part["ref"]=="J_GY" and info["number"]=="2":
                p.SetLocalZoneConnection(pcb.ZONE_CONNECTION_FULL)
            fp.Add(p);pad_records.append({**info,"ref":part["ref"],"xy":kxy(info["xz"]),"net_code":p.GetNetCode()})
        for i,info in enumerate(part.get("npth",[]),1):
            p=pcb.PAD(fp);p.SetNumber("");p.SetPosition(vec(kxy(info["xz"])));p.SetAttribute(pcb.PAD_ATTRIB_NPTH)
            p.SetSize(vec([info["d"]]*2));p.SetDrillSize(vec([info["d"]]*2));p.SetShape(pcb.PAD_SHAPE_CIRCLE);p.SetLayerSet(pcb.PAD.PTHMask());fp.Add(p)
            pad_records.append({"ref":part["ref"],"number":f"NPTH{i}","xy":kxy(info["xz"]),"net_code":-1,"drill":[info["d"]]*2,"size":[info["d"]]*2})
        # Fab/Courtyard rectangles are grouped in footprints, while hand-solder
        # labels remain board text to avoid a default reference on a drill pad.
        env=part["envelope"];xy=[kxy([x,z]) for x in env["x"] for z in env["z"]]
        xx=[v[0] for v in xy];yy=[v[1] for v in xy]
        corners=[[min(xx)-.25,min(yy)-.25],[max(xx)+.25,min(yy)-.25],[max(xx)+.25,max(yy)+.25],[min(xx)-.25,max(yy)+.25]]
        for a,b in zip(corners,corners[1:]+corners[:1]):
            item=pcb.PCB_SHAPE(fp);item.SetShape(pcb.SHAPE_T_SEGMENT);item.SetStart(vec(a));item.SetEnd(vec(b));item.SetLayer(pcb.F_CrtYd);item.SetWidth(MM(.05));fp.Add(item)
        if part["kind"]=="wirebank":
            for p in part["pads"]:
                x,y=kxy(p["xz"])
                # Pin numbers stay readable beside every real wire hole. The
                # supplied wiring table gives full names, avoiding text on
                # neighbouring pads in the narrow left-hand solder bank.
                add_text(board,p["number"],[x+1.8,y],.8)
                add_text(board,p["net"],[x-2.2,y],.8,pcb.F_Fab)
        elif part["kind"] in ("resistor","capacitor"):
            x,y=kxy(part["position_xz"]);add_text(board,part["ref"],[x,y-1.5],.55,pcb.F_Fab)
    for h in config["pcb"]["mount_holes"]:
        fp=pcb.FOOTPRINT(board);fp.SetReference(h["id"]);fp.SetValue("M2 clearance 2.4 mm");fp.SetPosition(vec(kxy(h["xz"])));fp.Reference().SetVisible(False);fp.Value().SetVisible(False)
        fp.SetFPID(pcb.LIB_ID("GunMouseHandSolder","Mount_M2"));fp.SetAttributes(pcb.FP_EXCLUDE_FROM_BOM | pcb.FP_EXCLUDE_FROM_POS_FILES);board.Add(fp)
        p=pcb.PAD(fp);p.SetPosition(vec(kxy(h["xz"])));p.SetAttribute(pcb.PAD_ATTRIB_NPTH);p.SetSize(vec([h["d"]]*2));p.SetDrillSize(vec([h["d"]]*2));p.SetShape(pcb.PAD_SHAPE_CIRCLE);p.SetLayerSet(pcb.PAD.PTHMask());fp.Add(p)
        pad_records.append({"ref":h["id"],"number":"","xy":kxy(h["xz"]),"net_code":-1,"drill":[h["d"]]*2,"size":[h["d"]]*2})
    add_text(board,"S3 THT CARRIER v1",[32,8],.8)
    add_text(board,"100k/100k SENSE",[39,82],.8)
    add_text(board,"BAT OFF BEFORE PC USB",[38,85.5],.8)
    return board,nets,pad_records,outline


class Router:
    """Two-layer grid router with real net owners and drill/via keepouts.

    The completed KiCad board is subjected to KiCad's independent DRC; this
    raster router is an implementation aid, not the electrical pass criterion.
    """
    def __init__(self,board,nets,pads,outline):
        self.board,self.nets,self.pads,self.outline=board,nets,pads,outline
        xx=[v[0] for v in outline];yy=[v[1] for v in outline]
        self.x0,self.y0=min(xx),min(yy);self.w=math.ceil((max(xx)-self.x0)/GRID)+1;self.h=math.ceil((max(yy)-self.y0)/GRID)+1
        self.owner=np.zeros((2,self.h,self.w),dtype=np.int16);self.hole_keepout=np.zeros((self.h,self.w),dtype=bool)
        xs=self.x0+np.arange(self.w)*GRID;ys=self.y0+np.arange(self.h)*GRID;X,Y=np.meshgrid(xs,ys)
        inside=np.zeros_like(X,dtype=bool)
        for a,b in zip(outline,outline[1:]+outline[:1]):
            if (a[1]>0)!=(b[1]>0):pass
            if abs(b[1]-a[1])>1e-10:
                cond=((a[1]>Y)!=(b[1]>Y))&(X<(b[0]-a[0])*(Y-a[1])/(b[1]-a[1])+a[0]);inside^=cond
        edge_dist=np.full_like(X,1e6)
        for a,b in zip(outline,outline[1:]+outline[:1]):
            dx,dy=b[0]-a[0],b[1]-a[1];t=np.clip(((X-a[0])*dx+(Y-a[1])*dy)/(dx*dx+dy*dy),0,1)
            edge_dist=np.minimum(edge_dist,np.hypot(X-a[0]-t*dx,Y-a[1]-t*dy))
        self.owner[:,~(inside & (edge_dist>=.68))]=-1
        for p in pads:
            radius=max(p["size"])/2+TRACK_W/2+CLEARANCE+.18
            self.mark_disc(p["xy"],radius,int(p["net_code"] or -1),[0,1])
            self.mark_hole(p["xy"],max(p["drill"])/2+VIA_DRILL/2+.25+.18)
        self.route_records=[];self.via_count=0

    def point(self,xy):return (int(round((xy[0]-self.x0)/GRID)),int(round((xy[1]-self.y0)/GRID)))
    def xy(self,p):return [round(self.x0+p[0]*GRID,6),round(self.y0+p[1]*GRID,6)]

    def disc_cells(self,xy,r):
        cx,cy=self.point(xy);n=math.ceil(r/GRID)+1
        xmin,xmax=max(0,cx-n),min(self.w,cx+n+1);ymin,ymax=max(0,cy-n),min(self.h,cy+n+1)
        X,Y=np.meshgrid(self.x0+np.arange(xmin,xmax)*GRID,self.y0+np.arange(ymin,ymax)*GRID)
        return xmin,xmax,ymin,ymax,(X-xy[0])**2+(Y-xy[1])**2<=r*r

    def mark_disc(self,xy,r,owner,layers):
        x0,x1,y0,y1,mask=self.disc_cells(xy,r)
        for layer in layers:
            view=self.owner[layer,y0:y1,x0:x1]
            clash=mask&(view!=0)&(view!=owner)
            view[mask & ~clash]=owner;view[clash]=-1

    def mark_hole(self,xy,r):
        x0,x1,y0,y1,mask=self.disc_cells(xy,r);self.hole_keepout[y0:y1,x0:x1]|=mask

    def astar(self,start,end,net):
        allowed=(self.owner==0)|(self.owner==net)
        free_via=(~self.hole_keepout)&(distance_transform_edt(~(~allowed[0]))*GRID>.35)&(distance_transform_edt(~(~allowed[1]))*GRID>.35)
        sx,sy=self.point(start);gx,gy=self.point(end)
        # The exact endpoints are the real pad centres. A rounded grid centre
        # can land in conservative neighbouring envelopes; require both sides
        # of any such escape to be actual same-net pad material after DRC.
        starts=[(sx,sy,l) for l in (0,1) if allowed[l,sy,sx]]
        if not starts:raise RuntimeError(f"Pad-grid start blocked: {net}, {start}")
        def heuristic(x,y):
            dx,dy=abs(x-gx),abs(y-gy);return 10*max(dx,dy)+4*min(dx,dy)
        pq=[];cost={};prev={};counter=0
        for s in starts:cost[s]=0;heapq.heappush(pq,(heuristic(s[0],s[1]),counter,s));counter+=1
        moves=((1,0,10),(-1,0,10),(0,1,10),(0,-1,10),(1,1,14),(1,-1,14),(-1,1,14),(-1,-1,14))
        last=None
        while pq:
            _,_,node=heapq.heappop(pq);x,y,l=node;current=cost[node]
            if x==gx and y==gy:last=node;break
            for dx,dy,c in moves:
                nx,ny=x+dx,y+dy
                if not (0<=nx<self.w and 0<=ny<self.h) or not allowed[l,ny,nx]:continue
                if dx and dy and (not allowed[l,y,nx] or not allowed[l,ny,x]):continue
                nxt=(nx,ny,l);new=current+c
                if new<cost.get(nxt,1e12):cost[nxt]=new;prev[nxt]=node;heapq.heappush(pq,(new+heuristic(nx,ny),counter,nxt));counter+=1
            if free_via[y,x]:
                nxt=(x,y,1-l);new=current+75
                if new<cost.get(nxt,1e12):cost[nxt]=new;prev[nxt]=node;heapq.heappush(pq,(new+heuristic(x,y),counter,nxt));counter+=1
        if last is None:raise RuntimeError(f"No route net {net} {start}->{end}")
        path=[last]
        while path[-1] in prev:path.append(prev[path[-1]])
        return path[::-1]

    def add_track(self,a,b,layer,netname,width=TRACK_W):
        if math.dist(a,b)<.001:return
        t=pcb.PCB_TRACK(self.board);t.SetStart(vec(a));t.SetEnd(vec(b));t.SetWidth(MM(width));t.SetLayer(pcb.F_Cu if layer==0 else pcb.B_Cu);t.SetNet(self.nets[netname]);self.board.Add(t)

    def apply_path(self,path,start,end,netname):
        net=self.nets[netname].GetNetCode()
        self.add_track(start,self.xy(path[0]),path[0][2],netname)
        # Simplify collinear grid segments but retain every layer transition.
        run_start=path[0];previous=path[0];direction=None
        for node in path[1:]:
            x,y,l=node;px,py,pl=previous
            if l!=pl:
                self.add_track(self.xy(run_start),self.xy(previous),pl,netname)
                v=pcb.PCB_VIA(self.board);v.SetPosition(vec(self.xy(node)));v.SetViaType(pcb.VIATYPE_THROUGH);v.SetLayerPair(pcb.F_Cu,pcb.B_Cu);v.SetWidth(pcb.F_Cu,MM(VIA_D));v.SetWidth(pcb.B_Cu,MM(VIA_D));v.SetDrill(MM(VIA_DRILL));v.SetNet(self.nets[netname]);self.board.Add(v)
                self.via_count+=1;self.mark_disc(self.xy(node),VIA_D/2+TRACK_W/2+CLEARANCE+.18,net,[0,1]);self.mark_hole(self.xy(node),VIA_DRILL+.25+.18)
                run_start=node;direction=None
            else:
                d=(x-px,y-py)
                if direction is not None and d!=direction:self.add_track(self.xy(run_start),self.xy(previous),l,netname);run_start=previous
                direction=d
            self.mark_disc(self.xy(node),TRACK_W+CLEARANCE+.18,net,[l]);previous=node
        self.add_track(self.xy(run_start),self.xy(path[-1]),path[-1][2],netname)
        self.add_track(self.xy(path[-1]),end,path[-1][2],netname)
        self.route_records.append({"net":netname,"start_mm":start,"end_mm":end,"grid_steps":len(path)})

    def route(self):
        groups=defaultdict(list)
        for p in self.pads:
            if p["net_code"]>0 and p.get("net")!="GND":groups[p["net"]].append(p["xy"])
        # Small, local circuits first; global power last. This avoids carving
        # long power trunks across the switch/ADC fanout before it can escape.
        priority={n:i for i,n in enumerate(("JOY_SW","VBUS_DET","VBAT_ADC","TRIG","BTN_R","JOY_X","JOY_Y","TOUCH","TOUCH_ELECTRODE","SDA","SCL","VBUS_SHARED","BAT_RAW","BAT_SW","3V3"))}
        names=sorted(groups,key=lambda n:priority.get(n,100))
        for name in names:
            points=groups[name]
            connected={0};edges=[]
            while len(connected)<len(points):
                a,b=min(((a,b) for a in connected for b in range(len(points)) if b not in connected),key=lambda ab:math.dist(points[ab[0]],points[ab[1]]))
                edges.append((a,b));connected.add(b)
            for a,b in edges:
                path=self.astar(points[a],points[b],self.nets[name].GetNetCode());self.apply_path(path,points[a],points[b],name)
            print(f"Routed {name}: {len(edges)} connections",flush=True)
        # Adjacent signal fanouts can isolate the IMU ground thermal island.
        # Connect it to the broad ground-pour corridor at the board's rear edge.
        a=next(p["xy"] for p in self.pads if p["ref"]=="J_GY" and p["number"]=="2")
        b=[55.0,a[1]]
        self.apply_path(self.astar(a,b,self.nets["GND"].GetNetCode()),a,b,"GND")


def add_ground_zone(board,nets,outline):
    for layer in (pcb.F_Cu,pcb.B_Cu):
        z=pcb.ZONE(board);z.SetLayer(layer);z.SetNet(nets["GND"]);z.SetLocalClearance(MM(CLEARANCE));z.SetThermalReliefGap(MM(.25));z.SetThermalReliefSpokeWidth(MM(.3));z.SetPadConnection(pcb.ZONE_CONNECTION_THERMAL)
        poly=z.Outline();poly.NewOutline()
        for point in outline:poly.Append(MM(point[0]),MM(point[1]))
        board.Add(z)
    board.BuildConnectivity()
    # The loader initializes the native design-rule engine used by KiCad 9's
    # zone filler; filling a freshly constructed in-memory BOARD can crash.
    pcb.SaveBoard(str(BOARD_FILE),board)
    loaded=pcb.LoadBoard(str(BOARD_FILE));filler=pcb.ZONE_FILLER(loaded);filler.Fill(loaded.Zones())
    return loaded


def validate_electrical(config,board):
    """Check the manufactured pad/net contract and the intentional circuit.

    This does not simulate the purchased development board or substitute for
    schematic ERC. It fails fabrication when an actual board pad, circuit role,
    ADC divider, or reserved MCU pin disagrees with the functional contract.
    """
    expected={(part["ref"],p["number"]):p for part in config["parts"] for p in part["pads"]}
    actual={(fp.GetReference(),p.GetNumber()):p for fp in board.GetFootprints()
            for p in fp.Pads() if p.GetAttribute()==pcb.PAD_ATTRIB_PTH}
    errors=[]
    if set(actual)!=set(expected):errors.append("Missing or extra actual PTH pad")
    for key,info in expected.items():
        p=actual.get(key)
        if p is None:continue
        xy=[pcb.ToMM(p.GetPosition().x),pcb.ToMM(p.GetPosition().y)]
        drill=[pcb.ToMM(p.GetDrillSize().x),pcb.ToMM(p.GetDrillSize().y)]
        if p.GetNetname()!=info["net"]:errors.append(f"{key}: net mismatch")
        if math.dist(xy,kxy(info["xz"]))>.002:errors.append(f"{key}: position mismatch")
        if max(abs(a-b) for a,b in zip(drill,info["drill"]))>.002:errors.append(f"{key}: drill mismatch")
    mounts={fp.GetReference():fp for fp in board.GetFootprints() if fp.GetReference().startswith("H")}
    for hole in config["pcb"]["mount_holes"]:
        fp=mounts.get(hole["id"])
        ps=list(fp.Pads()) if fp else []
        if len(ps)!=1 or ps[0].GetAttribute()!=pcb.PAD_ATTRIB_NPTH:
            errors.append(f"{hole['id']}: missing NPTH mounting hole");continue
        p=ps[0];xy=[pcb.ToMM(p.GetPosition().x),pcb.ToMM(p.GetPosition().y)]
        if math.dist(xy,kxy(hole["xz"]))>.002 or abs(pcb.ToMM(p.GetDrillSize().x)-hole["d"])>.002:
            errors.append(f"{hole['id']}: mounting geometry mismatch")
    parts={p["ref"]:p for p in config["parts"]}
    counts={kind:sum(p["kind"]==kind for p in config["parts"]) for kind in {p["kind"] for p in config["parts"]}}
    if counts!={"resistor":8,"capacitor":7,"wirebank":8,"joystick":1,"microswitch":1}:errors.append("Wrong component counts")
    # Deliberately state the electrical intent separately from default_config.
    contract={
        "R_JOY":("3.3k","3V3","JOY_SW"),"R_RIGHT":("3.3k","3V3","BTN_R"),
        "R_TRIG":("3.3k","3V3","TRIG"),"R_TOUCH":("510","TOUCH_ELECTRODE","TOUCH"),
        "R_BAT_H":("100k","BAT_SW","VBAT_ADC"),"R_BAT_L":("100k","VBAT_ADC","GND"),
        "R_RAIL_H":("100k","VBUS_SHARED","VBUS_DET"),"R_RAIL_L":("100k","VBUS_DET","GND"),
        "C_JOY_X":("100n","JOY_X","GND"),"C_JOY_Y":("100n","JOY_Y","GND"),
        "C_JOY_SW":("100n","JOY_SW","GND"),"C_RIGHT":("100n","BTN_R","GND"),
        "C_TRIG":("100n","TRIG","GND"),"C_BAT":("100n","VBAT_ADC","GND"),
        "C_RAIL":("100n","VBUS_DET","GND"),
    }
    for ref,(value,a,b) in contract.items():
        part=parts.get(ref,{})
        if part.get("value")!=value or [p["net"] for p in part.get("pads",[])]!=[a,b]:errors.append(f"{ref}: circuit role mismatch")
    def bank(ref,nets):
        if [p["net"] for p in parts[ref]["pads"]]!=nets:errors.append(f"{ref}: bank order mismatch")
    bank("J_BAT",["BAT_RAW","GND"]);bank("J_SWITCH",["BAT_RAW","BAT_SW"])
    bank("J_MODULE_BAT",["BAT_SW","GND"]);bank("J_MODULE_RAIL",["VBUS_SHARED"])
    bank("J_GY",["3V3","GND","SCL","SDA"]);bank("J_TRIG",["GND","TRIG"])
    bank("J_TOUCH",["TOUCH_ELECTRODE","GND"])
    sw2={p["number"]:p["net"] for p in parts["SW2"]["pads"]}
    if sw2!={"1":"GND","2":"BTN_R","3":""}:errors.append("SW2: COM/NO/dummy mismatch")
    pinmap=config["firmware_pins"]
    if len(set(pinmap.values()))!=len(pinmap):errors.append("GPIO reused")
    if set(pinmap.values())&{0,3,19,20,43,44,45,46}:errors.append("Reserved GPIO used")
    if any(pinmap[n] not in range(1,11) for n in ("JOY_X","JOY_Y","VBAT_ADC","VBUS_DET")):errors.append("ADC not ADC1")
    if config["power"]["vbus_detection"]["mode"]!="adc_shared_rail_external_5v_inference":errors.append("Wrong shared rail detection role")
    for part in config["parts"]:
        if part["kind"]=="capacitor" and any(p["net"] in {"TOUCH","TOUCH_ELECTRODE"} for p in part["pads"]):errors.append("Touch parallel capacitor")
        if part["kind"]=="resistor" and part["ref"]!="R_TOUCH" and any(p["net"] in {"TOUCH","TOUCH_ELECTRODE"} for p in part["pads"]):errors.append("Touch pull resistor")
    if errors:raise RuntimeError("Electrical contract failed: "+"; ".join(errors))
    nets=defaultdict(list)
    for (ref,number),info in expected.items():
        if info["net"]:nets[info["net"]].append(f"{ref}.{number}")
    write_json(OUT/"circuit-netlist.json",{"config_sha256":digest(CONFIG),"nets":dict(sorted(nets.items())),
               "parts":[{"ref":p["ref"],"kind":p["kind"],"value":p["value"],"pins":{i["number"]:i["net"] for i in p["pads"]}} for p in config["parts"]],
               "external_connections":"wiring.csv; bought modules are connected by wires and are not fabricated on this board"})
    report={"status":"pass","config_sha256":digest(CONFIG),"actual_board_sha256":digest(BOARD_FILE),
            "actual_pth_count":len(actual),"net_count":len(nets),"actual_pad_net_position_drill_errors":0,"mount_holes_verified":4,
            "resistors":8,"capacitors":7,"gpio_unique_reserved_and_adc1_check":"pass",
            "divider_adc_v_at_4_2v_battery":2.1,"divider_adc_v_at_5_25v_rail":2.625,
            "divider_thevenin_ohm":50000,"divider_rc_ms":5,"divider_5tau_ms":25,
            "button_closed_current_ma":1,"button_rc_ms":.33,
            "schematic_erc":"Not performed: no KiCad schematic supplied; explicit circuit/net/pad contract and independent written review are provided",
            "prototype_checks":"Purchased module topology, B+/B- polarity, footprint fit, ADC calibration, LDO margin, charging, touch and contact stability"}
    write_json(OUT/"electrical-report.json",report)
    with (OUT/"wiring.csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.writer(f);writer.writerow(["Carrier reference","Pin","Net","Connect to","Global X mm","Global Z mm"])
        for part in config["parts"]:
            if part["kind"]!="wirebank":continue
            for p in part["pads"]:
                n=p["net"];destination=part.get("purpose","")
                if part["ref"]=="J_MCU":destination=f"SuperMini GPIO{pinmap[n]}" if n in pinmap else f"SuperMini {n} pin"
                elif part["ref"]=="J_GY":destination={"3V3":"GY-601N1 H2 VCC","GND":"GY-601N1 H2 GND","SCL":"GY-601N1 H2 SCL","SDA":"GY-601N1 H2 SDA"}[n]
                elif part["ref"]=="J_TRIG":destination="SS-01GL13 COM" if n=="GND" else "SS-01GL13 NO; NC unconnected"
                elif part["ref"]=="J_MODULE_BAT":destination="SuperMini dedicated B+" if n=="BAT_SW" else "SuperMini dedicated B-"
                elif part["ref"]=="J_MODULE_RAIL":destination="SuperMini 5V/shared VBUS pin, sense only"
                writer.writerow([part["ref"],p["number"],n,destination,*p["xz"]])
    return report


def assembly_map(config):
    # A physical-size vector drawing; unlike the KiCad copper preview it labels
    # every body and bank, and is useful for 1:1 paper fit checks before buying.
    ox,oy=5.0,5.0
    def point(xz):
        x,y=kxy(xz);return x-ox,y-oy
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="52mm" height="82mm" viewBox="0 0 52 82">',
         '<rect width="52" height="82" fill="white"/>']
    poly=" ".join(f"{x},{y}" for x,y in map(point,config["pcb"]["outline_xz"]))
    svg.append(f'<polygon points="{poly}" fill="#fafaf7" stroke="#222" stroke-width=".12"/>')
    palette={"resistor":"#ffe2ad","capacitor":"#c3dff8","wirebank":"#d7ead2","joystick":"#d9d9df","microswitch":"#d9d9df"}
    for part in config["parts"]:
        e=part["envelope"];a=point([max(e["x"]),max(e["z"])]);b=point([min(e["x"]),min(e["z"])])
        svg.append(f'<rect x="{a[0]}" y="{a[1]}" width="{b[0]-a[0]}" height="{b[1]-a[1]}" fill="{palette[part["kind"]]}" stroke="#777" stroke-width=".08"/>')
        x,y=point(part["position_xz"])
        size=.85
        if part["kind"]=="wirebank":
            tx=x+1.4 if x<10 else x-1.4;ty=y-1.4;anchor="start" if x<10 else "end"
            if part["ref"]=="J_MCU":ty=point(part["pads"][-1]["xz"])[1]+1.7
        elif part["kind"]=="capacitor":tx=x;ty=y-1.5;anchor="middle";size=.65
        elif part["kind"]=="microswitch":tx=x;ty=a[1]-.7;anchor="middle"
        else:tx=x;ty=y+.3;anchor="middle"
        svg.append(f'<text x="{tx}" y="{ty}" font-family="sans-serif" font-size="{size}" text-anchor="{anchor}">{escape(part["ref"])}</text>')
        for p in part["pads"]:
            x,y=point(p["xz"]);w,h=p["size"];dw,dh=p["drill"]
            svg.append(f'<ellipse cx="{x}" cy="{y}" rx="{w/2}" ry="{h/2}" fill="#b89148"/>')
            svg.append(f'<ellipse cx="{x}" cy="{y}" rx="{dw/2}" ry="{dh/2}" fill="white" stroke="#333" stroke-width=".08"/>')
            if part["kind"]=="wirebank":
                svg.append(f'<text x="{x+1.1}" y="{y+.25}" font-family="sans-serif" font-size=".65">{p["number"]}</text>')
        for p in part.get("npth",[]):
            x,y=point(p["xz"]);svg.append(f'<circle cx="{x}" cy="{y}" r="{p["d"]/2}" fill="white" stroke="#333" stroke-width=".10"/>')
    for h in config["pcb"]["mount_holes"]:
        x,y=point(h["xz"]);svg.append(f'<circle cx="{x}" cy="{y}" r="{h["d"]/2}" fill="white" stroke="#222" stroke-width=".12"/>')
        svg.append(f'<text x="{x+1.6}" y="{y+.3}" font-family="sans-serif" font-size=".9">{h["id"]}</text>')
    svg.extend(['<text x="29" y="77.2" font-family="sans-serif" font-size="1.1" text-anchor="middle">FR4 1.6mm | 52x82mm</text>',
                '<path d="M24 79H34M24 78.5V79.5M34 78.5V79.5" stroke="#222" stroke-width=".12"/>',
                '<text x="29" y="80.5" font-family="sans-serif" font-size=".8" text-anchor="middle">10mm ruler | print 100%</text>','</svg>'])
    (OUT/"carrier-assembly-map.svg").write_text("\n".join(svg)+"\n",encoding="utf-8")


def render_previews():
    if not shutil.which("inkscape"):return
    for name,kind,suffix in (("carrier-assembly-map","png",""),("carrier-assembly-map","pdf","-1to1"),("carrier-copper-preview","png","")):
        subprocess.run(["inkscape",str(OUT/f"{name}.svg"),f"--export-type={kind}",
                        f"--export-filename={OUT/f'{name}{suffix}.{kind}'}","--export-dpi=300"],
                       check=True,capture_output=True,text=True)


def export_files(config,board,router,pads):
    configure_default_netclass(board)
    pretty=OUT/"GunMouseHandSolder.pretty";pretty.mkdir(exist_ok=True)
    footprint_plugin=pcb.PCB_IO_MGR.PluginFind(pcb.PCB_IO_MGR.KICAD_SEXP)
    for fp in board.GetFootprints():footprint_plugin.FootprintSave(str(pretty),fp)
    (OUT/"fp-lib-table").write_text('(fp_lib_table\n  (version 7)\n  (lib (name "GunMouseHandSolder")(type "KiCad")(uri "${KIPRJMOD}/GunMouseHandSolder.pretty")(options "")(descr "Generated hand-solder carrier footprints"))\n)\n',encoding="utf-8")
    pcb.SaveBoard(str(BOARD_FILE),board)
    electrical=validate_electrical(config,board)
    assembly_map(config)
    write_json(OUT/"carrier-layout.json",{"pcb":config["pcb"],"all_pads":pads,"config_sha256":digest(CONFIG),"routed_connections":router.route_records,"vias":router.via_count})
    with (OUT/"BOM.csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.writer(f);writer.writerow(["Reference","Value / Type","Qty","Assembly","Purchase / Fit Requirement","Nets / Purpose"])
        for part in config["parts"]:
            writer.writerow([part["ref"],part["value"],1,"Hand-solder THT" if part["kind"]!="wirebank" else "Solder labelled wires",
                             part["envelope_basis"],part.get("purpose",part.get("assembly",""))])
    gerber=OUT/"Gerber";gerber.mkdir(exist_ok=True)
    for old_file in gerber.iterdir():
        if old_file.is_file() and old_file.name.startswith("gun-mouse-supermini-carrier"):old_file.unlink()
    drc_cmd=["kicad-cli","pcb","drc","--format","json","--output",str(OUT/"drc-report.json"),str(BOARD_FILE)]
    completed=subprocess.run(drc_cmd,check=True,capture_output=True,text=True);print(completed.stdout.strip(),flush=True)
    drc=json.loads((OUT/"drc-report.json").read_text())
    if drc.get("violations") or drc.get("unconnected_items"):
        # Do not leave a newly generated fabrication archive after a failed
        # check; the report and native board remain available for correction.
        (OUT/"gun-mouse-supermini-carrier-Gerber.zip").unlink(missing_ok=True)
        raise RuntimeError("Fabrication blocked: KiCad DRC violations or unconnected items; inspect drc-report.json")
    commands=[
        ["kicad-cli","pcb","export","gerbers","--layers","F.Cu,B.Cu,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts","--output",str(gerber)+"/",str(BOARD_FILE)],
        ["kicad-cli","pcb","export","drill","--output",str(gerber)+"/",str(BOARD_FILE)],
        ["kicad-cli","pcb","export","svg","--mode-single","--fit-page-to-board","--exclude-drawing-sheet","--layers","F.Cu,B.Cu,F.Silkscreen,Edge.Cuts","--output",str(OUT/"carrier-copper-preview.svg"),str(BOARD_FILE)],
    ]
    for cmd in commands:
        completed=subprocess.run(cmd,check=True,capture_output=True,text=True)
        print(completed.stdout.strip(),flush=True)
    with zipfile.ZipFile(OUT/"gun-mouse-supermini-carrier-Gerber.zip","w",zipfile.ZIP_DEFLATED) as z:
        for p in sorted(gerber.iterdir()):
            if p.is_file():z.write(p,p.name)
    with zipfile.ZipFile(OUT/"gun-mouse-supermini-carrier-Gerber.zip") as z:
        # Seven selected fabrication layers, one combined Excellon drill file,
        # and KiCad's automatically generated Gerber job metadata.
        extensions={Path(name).suffix for name in z.namelist()}
        if len(z.namelist())!=9 or extensions!={".gtl",".gbl",".gto",".gbo",".gts",".gbs",".gm1",".drl",".gbrjob"} or z.testzip() is not None:
            raise RuntimeError("Fabrication archive content check failed")
    render_previews()
    report={"config_sha256":digest(CONFIG),"board_sha256":digest(BOARD_FILE),"pcb_size_mm":config["pcb"]["max_size_mm"],
            "factory_smt":False,"pads":len(pads),"routed_connections":len(router.route_records),"vias":router.via_count,
            "drc_violations":len(drc.get("violations",[])),"drc_unconnected":len(drc.get("unconnected_items",[])),
            "drc_warning_types":sorted({v["type"] for v in drc.get("violations",[]) if v.get("severity")=="warning"}),
            "drc_error_types":sorted({v["type"] for v in drc.get("violations",[]) if v.get("severity")=="error"}),
            "electrical_contract":"electrical-report.json","actual_pth_count":electrical["actual_pth_count"],
            "fabrication_ready":True,"fabrication_scope":"Carrier PCB only; prototype module topology and physical fit checks remain necessary",
            "schematic_parity":"No KiCad schematic supplied; actual PTHs checked against circuit/net/pad contract, independent source review provided",
            "boundary":"DRC verifies board geometry and routing; real module power topology, physical lead fit and solder workmanship require prototype checks"}
    write_json(OUT/"build-report.json",report);print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    products=[BOARD_FILE,BOARD_FILE.with_suffix(".kicad_pro"),CONFIG,OUT/"gun-mouse-supermini-carrier-Gerber.zip",
              OUT/"BOM.csv",OUT/"wiring.csv",OUT/"circuit-netlist.json",OUT/"drc-report.json",OUT/"electrical-report.json",
              OUT/"carrier-layout.json",OUT/"build-report.json",OUT/"carrier-assembly-map.svg"]
    write_json(OUT/"fabrication-manifest.json",{"config_sha256":digest(CONFIG),"board_sha256":digest(BOARD_FILE),
               "generator_sha256":digest(Path(__file__)),"kicad_version":pcb.Version(),
               "files":{str(p.relative_to(HERE)):digest(p) for p in products}})


def main():
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group();mode.add_argument("--config-only",action="store_true");mode.add_argument("--validate-existing",action="store_true",help="Check and re-export the existing native board without rebuilding geometry");args=parser.parse_args()
    if args.validate_existing:
        config=json.loads(CONFIG.read_text());layout=json.loads((OUT/"carrier-layout.json").read_text())
        if layout["config_sha256"]!=digest(CONFIG):raise RuntimeError("Existing board layout configuration is stale")
        board=pcb.LoadBoard(str(BOARD_FILE));router=SimpleNamespace(route_records=layout["routed_connections"],via_count=layout["vias"])
        export_files(config,board,router,layout["all_pads"]);return
    config=default_config();write_json(CONFIG,config);OUT.mkdir(parents=True,exist_ok=True)
    if args.config_only:
        print(json.dumps({"config":str(CONFIG),"parts":len(config["parts"]),"pins":config["firmware_pins"],"pcb":config["pcb"]},ensure_ascii=False,indent=2));return
    board,nets,pads,outline=new_board(config);router=Router(board,nets,pads,outline);router.route();board=add_ground_zone(board,nets,outline);export_files(config,board,router,pads)


if __name__=="__main__":main()
