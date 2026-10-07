"""Check same-coordinate hand-solder assembly and report explicit limits.

BRep intersections check designed print solids, exact carrier holes and assumed
physical envelopes. A pass cannot certify real resin strength or component fit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from itertools import combinations
from functools import lru_cache
from pathlib import Path

import cadquery as cq

from reference_models import HERE, ROOT, board_spec, build_references, box, cyl_y

V = cq.Vector
EPS_VOLUME = 1e-4
EPS_DISTANCE = 1e-5


@lru_cache(maxsize=4096)
def bounds(shape):
    b=shape.BoundingBox()
    return (b.xmin,b.xmax,b.ymin,b.ymax,b.zmin,b.zmax)


def volume_overlap(a,b):
    ab,bb=bounds(a),bounds(b)
    if any(ab[i+1]<bb[i] or bb[i+1]<ab[i] for i in (0,2,4)):
        return 0.0
    return float(a.intersect(b).Volume())


def shape_pair(a,b):
    ab,bb=bounds(a),bounds(b)
    if any(ab[i+1]<bb[i] or bb[i+1]<ab[i] for i in (0,2,4)):
        return {"overlap_mm3":0.0,"clear_of_volume_interference":True}
    intersection=a.intersect(b)
    value=float(intersection.Volume())
    result={"overlap_mm3":round(value,6),"clear_of_volume_interference":value<=EPS_VOLUME}
    if value>EPS_VOLUME:
        result["intersection_bounds_mm"]=_round_vector(bounds(intersection))
    return result


def _round_vector(v):
    return [round(float(x),4) for x in v]


def _axis(spec):
    axis=V(*spec["axis"])
    if axis.Length<=0:
        raise ValueError("Fastener axis cannot be zero")
    return axis.multiply(1/axis.Length)


def _hex_nut(origin,axis,af=4.0,thickness=1.6,angle=30.0):
    """True M2 hexagonal nut envelope with 2 mm clearance bore.

    angle is in the transverse local plane. For Y screws this plane is XZ;
    for X screws it is YZ. Default 30deg gives vertices in the same convention
    as the frame's polygon pockets; caller can explicitly override.
    """
    # Deterministic right-handed transverse basis avoids an arbitrary OCC roll.
    if abs(axis.y)>.9:
        u=V(1,0,0)
    elif abs(axis.x)>.9:
        u=V(0,1,0)
    else:
        u=V(1,0,0)
    u=(u-axis.multiply(u.dot(axis))).normalized()
    w=axis.cross(u).normalized()
    r=af/math.sqrt(3)
    vertices=[origin+u.multiply(r*math.cos(math.radians(angle+60*i)))
              +w.multiply(r*math.sin(math.radians(angle+60*i))) for i in range(6)]
    face=cq.Face.makeFromWires(cq.Wire.makePolygon(vertices,close=True))
    outer=cq.Solid.extrudeLinear(face,axis.multiply(thickness))
    bore=cq.Solid.makeCylinder(1.0,thickness+.2,origin-axis.multiply(.1),axis)
    return outer.cut(bore).clean()


def fastener_shapes(spec):
    """M2 cup-head screw, true hex nut(s), and straight 1.5 mm Allen access.

    Shaft length excludes the head. Ø4×2.1 mm head safely includes nominal
    Ø3.8×2 mm ISO4762. Tool is a Ø2 mm straight clearance cylinder; the handle
    and L-key bend are not included. Nuts are explicit solids, not just length
    arithmetic. A staged tool check can name parts removed before adjustment.
    """
    seat,axis=V(*spec["seat"]),_axis(spec)
    length=float(spec["length"])
    head_d=float(spec.get("head_d",4.0))
    head_h=float(spec.get("head_h",2.1))
    tool_d=float(spec.get("tool_d",2.0))
    tool_length=float(spec.get("tool_length",12.0))
    shapes={"shaft":cq.Solid.makeCylinder(1.0,length,seat,axis),
            "head":cq.Solid.makeCylinder(head_d/2,head_h,seat-axis.multiply(head_h),axis)}
    tool_end=seat-axis.multiply(head_h)
    shapes["tool"]=cq.Solid.makeCylinder(tool_d/2,tool_length,tool_end-axis.multiply(tool_length),axis)
    nuts=spec.get("nuts")
    if nuts is None and "nut_near_from_seat" in spec:
        nuts=[{"near_from_seat":spec["nut_near_from_seat"],
               "thickness":spec.get("nut_thickness",1.6),"af":spec.get("nut_af",4.0),
               "angle":spec.get("nut_angle",30.0)}]
    for index,nut in enumerate(nuts or []):
        shapes[f"nut_{index+1}"]=_hex_nut(seat+axis.multiply(float(nut["near_from_seat"])),axis,
                                          float(nut.get("af",4.0)),float(nut.get("thickness",1.6)),
                                          float(nut.get("angle",30.0)))
    return shapes


def _fixed_refs(refs):
    return {k:v for k,v in refs.items() if isinstance(v,cq.Shape)}


def _allowed_envelope_contact(contacts,part,envelope):
    return ((part,envelope["ref"]) in contacts
            or (part,envelope["ref"],envelope.get("sub_envelope")) in contacts)


def _contact_region(pair,envelope,regions):
    """Name an explicit moving-contact region; keep the envelope hit visible."""
    intersection=pair.get("intersection_bounds_mm")
    if not intersection:
        return None
    for region in regions:
        if region["ref"]!=envelope["ref"]:
            continue
        if "sub_envelope" in region and region["sub_envelope"]!=envelope.get("sub_envelope"):
            continue
        bb=region["bounds"]
        if all(intersection[i]>=bb[i]-1e-4 and intersection[i+1]<=bb[i+1]+1e-4 for i in (0,2,4)):
            return {k:v for k,v in region.items() if k!="bounds"}|{"bounds_mm":bb}
    return None


def _pcb_clamps(parts,refs,cfg):
    board=board_spec(cfg)
    top=float(board["top_face_y"])
    back=top-float(board["thickness"])
    frame=parts["frame"]
    result={}
    for hole in board["mount_holes"]:
        ident=hole["id"]
        x,z=hole.get("xz",hole.get("position_xz"))
        proposed=f"pcb_clamp_{ident}"
        clamp_name=hole.get("clamp_part",proposed if proposed in parts else "control_bridge")
        clamp=parts.get(clamp_name)
        outer_r=float(hole.get("support_probe_radius",2.5))
        inner_r=float(hole["d"])/2+.05
        annulus=cyl_y(x,z,outer_r,back-.1,top+.1).cut(cyl_y(x,z,inner_r,back-.2,top+.2))
        pcb_local=refs["pcb_board"].intersect(annulus)
        front_band=annulus.intersect(box(x-3,x+3,top,top+.1,z-3,z+3))
        back_band=annulus.intersect(box(x-3,x+3,back-.1,back,z-3,z+3))
        back_volume=volume_overlap(frame,back_band)
        front_volume=volume_overlap(clamp,front_band) if clamp else 0.0
        back_gap=frame.distance(pcb_local) if pcb_local.Volume() else None
        front_gap=clamp.distance(pcb_local) if clamp and pcb_local.Volume() else None
        no_crush=(volume_overlap(frame,pcb_local)<=EPS_VOLUME and clamp is not None
                  and volume_overlap(clamp,pcb_local)<=EPS_VOLUME)
        result[ident]={"clamp_part":clamp_name,
                       "rear_contact_gap_mm":None if back_gap is None else round(back_gap,6),
                       "front_contact_gap_mm":None if front_gap is None else round(front_gap,6),
                       "rear_contact_band_mm3":round(back_volume,6),"front_contact_band_mm3":round(front_volume,6),
                       "board_volume_not_crushed":no_crush,
                       "both_faces_supported_nominally":bool(no_crush and back_volume>.01 and front_volume>.01
                                                               and back_gap<=EPS_DISTANCE and front_gap<=EPS_DISTANCE),
                       "note":"Nominal contact only; gently tighten M2 nuts, PCB/resin tolerance requires first print"}
    return result


def _fasteners(parts,refs,fasteners):
    result={}
    for spec in fasteners or []:
        ident=spec["id"]
        shapes=fastener_shapes(spec)
        removed_parts=set(spec.get("tool_removed_parts",[]))
        removed_refs=set(spec.get("tool_removed_references",[]))
        thread_parts=set(spec.get("threaded_parts",[]))
        entry={"length_mm":spec["length"],"seat_mm":spec["seat"],"axis":spec["axis"],
               "approved_length":spec["length"] in (10,20),"fixed_reference_collisions":{},
               "printed_part_collisions":{},"component_envelope_collisions":[],
               "tool_access_stage":{"removed_parts":sorted(removed_parts),"removed_references":sorted(removed_refs),
                                    "reason":spec.get("tool_access_note","All installed parts present"),
                                    "limitation":"Straight Ø2 mm path; no L-key bend/handle or nut-wrench swept geometry"}}
        for name,obstacle in _fixed_refs(refs).items():
            for kind,shape in shapes.items():
                if kind=="tool" and name in removed_refs:
                    continue
                pair=shape_pair(shape,obstacle)
                if not pair["clear_of_volume_interference"]:
                    entry["fixed_reference_collisions"][f"{kind}/{name}"]=pair
        for name,obstacle in parts.items():
            for kind,shape in shapes.items():
                if kind=="tool" and name in removed_parts:
                    continue
                pair=shape_pair(shape,obstacle)
                if not pair["clear_of_volume_interference"]:
                    entry["printed_part_collisions"][f"{kind}/{name}"]={**pair,
                        "intended_thread_engagement":kind=="shaft" and name in thread_parts}
        for envelope in refs["component_envelopes"]:
            for kind,shape in shapes.items():
                if kind=="tool" and envelope["ref"] in removed_refs:
                    continue
                pair=shape_pair(shape,envelope["shape"])
                if not pair["clear_of_volume_interference"]:
                    entry["component_envelope_collisions"].append({"kind":kind,"ref":envelope["ref"],
                                                                   "side":envelope["side"],"pad":envelope.get("pad"),
                                                                   "sub_envelope":envelope.get("sub_envelope"),**pair})
        nuts=spec.get("nuts")
        if nuts is None and "nut_near_from_seat" in spec:
            nuts=[{"near_from_seat":spec["nut_near_from_seat"],"thickness":spec.get("nut_thickness",1.6)}]
        entry["nut_engagement"]=[]
        for nut in nuts or []:
            near=float(nut["near_from_seat"])
            thickness=float(nut.get("thickness",1.6))
            available=float(spec["length"])-near
            entry["nut_engagement"].append({"nut_near_from_seat_mm":near,"available_length_mm":round(available,4),
                                            "nut_thickness_mm":thickness,"tip_projection_mm":round(available-thickness,4),
                                            "full_nut_engagement":available>=thickness-1e-6})
        unexplained=[v for v in entry["printed_part_collisions"].values() if not v["intended_thread_engagement"]]
        entry["exact_clearance_pass"]=(entry["approved_length"] and not entry["fixed_reference_collisions"]
                                         and not unexplained and all(n["full_nut_engagement"] for n in entry["nut_engagement"]))
        result[ident]=entry
    return result


def assembly_sweep(reference,offset):
    """Exact translation sweep of a uniform axis-aligned prism or drilled PCB.

    This is only exact when the shape is a uniform extrusion along this axis.
    A component-filled or nonuniform assembly must use a conservative box sweep.
    """
    active=[i for i,value in enumerate(offset) if abs(value)>1e-8]
    if len(active)!=1:
        raise ValueError("Assembly sweep requires exactly one axis of translation")
    index=active[0]
    distance=float(offset[index])
    bb=bounds(reference)
    thickness=bb[2*index+1]-bb[2*index]
    faces=cq.Workplane().add(reference).faces("<"+"XYZ"[index]).vals()
    if len(faces)!=1:
        raise ValueError("Assembly sweep requires one planar base face")
    base=faces[0]
    if distance<0:
        base=base.translate(V(*offset))
    direction=[0.,0.,0.]
    direction[index]=thickness+abs(distance)
    return cq.Solid.extrudeLinear(base,V(*direction))


def assembly_bbox_sweep(reference,offset):
    if sum(abs(v)>1e-8 for v in offset)!=1:
        raise ValueError("Assembly bbox sweep requires one translation axis")
    bb=list(bounds(reference))
    for i,value in enumerate(offset):
        bb[2*i]+=min(0,value)
        bb[2*i+1]+=max(0,value)
    return box(*bb)


@lru_cache(maxsize=512)
def _uniform_axis_extrusion(shape,index):
    """Recognize a real uniform prism by reconstructing and comparing BRep."""
    faces=cq.Workplane().add(shape).faces("<"+"XYZ"[index]).vals()
    if len(faces)!=1 or faces[0].geomType()!="PLANE":
        return False
    bb=bounds(shape)
    direction=[0.,0.,0.]
    direction[index]=bb[index*2+1]-bb[index*2]
    candidate=cq.Solid.extrudeLinear(faces[0],V(*direction))
    a,b=float(candidate.Volume()),float(shape.Volume())
    if abs(a-b)>EPS_VOLUME:
        return False
    return float(candidate.intersect(shape).Volume())>=b-EPS_VOLUME


def exact_inverse_uniform_sweep(reference,obstacle,translation):
    """Exact reverse obstacle sweep for a uniform solid or box partition.

    A+t intersects B iff A intersects B-t. Orthogonal planar solids can be
    partitioned into uniform prisms using their vertex X/Z (or transverse)
    coordinates; all cells cover the exact original BRep volume. This proves
    sliding surface tangency without an invented clearance or deleted body.
    """
    active=[i for i,v in enumerate(translation) if abs(v)>1e-8]
    if len(active)!=1:
        return None
    index=active[0]
    reverse=[-v for v in translation]
    pieces=[]
    if _uniform_axis_extrusion(obstacle,index):
        pieces=[obstacle]
    else:
        for face in obstacle.Faces():
            if face.geomType()!="PLANE":
                return None
            n=face.normalAt()
            if sum(abs(v)>1e-7 for v in (n.x,n.y,n.z))!=1:
                return None
        transverse=[i for i in range(3) if i!=index]
        vertices=[v.toTuple() for v in obstacle.Vertices()]
        coordinates=[sorted({round(p[i],9) for p in vertices}) for i in transverse]
        if (len(coordinates[0])-1)*(len(coordinates[1])-1)>144:
            return None
        bb=bounds(obstacle)
        for lo0,hi0 in zip(coordinates[0],coordinates[0][1:]):
            for lo1,hi1 in zip(coordinates[1],coordinates[1][1:]):
                cell=list(bb)
                cell[2*transverse[0]:2*transverse[0]+2]=[lo0,hi0]
                cell[2*transverse[1]:2*transverse[1]+2]=[lo1,hi1]
                piece=obstacle.intersect(box(*cell))
                if piece.Volume()<=EPS_VOLUME:
                    continue
                if len(piece.Solids())!=1 or not _uniform_axis_extrusion(piece,index):
                    return None
                pieces.append(piece)
        if abs(sum(p.Volume() for p in pieces)-obstacle.Volume())>EPS_VOLUME:
            raise AssertionError("Inverse sweep partition does not cover obstacle volume")
    checks=[]
    for piece in pieces:
        swept=assembly_sweep(piece,reverse)
        checks.append(shape_pair(reference,swept))
    return {"method":"Exact reverse translation sweep of BRep-verified uniform obstacle prisms",
        "reverse_translation_mm":reverse,"uniform_partition_cell_count":len(pieces),
        "prism_swept_intersections":checks,
        "entire_linear_stroke_clear":all(c["clear_of_volume_interference"] for c in checks),
        "sliding_zero_area_surface_contact_permitted":True}


def partitioned_translation_clearance(reference,obstacle,translation,planes):
    """Prove all pairs of exact material partitions across declared interfaces."""
    def partition(shape):
        pieces=[(shape,{})]
        for number,plane in enumerate(planes):
            axis=int(plane["axis"])
            coordinate=float(plane["at"])
            subdivided=[]
            for piece,sides in pieces:
                bb=list(bounds(piece))
                cuts=[bb[2*axis],coordinate,bb[2*axis+1]] if bb[2*axis]<coordinate<bb[2*axis+1] else [bb[2*axis],bb[2*axis+1]]
                for lo,hi in zip(cuts,cuts[1:]):
                    cell=bb.copy()
                    cell[2*axis:2*axis+2]=[lo,hi]
                    material=piece.intersect(box(*cell))
                    solids=[solid for solid in material.Solids() if solid.Volume()>EPS_VOLUME]
                    if solids:
                        solid=solids[0] if len(solids)==1 else cq.Compound.makeCompound(solids)
                        subdivided.append((solid,{**sides,number:-1 if (lo+hi)/2<coordinate else 1}))
            pieces=subdivided
        if abs(sum(p.Volume() for p,_ in pieces)-shape.Volume())>EPS_VOLUME:
            raise AssertionError("Material partition did not preserve full input volume")
        return pieces
    moving,fixed=partition(reference),partition(obstacle)
    checks={}
    for i,(piece,moving_sides) in enumerate(moving):
        for j,(solid,fixed_sides) in enumerate(fixed):
            separation=[plane for n,plane in enumerate(planes)
                if moving_sides[n]!=fixed_sides[n] and abs(translation[int(plane["axis"])])<1e-10]
            name=f"moving_partition_{i}/fixed_partition_{j}"
            if separation:
                checks[name]={"entire_linear_stroke_clear":True,
                    "method":"Exact opposing material halfspaces; translation is parallel to their shared plane",
                    "separation_planes":separation,"moving_bounds_mm":bounds(piece),"fixed_bounds_mm":bounds(solid),
                    "limitation":"Nominal BRep boundary contact is permitted; assembly force/shrinkage not certified"}
            else:
                checks[name]=continuous_translation_clearance(piece,{"fixed_partition":solid},translation)
    return {"method":"Exact BRep material partition; separation-plane or continuous distance/inverse-sweep proof for every pair",
        "interface_planes":planes,"moving_volume_mm3":reference.Volume(),"fixed_volume_mm3":obstacle.Volume(),
        "moving_partition_volume_mm3":sum(p.Volume() for p,_ in moving),
        "fixed_partition_volume_mm3":sum(p.Volume() for p,_ in fixed),"partition_pair_certificates":checks,
        "entire_linear_stroke_clear":all(c["entire_linear_stroke_clear"] for c in checks.values())}


def continuous_translation_clearance(reference,obstacles,translation,max_depth=12):
    """Prove a complete linear stroke with a Lipschitz distance bound.

    At each interval midpoint, the maximum displacement to either endpoint is
    half the interval travel. If separation is at least that displacement,
    no pose in the entire interval can penetrate the fixed obstacle. Otherwise
    subdivide; an overlap fails and a depth-limited ambiguity stays unproved.
    Tangency is permitted. This supports a nonuniform/filleted moving solid,
    unlike the uniform-extrusion assembly_sweep helper.
    """
    vector=V(*translation)
    travel=vector.Length
    if travel<=0:
        raise ValueError("Motion proof requires nonzero translation")
    output={}
    for name,obstacle in obstacles.items():
        rb,ob=bounds(reference),bounds(obstacle)
        swept=list(rb)
        for i,v in enumerate(translation):
            swept[2*i]+=min(0,v)
            swept[2*i+1]+=max(0,v)
        planes=[i for i in range(3) if swept[2*i+1]<=ob[2*i]+1e-7 or ob[2*i+1]<=swept[2*i]+1e-7]
        if planes:
            output[name]={"continuous_clearance_proved":True,"certificate_interval_count":0,
                "certified_intervals":[],"failures_or_unproved_intervals":[],
                "whole_stroke_separation_plane_certificate":{"axis_indices":planes,"moving_swept_bounds_mm":swept,
                    "fixed_bounds_mm":ob,"permitted_numeric_boundary_tolerance_mm":1e-7}}
            continue
        leaves=[]
        failed=[]
        def check(lo,hi,depth):
            if failed:
                return
            middle=(lo+hi)/2
            moving=reference.translate(vector.multiply(middle))
            displacement=travel*(hi-lo)/2
            distance=float(moving.distance(obstacle))
            if distance+EPS_DISTANCE>=displacement:
                leaves.append({"fraction_interval":[round(lo,7),round(hi,7)],
                               "midpoint_distance_mm":round(distance,7),
                               "maximum_displacement_mm":round(displacement,7)})
                return
            pair=shape_pair(moving,obstacle)
            if not pair["clear_of_volume_interference"]:
                failed.append({"fraction":middle,"meaning":"Actual midpoint interference",**pair})
                return
            if depth>=max_depth:
                failed.append({"fraction_interval":[lo,hi],"meaning":"Distance bound remains inconclusive",
                               "midpoint_distance_mm":distance,"maximum_displacement_mm":displacement})
                return
            check(lo,middle,depth+1)
            check(middle,hi,depth+1)
        check(0.,1.,0)
        alternate=None
        unresolved=failed
        if failed and all(f["meaning"]=="Distance bound remains inconclusive" for f in failed):
            alternate=exact_inverse_uniform_sweep(reference,obstacle,translation)
            if alternate and alternate["entire_linear_stroke_clear"]:
                unresolved=[]
        output[name]={"continuous_clearance_proved":not unresolved,"certificate_interval_count":len(leaves),
                      "certified_intervals":leaves,"failures_or_unproved_intervals":unresolved}
        if alternate:
            output[name]["alternate_exact_inverse_sweep_certificate"]=alternate
            output[name]["distance_bound_ambiguity_resolved_by_exact_sweep"]=failed
    return {"translation_mm":translation,"method":"Adaptive midpoint separation >= maximum interval displacement",
            "entire_linear_stroke_clear":all(value["continuous_clearance_proved"] for value in output.values()),
            "obstacles":output,"limitation":"Nominal CAD surfaces and dimensional references; resin fit/force still untested"}


def _motion_shape(shape,state):
    if "translation" in state:
        shape=shape.translate(V(*state["translation"]))
    if "rotate" in state:
        rotation=state["rotate"]
        origin=V(*rotation["origin"])
        shape=shape.rotate(origin,origin+V(*rotation["axis"]),rotation["angle"])
    return shape


def _component_obstacles(refs,groups,exclusions=None):
    result={}
    for index,envelope in enumerate(refs["component_envelopes"]):
        if envelope["board_group"] not in groups:
            continue
        shape=envelope["shape"]
        for exclusion in exclusions or []:
            if exclusion["ref"]!=envelope["ref"]:
                continue
            if "sub_envelope" in exclusion and exclusion["sub_envelope"]!=envelope.get("sub_envelope"):
                continue
            if "pad" in exclusion and exclusion["pad"]!=envelope.get("pad"):
                continue
            shape=shape.cut(box(*exclusion["bounds"]))
        if shape.Volume()>EPS_VOLUME:
            result[f"envelope:{envelope['ref']}:{envelope['side']}:{index}"]=shape
    return result


def verify_parts(parts,cfg=None,fasteners=None,motions=None,allowed_part_overlaps=None,
                 allowed_envelope_contacts=None,assembly_paths=None,assembly_cfg=None,
                 accessory_shapes=None,accessory_allowed_contacts=None):
    """Return JSON evidence; geometry errors and conservative hits stay visible.

    motions check explicit states. Use densely sampled states for rotations;
    a pure translational full stroke can add sweep_translation to continuously
    check the complete stroke, not just the two endpoints. A motion may select
    source_reference instead of a printed part (e.g. joystick shaft envelope).
    accessory_shapes are optional strap/wire envelopes; contact exemptions are
    explicit pairs and never imply an actual bend-radius or strain-relief proof.
    """
    cfg=cfg or json.loads((HERE/"carrier-config.json").read_text(encoding="utf-8"))
    refs=build_references(cfg,assembly_cfg)
    fixed=_fixed_refs(refs)
    allowed_pairs={frozenset(pair) for pair in (allowed_part_overlaps or [])}
    contacts=set(tuple(pair) for pair in (allowed_envelope_contacts or []))
    report={"checked_at_utc":datetime.now(timezone.utc).isoformat(),
            "cadquery_version":cq.__version__,
            "method":"BRep intersection of exact print/carrier designs and explicitly assumed dimensional reference boxes",
            "reference_provenance":refs["metadata"],"printed_parts":{},"printed_pair_interference":{},
            "fixed_reference_interference":{},"component_envelope_hits":[],"motion_checks":{},"assembly_paths":{}}
    for name,shape in parts.items():
        report["printed_parts"][name]={"valid":bool(shape.isValid()),"solids":len(shape.Solids()),
                                         "volume_mm3":round(shape.Volume(),4),"bounds_mm":_round_vector(bounds(shape))}
    for (an,a),(bn,b) in combinations(parts.items(),2):
        pair=shape_pair(a,b)
        if not pair["clear_of_volume_interference"]:
            report["printed_pair_interference"][f"{an}/{bn}"]={**pair,"explicitly_allowed":frozenset((an,bn)) in allowed_pairs}
    for name,shape in parts.items():
        for ref_name,reference in fixed.items():
            pair=shape_pair(shape,reference)
            if not pair["clear_of_volume_interference"]:
                report["fixed_reference_interference"][f"{name}/{ref_name}"]=pair
        for envelope in refs["component_envelopes"]:
            pair=shape_pair(shape,envelope["shape"])
            if not pair["clear_of_volume_interference"]:
                report["component_envelope_hits"].append({"part":name,"ref":envelope["ref"],"side":envelope["side"],**pair,
                                                         "sub_envelope":envelope.get("sub_envelope"),
                                                         "intended_contact":_allowed_envelope_contact(contacts,name,envelope),
                                                         "meaning":"Conservative static box overlap; exact component solid unavailable"})
    for state in motions or []:
        part_name=state.get("part")
        source_name=state.get("source_reference")
        moving=fixed[source_name] if source_name else parts[part_name]
        moving=_motion_shape(moving,state)
        method="Specified position/angle state; states do not prove the path between them"
        if "sweep_translation" in state:
            moving=assembly_sweep(moving,state["sweep_translation"])
            method="Continuous exact uniform-extrusion translation sweep"
        expected=state.get("expected_contact_parts",[])
        moving_refs=set(state.get("co_moving_references",[]))|{source_name}
        state_result={"printed":{},"reference_boards":{},"component_envelope_hits":[],
                      "expected_contact_parts":expected,"method":method,
                      "actual_moving_component_geometry_available":False if source_name else None}
        for name,obstacle in parts.items():
            if name!=part_name and name not in state.get("co_moving_parts",[]):
                state_result["printed"][name]=shape_pair(moving,obstacle)
        for name,obstacle in fixed.items():
            if name not in moving_refs:
                state_result["reference_boards"][name]=shape_pair(moving,obstacle)
        for envelope in refs["component_envelopes"]:
            if (envelope["ref"] in state.get("co_moving_envelopes",[])
                    or [envelope["ref"],envelope.get("sub_envelope")] in state.get("co_moving_envelope_sections",[])):
                continue
            pair=shape_pair(moving,envelope["shape"])
            if not pair["clear_of_volume_interference"]:
                region=_contact_region(pair,envelope,state.get("expected_envelope_regions",[]))
                state_result["component_envelope_hits"].append({"ref":envelope["ref"],"side":envelope["side"],
                    "sub_envelope":envelope.get("sub_envelope"),**pair,
                    "declared_actuation_region":region,
                    "intended_actuation_contact":envelope["ref"] in state.get("expected_envelope_contacts",[])
                        or [envelope["ref"],envelope.get("sub_envelope")] in state.get("expected_envelope_contact_sections",[])
                        or region is not None})
        printed_hits={name for name,value in state_result["printed"].items() if not value["clear_of_volume_interference"]}
        state_result["expected_contact_result"]=all(name in printed_hits for name in expected)
        state_result["no_unexpected_printed_collision"]=printed_hits.issubset(set(expected))
        state_result["reference_clearance"]=all(pair["clear_of_volume_interference"] for pair in state_result["reference_boards"].values())
        report["motion_checks"][state["name"]]=state_result
    if motions:
        progress={"partial_report":True,"checked_at_utc":datetime.now(timezone.utc).isoformat(),
            "printed_pair_interference":report["printed_pair_interference"],
            "fixed_reference_interference":report["fixed_reference_interference"],
            "unintended_component_envelope_hits":[h for h in report["component_envelope_hits"] if not h["intended_contact"]],
            "motion_failures":{name:m for name,m in report["motion_checks"].items()
                if not(m["expected_contact_result"] and m["no_unexpected_printed_collision"] and m["reference_clearance"])
                   or any(not hit["intended_actuation_contact"] for hit in m["component_envelope_hits"])}}
        (HERE/"generated/assembly-progress.json").write_text(json.dumps(progress,indent=2)+"\n")
        print(json.dumps({"static_and_motion_progress":{
            "fixed_hits":progress["fixed_reference_interference"],
            "envelope_hits":progress["unintended_component_envelope_hits"],
            "motion_failed_names":list(progress["motion_failures"])}}),flush=True)
    for path in assembly_paths or []:
        print("Checking assembly path: "+path["name"],flush=True)
        ref_name=path.get("reference",path.get("part"))
        if "parts" in path:
            shapes=[parts[name] for name in path["parts"]]
            shapes.extend(fixed[name] for name in path.get("moving_references",[]))
            for spec in fasteners or []:
                if spec["id"] in path.get("moving_fasteners",[]):
                    shapes.extend(shape for name,shape in fastener_shapes(spec).items() if name!="tool")
            reference=cq.Compound.makeCompound(shapes)
            ref_name=" + ".join(path["parts"]+path.get("moving_references",[])+path.get("moving_fasteners",[]))
        else:
            reference=parts[ref_name] if "part" in path else fixed[ref_name]
        if "pose_translation" in path:
            reference=reference.translate(V(*path["pose_translation"]))
        active=[i for i,value in enumerate(path["offset"]) if abs(value)>1e-8]
        if len(active)!=1:
            raise ValueError("Assembly path needs exactly one active axis")
        if path.get("sweep_method")=="adaptive_distance_bound":
            obstacles={name:parts[name] for name in path["obstacles"]}
            obstacles.update({name:fixed[name] for name in path.get("reference_obstacles",[])})
            obstacles.update(_component_obstacles(refs,path.get("component_obstacle_groups",[]),
                                                  path.get("component_obstacle_exclusions",[])))
            proof=continuous_translation_clearance(reference,obstacles,path["offset"])
            for name,result in proof["obstacles"].items():
                if result["continuous_clearance_proved"] or not path.get("interface_partition_planes"):
                    continue
                if not all(f["meaning"]=="Distance bound remains inconclusive" for f in result["failures_or_unproved_intervals"]):
                    continue
                certificate=partitioned_translation_clearance(reference,obstacles[name],path["offset"],path["interface_partition_planes"])
                result["exact_material_partition_certificate"]=certificate
                if certificate["entire_linear_stroke_clear"]:
                    result["distance_bound_ambiguity_resolved_by_partition"]=result["failures_or_unproved_intervals"]
                    result["failures_or_unproved_intervals"]=[]
                    result["continuous_clearance_proved"]=True
            proof["entire_linear_stroke_clear"]=all(v["continuous_clearance_proved"] for v in proof["obstacles"].values())
            report["assembly_paths"][path["name"]]={"reference":ref_name,"offset_mm":path["offset"],
                "method":proof["method"],"distance_bound_proof":proof,
                "obstacles_at_this_assembly_stage":list(obstacles),"collisions":{},
                "component_swept_envelope_hits":[],"clear":proof["entire_linear_stroke_clear"],
                "component_envelopes_included":bool(path.get("component_obstacle_groups")),
                "declared_moving_component_exclusion_windows":path.get("component_obstacle_exclusions",[]),
                "initial_assembly_pose_translation_mm":path.get("pose_translation",[0,0,0]),
                "limitation":"Assembly part proof excludes any not explicitly named components, flexible wiring and insertion force"}
            if not proof["entire_linear_stroke_clear"]:
                print(json.dumps({"assembly_path_failed":path["name"],"obstacles":{name:value["failures_or_unproved_intervals"]
                    for name,value in proof["obstacles"].items() if not value["continuous_clearance_proved"]}}),flush=True)
            continue
        uniform=(ref_name=="pcb_board" and active[0]==1) or ("part" not in path and "parts" not in path and ref_name not in ("pcb_board","trigger_switch"))
        swept=assembly_sweep(reference,path["offset"]) if uniform else assembly_bbox_sweep(reference,path["offset"])
        obstacles={name:parts[name] for name in path["obstacles"]}
        obstacles.update({name:fixed[name] for name in path.get("reference_obstacles",[])})
        for index,envelope in enumerate(refs["component_envelopes"]):
            if envelope["board_group"] in path.get("component_obstacle_groups",[]):
                obstacles[f"envelope:{envelope['ref']}:{envelope['side']}:{index}"]=envelope["shape"]
        collisions={name:shape_pair(swept,shape) for name,shape in obstacles.items()}
        envelope_hits=[]
        if path.get("include_component_envelopes"):
            for envelope in refs["component_envelopes"]:
                if envelope["board_group"]!=("carrier" if ref_name=="pcb_board" else ref_name):
                    continue
                component_sweep=assembly_sweep(envelope["shape"],path["offset"])
                for obstacle_name,obstacle in obstacles.items():
                    pair=shape_pair(component_sweep,obstacle)
                    if not pair["clear_of_volume_interference"]:
                        envelope_hits.append({"ref":envelope["ref"],"side":envelope["side"],"pad":envelope.get("pad"),
                                              "sub_envelope":envelope.get("sub_envelope"),"obstacle":obstacle_name,**pair})
        report["assembly_paths"][path["name"]]={"reference":ref_name,"offset_mm":path["offset"],
            "method":"Continuous uniform-extrusion swept volume" if uniform else "Conservative continuous swept bounding box",
            "bare_board_sweep_exact":ref_name=="pcb_board" and uniform,
            "obstacles_at_this_assembly_stage":list(obstacles),"collisions":collisions,
            "component_swept_envelope_hits":envelope_hits,
            "clear":all(pair["clear_of_volume_interference"] for pair in collisions.values()),
            "component_envelopes_included":bool(path.get("include_component_envelopes")),
            "limitation":"Module/battery boxes and component bounds are assumed; wiring and insertion force not included"}
    print("Assembly paths evaluated",flush=True)
    report["pcb_clamping"]=_pcb_clamps(parts,refs,cfg)
    report["fasteners"]=_fasteners(parts,refs,fasteners)
    report["accessory_checks"]={}
    accessory_contacts=set(tuple(pair) for pair in (accessory_allowed_contacts or []))
    for name,shape in (accessory_shapes or {}).items():
        hits={}
        for obstacle_name,obstacle in {**parts,**fixed}.items():
            pair=shape_pair(shape,obstacle)
            if not pair["clear_of_volume_interference"]:
                hits[obstacle_name]={**pair,"intended_contact":(name,obstacle_name) in accessory_contacts}
        envelope_hits=[]
        for envelope in refs["component_envelopes"]:
            pair=shape_pair(shape,envelope["shape"])
            if not pair["clear_of_volume_interference"]:
                envelope_hits.append({"ref":envelope["ref"],"side":envelope["side"],**pair,
                                      "intended_contact":_allowed_envelope_contact(accessory_contacts,name,envelope)})
        report["accessory_checks"][name]={"bounds_mm":_round_vector(bounds(shape)),"hits":hits,
            "component_envelope_hits":envelope_hits,
            "clear_except_intended_contacts":all(h["intended_contact"] for h in hits.values())
                and all(h["intended_contact"] for h in envelope_hits),
            "limitation":"Designed strap/wire envelope only; actual strap tightening/bend radius not certified"}
    report["exact_geometry_pass"]=(
        all(p["valid"] and p["solids"]==1 for p in report["printed_parts"].values())
        and not report["fixed_reference_interference"]
        and all(v["explicitly_allowed"] for v in report["printed_pair_interference"].values())
        and all(v["both_faces_supported_nominally"] for v in report["pcb_clamping"].values())
        and all(v["exact_clearance_pass"] for v in report["fasteners"].values())
        and all(v["clear"] for v in report["assembly_paths"].values())
        and all(v["expected_contact_result"] and v["no_unexpected_printed_collision"] and v["reference_clearance"]
                for v in report["motion_checks"].values())
        and all(v["clear_except_intended_contacts"] for v in report["accessory_checks"].values()))
    report["conservative_envelope_review_clear"]=(
        all(hit["intended_contact"] for hit in report["component_envelope_hits"])
        and all(not path["component_swept_envelope_hits"] for path in report["assembly_paths"].values())
        and all(not f["component_envelope_collisions"] for f in report["fasteners"].values())
        and all(all(h["intended_actuation_contact"] for h in m["component_envelope_hits"]) for m in report["motion_checks"].values()))
    report["check_coverage"]={"pcb_mounts":len(report["pcb_clamping"]),
        "socket_head_screws_and_hex_nuts":len(report["fasteners"]),
        "specified_motion_states_or_sweeps":list(report["motion_checks"]),
        "specified_insertion_paths":list(report["assembly_paths"]),
        "specified_strap_or_wire_envelopes":list(report["accessory_checks"]),
        "scope":"Pass flags apply only to listed geometry checks; omitted motion/assembly/accessories are not implicitly verified"}
    report["not_certified"]=["Resin strength / fatigue / drop or impact resistance",
        "Print-service billable weight, support material, shrinkage and dimensional tolerance",
        "Real module manufacturer variation and battery protection/lead protrusions",
        "Real switch actuation/lever/plunger geometry and joystick articulation",
        "Actual wire bending, solder protrusions, strap tension, insulation and assembly force",
        "L-key bend, driver handle and open-ended nut-wrench swept access"]
    return report


def _all_obstacles(parts,refs,excluded_parts=(),excluded_refs=(),excluded_sections=(),cutouts=None):
    obstacles={name:shape for name,shape in parts.items() if name not in excluded_parts}
    obstacles.update({name:shape for name,shape in _fixed_refs(refs).items() if name not in excluded_refs})
    excluded={tuple(v) for v in excluded_sections}
    for index,envelope in enumerate(refs["component_envelopes"]):
        if (envelope["ref"],envelope.get("sub_envelope")) in excluded:
            continue
        shape=envelope["shape"]
        for cut in cutouts or []:
            if cut["ref"]==envelope["ref"] and cut.get("sub_envelope")==envelope.get("sub_envelope"):
                shape=shape.cut(box(*cut["bounds"]))
        if shape.Volume()>EPS_VOLUME:
            obstacles[f"envelope:{envelope['ref']}:{index}"]=shape
    return obstacles


def complete_validation(parts,cfg=None,assembly_cfg=None,fasteners=None):
    """Reproducible full checks for this experiment, including explicit stages.

    Moving plunger, joystick shaft and lever are absent from manufacturer STEP.
    Their narrowly declared mating/actuation windows stay in the report; static
    body, solder fillets and all other hardware continue to be collision checked.
    """
    from trigger_parts import AXIS_Z,FACE_X,HEAD_K,TRAVEL,FIXED_NUT_X,JAM_NUT_X,screw_motion_envelope
    from trigger_holder import terminal_wire_envelope
    cfg=cfg or json.loads((HERE/"carrier-config.json").read_text(encoding="utf-8"))
    assembly_cfg=assembly_cfg or json.loads((HERE/"open-frame-config.json").read_text(encoding="utf-8"))
    if fasteners is None:
        from build_skeleton import fasteners as built_fasteners
        fasteners=built_fasteners()
    fasteners=[dict(s) for s in fasteners]
    refs=build_references(cfg,assembly_cfg)
    top=float(board_spec(cfg)["top_face_y"])
    contact={"id":"trigger_contact","seat":[FACE_X+HEAD_K,0,AXIS_Z],"axis":[1,0,0],"length":10,
             "nuts":[{"near_from_seat":x-FACE_X-HEAD_K,"angle":0} for x in (FIXED_NUT_X,JAM_NUT_X)],
             "tool_removed_parts":[name for name in parts if name!="trigger"],
             "tool_removed_references":list(_fixed_refs(refs))+[e["ref"] for e in refs["component_envelopes"]],
             "tool_access_note":"Contact adjustment on detached trigger at workbench; jam with thin 4 mm wrench, reinstall and gauge"}
    if not any(s["id"]=="trigger_contact" for s in fasteners):
        fasteners.append(contact)
    active={"ref":"SW2","sub_envelope":0,"bounds":[-31.45,-30.65,top+6.4,top+6.6,-3,-1],
            "provenance":"Local moving-plunger actuation window; conservative case box is not measured plunger/recess STEP"}
    motions=[]
    for travel in (0,TRAVEL/2,TRAVEL):
        motions.append({"name":f"trigger_travel_{travel:g}mm","part":"trigger","translation":[-travel,0,0],
                        "co_moving_parts":["touch_cover"]})
    for travel in (0,.4,.8):
        motions.append({"name":f"right_button_travel_{travel:g}mm","part":"right_cap","translation":[0,-travel,0],
                        "expected_envelope_contact_sections":[["SW2",1]],"expected_envelope_regions":[active]})
    pivot=[-33,top+7,23]
    for elevation in (0,.7):
        for press in (0,.9):
            for azimuth in range(0,360,45):
                radians=math.radians(azimuth)
                motions.append({"name":f"joystick_20deg_az{azimuth}_press{press:g}_shaftplus{elevation:g}",
                    "part":"joystick_cap","translation":[0,elevation-press,0],
                    "rotate":{"origin":pivot,"axis":[math.sin(radians),0,-math.cos(radians)],"angle":20},
                    "co_moving_envelope_sections":[["SW1",1]]})
    fixed_after_carrier=["battery","dev_board","pcb_board"]
    carrier_stops=["frame","supermini_clamp","pcb_clamp_H1","pcb_clamp_H4"]
    assembly_paths=[
        {"name":"battery_from_positive_Y","reference":"battery","offset":[0,40,0],"obstacles":["frame"]},
        {"name":"SuperMini_wired_from_positive_X","reference":"dev_board","offset":[40,0,0],
         "obstacles":["frame"],"reference_obstacles":["battery"],"include_component_envelopes":True},
        {"name":"populated_carrier_from_positive_Y_before_GY_holder","reference":"pcb_board","offset":[0,40,0],
         "obstacles":["frame","supermini_clamp"],"reference_obstacles":["battery","dev_board"],
         "component_obstacle_groups":["dev_board"],"include_component_envelopes":True},
        {"name":"GY_cradle_after_carrier_from_positive_Y","part":"imu_cradle","offset":[0,40,0],
         "sweep_method":"adaptive_distance_bound","obstacles":carrier_stops,
         "reference_obstacles":fixed_after_carrier,"component_obstacle_groups":["carrier","dev_board"]},
        {"name":"GY_module_from_positive_Y","reference":"imu","offset":[0,40,0],
         "obstacles":carrier_stops+["imu_cradle"],"reference_obstacles":fixed_after_carrier,
         "component_obstacle_groups":["carrier","dev_board"],"include_component_envelopes":True},
        {"name":"GL13_complete_holder_after_carrier_from_positive_Y","parts":["trigger_holder"],
         "moving_references":["trigger_switch"],"moving_fasteners":[s["id"] for s in fasteners if s["id"].startswith("trigger_switch")],
         "offset":[0,40,0],"sweep_method":"adaptive_distance_bound",
         "obstacles":carrier_stops+["imu_cradle","imu_clamp"],"reference_obstacles":fixed_after_carrier+["imu"],
         "component_obstacle_groups":["carrier","dev_board","imu"]},
        {"name":"right_cap_into_detached_bridge_from_positive_X_pressed_0.15mm","part":"right_cap","offset":[20,0,0],
         "pose_translation":[0,-.15,0],
         "sweep_method":"adaptive_distance_bound","obstacles":["control_bridge"]},
        {"name":"bridge_rightcap_keeper_workbench_subassembly_from_positive_Y","parts":["control_bridge","right_cap"],
         "moving_fasteners":["right_cap_keeper"],"offset":[0,40,0],"sweep_method":"adaptive_distance_bound",
         "obstacles":[name for name in parts if name not in ("control_bridge","right_cap","joystick_cap")],
         "reference_obstacles":fixed_after_carrier+["imu","trigger_switch"],
         "component_obstacle_groups":["carrier","dev_board","imu","trigger_switch"],
         "component_obstacle_exclusions":[active,{"ref":"SW2","sub_envelope":1,"bounds":[-40,-20,-2,8,-10,10],
            "provenance":"Moving switch plunger compresses during cap seating"}]},
        {"name":"trigger_contact_subassembly_from_positive_Y_with_gate_removed","parts":["trigger"],
         "interface_partition_planes":[{"axis":0,"at":0,"provenance":"Return-tooth right face and upper guide left face share the X=0 installation plane"}],
         "moving_fasteners":["trigger_contact"],"offset":[0,30,0],"sweep_method":"adaptive_distance_bound",
         "obstacles":[name for name in parts if name not in ("trigger","touch_cover","trigger_gate","control_bridge","right_cap","joystick_cap")],
         "reference_obstacles":list(_fixed_refs(refs)),
         "component_obstacle_groups":["carrier","dev_board","imu","trigger_switch"]},
        {"name":"trigger_gate_from_positive_Y","part":"trigger_gate","offset":[0,30,0],
         "sweep_method":"adaptive_distance_bound","obstacles":[name for name in parts if name not in ("trigger_gate","control_bridge","right_cap","joystick_cap")],
         "reference_obstacles":list(_fixed_refs(refs)),"component_obstacle_groups":["carrier","dev_board","imu","trigger_switch"]}]
    assembly_paths.extend([
        {"name":"SuperMini_front_clamp_from_positive_Y_before_carrier","part":"supermini_clamp","offset":[0,30,0],
         "sweep_method":"adaptive_distance_bound","obstacles":["frame"],"reference_obstacles":["dev_board","battery"],
         "component_obstacle_groups":["dev_board"]},
        {"name":"GY_front_clamp_from_positive_Y_after_module","part":"imu_clamp","offset":[0,30,0],
         "sweep_method":"adaptive_distance_bound","obstacles":carrier_stops+["imu_cradle"],
         "reference_obstacles":fixed_after_carrier+["imu"],"component_obstacle_groups":["carrier","dev_board","imu"]},
        {"name":"right_cap_workbench_release_0.15mm_after_side_insertion","part":"right_cap","offset":[0,-.15,0],
         "sweep_method":"adaptive_distance_bound","obstacles":["control_bridge"]}])
    accessories={"trigger_terminal_wire_corridor":terminal_wire_envelope()}
    for z in (-73,-43):
        outer=box(-55,-20.4,-18.8,-3.4,z-1.25,z+1.25)
        inner=box(-54.4,-21,-18.2,-4,z-1.5,z+1.5)
        accessories[f"battery_strap_z{z}"]=outer.cut(inner).clean()
        accessories[f"battery_strap_lock_z{z}"]=box(-48,-44,-22.5,-18.8,z-2,z+2)
    report=verify_parts(parts,cfg=cfg,assembly_cfg=assembly_cfg,fasteners=fasteners,motions=motions,
        allowed_envelope_contacts=[("right_cap","SW2",1),("joystick_cap","SW1",1)],assembly_paths=assembly_paths,
        accessory_shapes=accessories,accessory_allowed_contacts=[("trigger_terminal_wire_corridor","trigger_switch")])
    print("Full static/state/path checks completed",flush=True)
    linear={}
    for name,vector,exclude,sections,cutouts in (
        ("trigger_complete_4.1mm_stroke",[-TRAVEL,0,0],["trigger","touch_cover"],[],[]),
        ("right_button_complete_0.8mm_stroke",[0,-.8,0],["right_cap"],[["SW2",1]],[active])):
        part="trigger" if name.startswith("trigger") else "right_cap"
        obstacles=_all_obstacles(parts,refs,exclude,excluded_sections=sections,cutouts=cutouts)
        for spec in fasteners:
            if spec["id"]=="trigger_contact" and part=="trigger":
                continue
            for kind,shape in fastener_shapes(spec).items():
                if kind!="tool":
                    obstacles[f"hardware:{spec['id']}:{kind}"]=shape
        moving=parts[part]
        if part=="trigger":
            moving=cq.Compound.makeCompound([moving,parts["touch_cover"]]+[
                shape for kind,shape in fastener_shapes(contact).items() if kind!="tool"])
        linear[name]=continuous_translation_clearance(moving,obstacles,vector)
        linear[name]["declared_moving_component_exclusion_windows"]=cutouts
        print(name+": "+str(linear[name]["entire_linear_stroke_clear"]),flush=True)
    report["linear_motion_certificates"]=linear
    adjust_envelope=screw_motion_envelope()
    adjust_obstacles=_all_obstacles(parts,refs,excluded_parts=["trigger","touch_cover"])
    report["trigger_contact_all_adjustments_and_stroke"]={
        "adjustment_range_mm":[-1.5,2],"trigger_stroke_mm":TRAVEL,
        "method":"Exact uniform cylinder sweep covering Cartesian product of adjust/stroke ranges",
        "obstacles":{name:shape_pair(adjust_envelope,shape) for name,shape in adjust_obstacles.items()}}
    report["trigger_contact_all_adjustments_and_stroke"]["passed"]=all(
        pair["clear_of_volume_interference"] for pair in report["trigger_contact_all_adjustments_and_stroke"]["obstacles"].values())
    # Full azimuth cone for the shaft stem at the bridge ring. The short shaft
    # determines the lowest cap; a +0.7 mm long shaft raises it. Pivot is assumed.
    angle=math.radians(20)
    yl,yh=17.6,20
    radius=3.5/math.cos(angle)
    cone=cq.Solid.makeCone((yl-pivot[1])*math.tan(angle)+radius,
        (yh-pivot[1])*math.tan(angle)+radius,yh-yl,V(-33,yl,23),V(0,1,0))
    ring_intersection=shape_pair(cone,parts["control_bridge"])
    disk_low=pivot[1]+(25-.9-pivot[1])*math.cos(angle)-8*math.sin(angle)
    report["joystick_all_azimuth_bridge_envelope"]={"angle_deg":20,"center_push_worst_mm":.9,
        "assumed_pivot_y_mm":pivot[1],"stem_diameter_mm":7,"ring_cone_vs_bridge":ring_intersection,
        "cap_disk_lower_surface_min_y_mm":round(disk_low,6),"bridge_ring_top_y_mm":yh,
        "disk_clearance_mm":round(disk_low-yh,6),
        "passed":ring_intersection["clear_of_volume_interference"] and disk_low>yh,
        "limitation":"Analytic stem/disk envelope at bridge; actual pivot articulation and simultaneous press need first-print verification"}
    report["complete_validation_plan"]={"fasteners":fasteners,"motions":motions,"assembly_paths":assembly_paths,
        "accessories":{name:_round_vector(bounds(shape)) for name,shape in accessories.items()}}
    report["check_coverage"]["continuous_linear_motion_certificates"]=list(linear)
    report["check_coverage"]["joystick_all_azimuth_bridge_envelope"]=True
    report["exact_geometry_pass"] &= all(p["entire_linear_stroke_clear"] for p in linear.values())
    report["exact_geometry_pass"] &= report["joystick_all_azimuth_bridge_envelope"]["passed"]
    report["exact_geometry_pass"] &= report["trigger_contact_all_adjustments_and_stroke"]["passed"]
    report["complete_coverage"]=(len(parts)==13 and len(fasteners)==14 and len(motions)>=38
                                 and len(assembly_paths)>=13 and len(accessories)>=5)
    report["full_validation_pass"]=(report["exact_geometry_pass"] and report["conservative_envelope_review_clear"]
                                     and report["complete_coverage"])
    sources=[Path(__file__),HERE/"reference_models.py",HERE/"build_skeleton.py",HERE/"trigger_holder.py",HERE/"trigger_parts.py",
             HERE/"open-frame-config.json",HERE/"carrier-config.json",HERE/"pcb/gun-mouse-supermini-carrier.kicad_pcb",ROOT/"config/pcb-shell-v1.json",ROOT/"scripts/pcb_shell_v1/build_shell.py"]
    report["design_sources_sha256"]={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.exists()}
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts-dir",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--fasteners",type=Path)
    parser.add_argument("--static-only",action="store_true",help="Omit full motion/insertion/accessory plan; explicitly incomplete coverage")
    parser.add_argument("--carrier-config",type=Path,default=HERE/"carrier-config.json")
    parser.add_argument("--assembly-config",type=Path,default=HERE/"open-frame-config.json")
    args=parser.parse_args()
    volume_manifest=args.parts_dir/"part-volumes.json"
    if volume_manifest.exists():
        names=json.loads(volume_manifest.read_text(encoding="utf-8"))
        paths=[args.parts_dir/(name+".step") for name in names]
    else:
        paths=[p for p in sorted(args.parts_dir.glob("*.step"))
               if "debug" not in p.stem and not p.stem.startswith(("assembly-","onepiece-","reference-"))]
    parts={p.stem:cq.importers.importStep(str(p)).val() for p in paths}
    fasteners=json.loads(args.fasteners.read_text(encoding="utf-8")) if args.fasteners else None
    cfg=json.loads(args.carrier_config.read_text(encoding="utf-8"))
    assembly_cfg=json.loads(args.assembly_config.read_text(encoding="utf-8"))
    report=(verify_parts(parts,cfg=cfg,assembly_cfg=assembly_cfg,fasteners=fasteners) if args.static_only
            else complete_validation(parts,cfg=cfg,assembly_cfg=assembly_cfg,fasteners=fasteners))
    report["parts_source_sha256"]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(args.output),"exact_geometry_pass":report["exact_geometry_pass"],
                      "conservative_envelope_review_clear":report["conservative_envelope_review_clear"],
                      "full_validation_pass":report.get("full_validation_pass")}))
    if not args.static_only and not report["full_validation_pass"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
