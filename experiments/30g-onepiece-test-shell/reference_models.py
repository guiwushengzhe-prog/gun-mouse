"""Same-source hand-solder carrier references, in assembly coordinates (mm).

The carrier outline and drills are exact design geometry. Component and module
boxes are conservative dimensional envelopes, not measured component solids.
This distinction is preserved in the machine-readable verification report.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V = cq.Vector


def box(x0, x1, y0, y1, z0, z1):
    if min(x1-x0, y1-y0, z1-z0) <= 0:
        raise ValueError(f"Non-positive box dimensions: {(x0,x1,y0,y1,z0,z1)}")
    return cq.Solid.makeBox(x1-x0, y1-y0, z1-z0, V(x0,y0,z0))


def cyl_y(x, z, radius, y0, y1):
    return cq.Solid.makeCylinder(radius, y1-y0, V(x,y0,z), V(0,1,0))


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def board_spec(cfg):
    """Use the carrier schema; compatibility with old names is explicit."""
    return cfg.get("pcb", cfg.get("board"))


def mount_holes(cfg):
    return board_spec(cfg)["mount_holes"]


def _hole_xz(hole):
    return hole.get("xz", hole.get("position_xz"))


def _drill(x, z, dimensions, y0, y1):
    """True round/capsule drill; drill dimensions are global X/Z widths."""
    dx, dz = map(float, dimensions)
    if min(dx, dz) <= 0:
        raise ValueError(f"Invalid drill dimensions: {dimensions}")
    r = min(dx, dz)/2
    if abs(dx-dz) < 1e-9:
        return cyl_y(x,z,r,y0,y1)
    if dx > dz:
        half = (dx-dz)/2
        return (box(x-half,x+half,y0,y1,z-r,z+r)
                .fuse(cyl_y(x-half,z,r,y0,y1),cyl_y(x+half,z,r,y0,y1))).clean()
    half = (dz-dx)/2
    return (box(x-r,x+r,y0,y1,z-half,z+half)
            .fuse(cyl_y(x,z-half,r,y0,y1),cyl_y(x,z+half,r,y0,y1))).clean()


def _envelope_bounds(part, envelope, top, back):
    """Return explicit above-board and trimmed solder-lead boxes.

    x/z are global assembly bounds, avoiding any implicit rotation convention.
    A full-height rear bounding prism is conservative and is labelled as such;
    individual metal leads are not reconstructed from body-library bounds.
    """
    x0,x1 = envelope["x"]
    z0,z1 = envelope["z"]
    result = []
    height = envelope.get("y_above_board",0)
    if isinstance(height,list):
        a,b = height
    else:
        a,b = 0,float(height)
    if b>a:
        result.append(("top",[x0,x1,top+a,top+b,z0,z1]))
    return result


def build_references(cfg=None, assembly_cfg=None):
    """Return exact bare carrier and conservative physical references.

    assembly_cfg.reference_boxes maps a ref name to six assembly XYZ bounds or
    {bounds:[...], provenance:..., kind:...}. battery and dev_board are required
    for a final assembly check. Missing dimensions are errors, never defaults.
    """
    carrier_path = HERE/"carrier-config.json"
    assembly_path = HERE/"open-frame-config.json"
    cfg = cfg or _load(carrier_path)
    assembly_cfg = assembly_cfg or _load(assembly_path)
    pcb_cfg = board_spec(cfg)
    if not pcb_cfg:
        raise ValueError("Carrier config requires pcb")
    top = float(pcb_cfg["top_face_y"])
    thickness = float(pcb_cfg["thickness"])
    back = top-thickness
    outline = pcb_cfg["outline_xz"]
    face = cq.Face.makeFromWires(cq.Wire.makePolygon([V(x,back,z) for x,z in outline],close=True))
    pcb = cq.Solid.extrudeLinear(face,V(0,thickness,0))
    drill_records = []
    for hole in pcb_cfg["mount_holes"]:
        x,z = _hole_xz(hole)
        d = float(hole["d"])
        pcb = pcb.cut(_drill(x,z,[d,d],back-.2,top+.2))
        drill_records.append({"ref":hole["id"],"kind":"mount","xz":[x,z],"drill_mm":[d,d]})
    envelopes = []
    for part in cfg.get("parts",[]):
        for pad in part.get("pads",[]):
            if not pad.get("drill"):
                continue
            x,z = pad["xz"]
            dimensions = pad["drill"]
            if isinstance(dimensions,(int,float)):
                dimensions=[dimensions,dimensions]
            pcb=pcb.cut(_drill(x,z,dimensions,back-.2,top+.2))
            drill_records.append({"ref":part["ref"],"pad":pad.get("number"),"kind":"footprint",
                                  "xz":[x,z],"drill_mm":dimensions})
        for hole in part.get("npth",[]):
            x,z=hole["xz"]
            dimensions=hole["drill"] if "drill" in hole else [hole["d"],hole["d"]]
            pcb=pcb.cut(_drill(x,z,dimensions,back-.2,top+.2))
            drill_records.append({"ref":part["ref"],"kind":"npth","xz":[x,z],"drill_mm":dimensions})
        body_envelopes=part.get("envelopes",[part["envelope"]] if part.get("envelope") else [])
        for index,envelope in enumerate(body_envelopes):
            if envelope.get("kind")=="cylinder_y":
                x,z=envelope["xz"]
                a,b=envelope["y_above_board"]
                shape=cyl_y(x,z,envelope["radius"],top+a,top+b)
                r=envelope["radius"]
                bb=[x-r,x+r,top+a,top+b,z-r,z+r]
                candidates=[("top",bb,shape)]
            else:
                candidates=[(side,bb,box(*bb)) for side,bb in _envelope_bounds(part,envelope,top,back)]
            for side,bb,shape in candidates:
                envelopes.append({"shape":shape,"ref":part["ref"],"sub_envelope":index,"side":side,
                                  "board_group":"carrier","bounds_mm":bb,"conservative":True,
                                  "provenance":envelope.get("source",part.get("geometry_provenance",part.get("metadata",{})))})
        # Rear solder envelopes follow the actual pin centres, not a full-body
        # rear prism. The local maximum diameter covers hand-soldered pad fillets;
        # trimmed height is an explicit assembly limit, never measured geometry.
        below=part.get("envelope",{}).get("lead_below_board",0)
        if isinstance(below,list):
            below=max(below)
        if below:
            for pad in part.get("pads",[]):
                if not pad.get("drill"):
                    continue
                x,z=pad["xz"]
                diameter=max(2.0,*pad.get("size",[2.0,2.0]))
                r=diameter/2
                shape=cyl_y(x,z,r,back-float(below),back)
                envelopes.append({"shape":shape,"ref":part["ref"],"pad":pad.get("number"),"side":"back",
                                  "board_group":"carrier","bounds_mm":[x-r,x+r,back-float(below),back,z-r,z+r],
                                  "conservative":True,"provenance":"Per-pad hand-soldered fillet envelope; cut leads to configured maximum height"})
    pcb=pcb.clean()
    if not pcb.isValid() or len(pcb.Solids())!=1:
        raise ValueError("Carrier reference must be one valid connected solid")
    references={"pcb_board":pcb}
    physical_metadata={}
    for name,spec in assembly_cfg.get("reference_boxes",{}).items():
        spec={"bounds":spec} if isinstance(spec,list) else spec
        bb=spec["bounds"]
        references[name]=box(*bb)
        physical_metadata[name]={**assembly_cfg.get("module_metadata",{}).get(name,{}),
                                 **spec,"conservative_dimensional_envelope":True}
    for envelope in assembly_cfg.get("module_envelopes",[]):
        if envelope["board_group"] not in references:
            raise ValueError(f"Module envelope references missing board {envelope['board_group']}")
        bb=envelope["bounds"]
        envelopes.append({"shape":box(*bb),"ref":envelope["ref"],"side":envelope["side"],
                          "board_group":envelope["board_group"],"bounds_mm":bb,"conservative":True,
                          "provenance":envelope.get("provenance","Assumed module assembly envelope")})
    # Reconstruct the specified solder-lug trigger switch from its separate
    # nominal-dimension builder. Flexible actuation lever is deliberately absent.
    if (HERE/"trigger_holder.py").exists():
        from trigger_holder import switch_rigid, switch_body_tolerance_envelope, HOLES
        references["trigger_switch"]=switch_rigid()
        physical_metadata["trigger_switch"]={"kind":"nominal datasheet rigid switch/lugs with true mount holes",
            "source":"trigger_holder.py / Omron SS-01GL13 drawing","measured_component_step":False,
            "flexible_actuation_lever_included":False}
        shape=switch_body_tolerance_envelope()
        # Mount screws locate the installed switch; retain its actual through
        # holes instead of interpreting the conservative body box as filler.
        # Minimum nominal drill 2.35 mm is deliberately used for both bores.
        for x,z in HOLES:
            shape=shape.cut(cyl_y(x,z,2.35/2,-3.7,3.7))
        b=shape.BoundingBox()
        envelopes.append({"shape":shape,"ref":"SS01GL13-body-tolerance","side":"all",
            "board_group":"trigger_switch","bounds_mm":[b.xmin,b.xmax,b.ymin,b.ymax,b.zmin,b.zmax],
            "conservative":True,"provenance":"Omron unmarked +/-0.4 mm body envelope, installed and located by two mount screws; known through bores at minimum 2.35 mm subtracted; flexible lever excluded"})
    required={"battery","dev_board"}
    missing=required-set(references)
    if missing:
        raise ValueError(f"Missing physical reference boxes: {sorted(missing)}")
    source_files=[p for p in (carrier_path,assembly_path,Path(__file__),HERE/"trigger_holder.py") if p.exists()]
    references["component_envelopes"]=envelopes
    references["metadata"]={
        "units":"mm","coordinate_system":"Assembly X forward, Y left, Z up",
        "pcb":"Carrier-config outline and every mount/PTH/NPTH drill; no legacy EVT-A daughter PCB",
        "pcb_outline_xz":outline,"pcb_thickness_mm":thickness,"pcb_top_face_y_mm":top,
        "footprint_drills":drill_records,"physical_references":physical_metadata,
        "routing_vias_not_reconstructed":True,
        "routing_via_limit":"Electrical 0.3 mm routing vias are not material-subtracted; mechanical board reference is conservative",
        "component_envelope_limit":"Conservative body/solder-lead boxes; no measured switch/joystick moving solid",
        "config_input_sha256":{
            "carrier":hashlib.sha256(json.dumps(cfg,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            "assembly":hashlib.sha256(json.dumps(assembly_cfg,ensure_ascii=False,sort_keys=True).encode()).hexdigest()},
        "config_inputs_match_files":{
            "carrier":carrier_path.exists() and cfg==_load(carrier_path),
            "assembly":assembly_path.exists() and assembly_cfg==_load(assembly_path)},
        "sources_sha256":{str(p.relative_to(ROOT)):_digest(p) for p in source_files},
        "not_verified":["Module manufacturer variants and actual connector heights","Battery protection board / lead protrusions",
                        "Wire bending / connector strain relief","Switch actuation point and actual joystick motion",
                        "Printed shrinkage and resin strength"]}
    return references


if __name__=="__main__":
    refs=build_references()
    summary={key:{"valid":shape.isValid(),"solid_count":len(shape.Solids()),"volume_mm3":round(shape.Volume(),3)}
             for key,shape in refs.items() if isinstance(shape,cq.Shape)}
    print(json.dumps({"geometry":summary,"metadata":refs["metadata"]},ensure_ascii=False,indent=2))
