"""Pack assembly-coordinate print parts into one cut-apart resin print solid.

``pack_parts(parts, out_dir=None, ...)`` never imports transformed baseline STLs.
Each part is rotated independently, parked outside the primary part, and joined
with low-volume sprues. Forward and inverse transforms are saved explicitly.
The assembly STEP retains the original independent assembly-coordinate solids.

Automatic sprue attachments use low exterior section edges. Supply explicit
``connection_points`` in assembly coordinates and/or ``protected_regions`` for
functional surfaces that must stay untouched. A model-specific reviewer must
confirm automatic contact locations before manufacture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

import cadquery as cq

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "generated"
V = cq.Vector

DEFAULT_ROTATIONS = {
    "frame": [((1, 0, 0), 90)],
    "trigger": [((1, 0, 0), 90)],
    "control_bridge": [((1, 0, 0), -90)],
    "trigger_gate": [((1, 0, 0), -90)],
    "touch_cover": [((1, 0, 0), -90)],
    "right_cap": [((1, 0, 0), -90)],
    "joystick_cap": [((1, 0, 0), -90)],
}


def _bounds(s):
    b = s.BoundingBox()
    return [b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax]


def _eye():
    return [[float(i == j) for j in range(4)] for i in range(4)]


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4))
             for j in range(4)] for i in range(4)]


def _rotation(axis, degrees):
    norm = math.sqrt(sum(float(x) ** 2 for x in axis))
    if norm <= 0:
        raise ValueError("Rotation axis must be nonzero")
    x, y, z = (float(a) / norm for a in axis)
    t = math.radians(degrees)
    c, s, q = math.cos(t), math.sin(t), 1 - math.cos(t)
    return [[c+x*x*q, x*y*q-z*s, x*z*q+y*s, 0],
            [y*x*q+z*s, c+y*y*q, y*z*q-x*s, 0],
            [z*x*q-y*s, z*y*q+x*s, c+z*z*q, 0],
            [0, 0, 0, 1]]


def _translation(delta):
    m = _eye()
    for i, x in enumerate(delta):
        m[i][3] = float(x)
    return m


def _point(m, p):
    return [sum(m[i][j] * float(p[j]) for j in range(3)) + m[i][3]
            for i in range(3)]


def _inverse(m):
    out = _eye()
    for i in range(3):
        for j in range(3):
            out[i][j] = m[j][i]
        out[i][3] = -sum(m[j][i] * m[j][3] for j in range(3))
    return out


def _rotate(s, rotations):
    m = _eye()
    for axis, angle in rotations:
        s = s.rotate((0, 0, 0), tuple(axis), angle)
        m = _mul(_rotation(axis, angle), m)
    return s, m


def _cylinder(a, b, radius, extension=0):
    direction = V(*b) - V(*a)
    if direction.Length < 1e-7:
        raise ValueError("Zero-length sprue")
    unit = direction.normalized()
    return cq.Solid.makeCylinder(radius, direction.Length + 2 * extension,
                                 V(*a) - unit * extension, unit)


def _section_candidates(s, side):
    """Choose actual exterior section points rather than a bounding-box corner."""
    b = _bounds(s)
    height = b[5] - b[4]
    z = b[4] + min(.65, height / 2)
    section = cq.Workplane("XY").add(s).section(z).val()
    pts = []
    for edge in section.Edges():
        pts.extend(p.toTuple() for p in edge.sample(24)[0])
    if not pts:
        raise ValueError("No low exterior section for a sprue attachment")
    # Trying multiple exterior points lets protected functional regions exclude
    # an entire first-choice face without silently dropping its protection.
    extreme = min(p[0] for p in pts) if side == "left" else max(p[0] for p in pts)
    pts = [p for p in pts if abs(p[0] - extreme) < .25]
    return sorted(pts, key=lambda p: p[1])


def _transform_shape(s, rotations, translation):
    for axis, angle in rotations:
        s = s.rotate((0, 0, 0), tuple(axis), angle)
    return s.translate(tuple(translation))


def check_stl(path):
    """Independent exported-STL topology/volume check without optional packages."""
    data = Path(path).read_bytes()
    count = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else 0
    triangles = []
    if len(data) == 84 + 50*count:
        for i in range(count):
            row = struct.unpack_from("<12fH", data, 84+50*i)
            triangles.append([row[3:6], row[6:9], row[9:12]])
    else:
        points = []
        for line in data.decode("ascii").splitlines():
            terms = line.split()
            if terms and terms[0] == "vertex":
                points.append(tuple(map(float, terms[1:4])))
        if not points or len(points) % 3:
            raise ValueError("Malformed STL triangle stream")
        triangles = [points[i:i+3] for i in range(0, len(points), 3)]
    vertex_ids, edges, parents = {}, defaultdict(list), list(range(len(triangles)))

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    volume, degenerate = 0., 0
    for face_id, tri in enumerate(triangles):
        ids = []
        for point in tri:
            key = tuple(round(float(v)/1e-5) for v in point)
            if key not in vertex_ids:
                vertex_ids[key] = len(vertex_ids)
            ids.append(vertex_ids[key])
        if len(set(ids)) != 3:
            degenerate += 1
            continue
        for a, b in zip(ids, ids[1:]+ids[:1]):
            key = (min(a,b), max(a,b))
            edges[key].append((face_id, a<b))
        a, b, c = tri
        volume += (a[0]*(b[1]*c[2]-b[2]*c[1])
                   + a[1]*(b[2]*c[0]-b[0]*c[2])
                   + a[2]*(b[0]*c[1]-b[1]*c[0])) / 6
    boundary, nonmanifold, winding = 0, 0, 0
    for entries in edges.values():
        if len(entries) == 1:
            boundary += 1
        elif len(entries) > 2:
            nonmanifold += 1
        elif entries[0][1] == entries[1][1]:
            winding += 1
        first = entries[0][0]
        for other, _ in entries[1:]:
            parents[find(other)] = find(first)
    bodies = len({find(i) for i in range(len(triangles))})
    return {"watertight": not (boundary or nonmanifold or degenerate),
            "winding_consistent": not winding, "connected_bodies": bodies,
            "volume_mm3": abs(volume), "triangle_count": len(triangles),
            "merged_vertex_count": len(vertex_ids), "boundary_edges": boundary,
            "nonmanifold_edges": nonmanifold, "degenerate_triangles": degenerate,
            "vertex_merge_tolerance_mm": 1e-5}


def pack_parts(parts: Mapping[str, cq.Shape], out_dir=None, *,
               density_g_cm3=1.35, primary_name="frame", rotations=None,
               connection_points=None, protected_regions=None,
               gap_mm=7.0, part_gap_mm=4.0, sprue_d_mm=.9,
               layout="single_column", parking_height_mm=None,
               attachment_sprue_d_mm=None):
    """Return ``onepiece_shape``, ``parked_parts`` and serializable ``metadata``.

    Outputs: ``onepiece-print.stl/.step``, ``assembly-original.step``, and
    ``print-pack.json``. The primary part's XY centre is retained; Z is grounded.
    Other parts are parked in separate vertical strips on its +X side. Default
    ``layout="single_column"`` is predictable; ``layout="columns"`` uses first-fit
    height bins to make the package shorter. Every column has its own low rail
    connected by a header outside all part footprints, so sprues never cross a
    neighbouring part to reach an attachment point.
    ``rotations`` values are lists of ``(axis_xyz, angle_deg)`` about the origin.
    ``connection_points`` values are xyz points in original assembly coordinates.
    ``protected_regions`` values are lists of assembly-coordinate CQ shapes.
    All input parts must be individually valid and one connected solid.
    """
    if not parts or primary_name not in parts:
        raise ValueError("A nonempty part mapping containing the primary part is required")
    if sprue_d_mm <= 0 or sprue_d_mm > 2 or gap_mm <= sprue_d_mm + 1:
        raise ValueError("Use positive small sprues and a clear separation gap")
    if density_g_cm3 <= 0:
        raise ValueError("Density must be positive")
    if layout not in ("single_column", "columns"):
        raise ValueError("Unknown parking layout")
    for name, s in parts.items():
        if not s.isValid() or len(s.Solids()) != 1:
            raise ValueError(f"Input {name!r} must be one valid connected solid")
    out = Path(out_dir or DEFAULT_OUT)
    out.mkdir(parents=True, exist_ok=True)
    rotations = {**DEFAULT_ROTATIONS, **(rotations or {})}
    connection_points = connection_points or {}
    protected_regions = protected_regions or {}
    attachment_sprue_d_mm = attachment_sprue_d_mm or {}
    if any(not .5 <= float(d) <= 2 for d in attachment_sprue_d_mm.values()):
        raise ValueError("Individual attachment diameters must be between 0.5 and 2 mm")
    radius = sprue_d_mm / 2
    parked, transforms, rows = {}, {}, {}
    primary, pm = _rotate(parts[primary_name], rotations.get(primary_name, []))
    pb = _bounds(primary)
    td = (0, 0, -pb[4])
    primary = primary.translate(td)
    parked[primary_name] = primary
    transforms[primary_name] = _mul(_translation(td), pm)
    pb = _bounds(primary)
    first_rail_x = pb[1] + gap_mm / 2
    rail_for_part = {primary_name: first_rail_x}
    unparked = {}
    for name, s in parts.items():
        if name == primary_name:
            continue
        rotated, m = _rotate(s, rotations.get(name, []))
        b = _bounds(rotated)
        unparked[name] = (rotated, m, b)
    limit_height = parking_height_mm or max(pb[3]-pb[2],
                                           max((b[3]-b[2] for _, _, b in unparked.values()), default=0))
    columns = []
    names = list(unparked)
    if layout == "columns":
        names.sort(key=lambda n: unparked[n][2][3]-unparked[n][2][2], reverse=True)
    for name in names:
        b = unparked[name][2]
        height, width = b[3]-b[2], b[1]-b[0]
        column = next((c for c in columns if layout == "single_column"
                       or c["height"]+height <= limit_height+1e-6), None)
        if column is None:
            column = {"names": [], "height": 0., "width": 0.}
            columns.append(column)
        column["names"].append(name)
        column["height"] += height+part_gap_mm
        column["width"] = max(column["width"], width)
    column_left = pb[1]+gap_mm
    for column in columns:
        next_y = pb[2]
        column["left_x_mm"] = column_left
        column["rail_x_mm"] = column_left-gap_mm/2
        for name in column["names"]:
            rotated, m, b = unparked[name]
            td = (column_left-b[0], next_y-b[2], -b[4])
            parked[name] = rotated.translate(td)
            transforms[name] = _mul(_translation(td), m)
            rail_for_part[name] = column["rail_x_mm"]
            next_y = _bounds(parked[name])[3]+part_gap_mm
        column_left += column["width"]+gap_mm
    # Confirm parts remain independent before adding sacrificial material.
    pairs = list(parked.items())
    for i, (an, a) in enumerate(pairs):
        for bn, b in pairs[i+1:]:
            if a.intersect(b).Volume() > 1e-6:
                raise ValueError(f"Parked print parts overlap: {an}/{bn}")
    attachments, branches = {}, []
    for name, s in parked.items():
        side = "right" if name == primary_name else "left"
        m = transforms[name]
        inv = _inverse(m)
        candidates = ([_point(m, connection_points[name])] if name in connection_points
                      else _section_candidates(s, side))
        rs = rotations.get(name, [])
        td = [m[i][3] for i in range(3)]
        exclusions = [_transform_shape(region, rs, td)
                      for region in protected_regions.get(name, [])]
        accepted = None
        for point in candidates:
            # All rails start at the printing plane. A lower-than-radius point
            # uses a narrower branch so no uncounted material sits below Z=0.
            r = min(float(attachment_sprue_d_mm.get(name, sprue_d_mm))/2,
                    point[2] - _bounds(s)[4])
            if r < .25:
                continue
            endpoint = [rail_for_part[name], point[1], radius]
            branch = _cylinder(point, endpoint, r, extension=.65)
            # The rail end is fully in free space; the part end penetrates only
            # a small external contact patch to make the Boolean union robust.
            if branch.intersect(s).Volume() < 1e-5:
                continue
            if any(branch.intersect(reg).Volume() > 1e-7 for reg in exclusions):
                continue
            if any(branch.intersect(other).Volume() > 1e-6
                   for other_name, other in parked.items() if other_name != name):
                continue
            accepted = (point, endpoint, branch, r)
            break
        if accepted is None:
            raise ValueError(f"No unprotected external sprue attachment found for {name}")
        point, endpoint, branch, r = accepted
        branches.append(branch)
        attachments[name] = {"point_print_mm": list(point),
                             "point_assembly_mm": _point(inv, point),
                             "rail_point_print_mm": endpoint,
                             "sprue_d_mm": 2*r,
                             "automatic_location_requires_review": name not in connection_points,
                             "protected_region_count": len(exclusions),
                             "contact_volume_mm3": branch.intersect(s).Volume()}
    header_y = pb[2]-gap_mm/2
    rails = []
    for rail_x in sorted(set(rail_for_part.values())):
        ys = [r["rail_point_print_mm"][1] for n, r in attachments.items()
              if rail_for_part[n] == rail_x]
        rails.append(_cylinder([rail_x, header_y, radius],
                                [rail_x, max(ys)+radius, radius], radius))
    if len(rails) > 1:
        rails.append(_cylinder([min(rail_for_part.values()), header_y, radius],
                                [max(rail_for_part.values()), header_y, radius], radius))
    sprues = rails[0].fuse(*rails[1:], *branches).clean()
    onepiece = primary.fuse(*(s for n, s in parked.items() if n != primary_name),
                            sprues).clean()
    if not onepiece.isValid() or len(onepiece.Solids()) != 1:
        raise ValueError(f"Print pack is not one valid connected solid ({len(onepiece.Solids())})")
    if _bounds(onepiece)[4] < -1e-6:
        # End extensions can overrun the rail plane on a sloped attachment.
        # Preserve the complete union and explicitly account for grounding.
        dz = -_bounds(onepiece)[4]
        onepiece = onepiece.translate((0, 0, dz))
        sprues = sprues.translate((0, 0, dz))
        parked = {n: s.translate((0, 0, dz)) for n, s in parked.items()}
        for n in transforms:
            transforms[n] = _mul(_translation((0, 0, dz)), transforms[n])
            attachments[n]["point_print_mm"][2] += dz
            attachments[n]["rail_point_print_mm"][2] += dz
    for name, s in parts.items():
        rows[name] = {"assembly_bounds_mm": _bounds(s),
                      "print_bounds_mm": _bounds(parked[name]),
                      "rotations_about_assembly_origin": [[list(a), d] for a, d in rotations.get(name, [])],
                      "assembly_to_print_4x4": transforms[name],
                      "print_to_assembly_4x4": _inverse(transforms[name]),
                      "volume_mm3": s.Volume(),
                      "sprue_attachment": attachments[name]}
    volumes = sum(s.Volume() for s in parts.values())
    net = onepiece.Volume()
    metadata = {"units": "mm", "coordinate_policy": "Independent assembly sources; explicit per-part print transforms",
                "packing_layout": layout+" outside +X with low cut-apart sprues",
                "parking_columns": columns,
                "all_input_print_parts_included": list(parts), "parts": rows,
                "print_part_count": len(parts),
                "all_attachment_locations_explicit": all(n in connection_points for n in parts),
                "print_bounds_mm": _bounds(onepiece), "solid_count": len(onepiece.Solids()),
                "cad_valid": onepiece.isValid(), "all_parts_volume_mm3": volumes,
                "sprues_nominal_volume_mm3": sprues.Volume(),
                "sprues_added_volume_mm3": net-volumes,
                "all_print_parts_and_sprues_volume_mm3": net,
                "density_g_cm3": density_g_cm3,
                "mass_g": net*density_g_cm3/1000,
                "mass_is_estimate_not_measured": True,
                "maximum_density_for_30g_g_cm3": 30000/net,
                "scope": "Net model including every listed print part and sacrificial sprue; printing supports are not modeled",
                "manufacturing_review_required": (
                    (["Review automatic attachment points against functional mating surfaces"]
                     if any(n not in connection_points for n in parts) else [])
                    + ["Resin fit/strength and shop support orientation", "Shop build-area and mass accounting rules"]),
                "files": {"onepiece_stl": "onepiece-print.stl", "onepiece_step": "onepiece-print.step",
                          "assembly_original_step": "assembly-original.step"}}
    cq.exporters.export(onepiece, str(out / "onepiece-print.stl"), tolerance=.03, angularTolerance=.08)
    cq.exporters.export(onepiece, str(out / "onepiece-print.step"))
    cq.exporters.export(cq.Compound.makeCompound(list(parts.values())), str(out / "assembly-original.step"))
    for key, filename in metadata["files"].items():
        p = out / filename
        metadata.setdefault("sha256", {})[key] = hashlib.sha256(p.read_bytes()).hexdigest()
    metadata["stl"] = check_stl(out / "onepiece-print.stl")
    if not metadata["stl"]["watertight"] or metadata["stl"]["connected_bodies"] != 1:
        raise ValueError("Exported one-piece STL must be watertight with one connected body")
    if not metadata["stl"]["winding_consistent"]:
        raise ValueError("Exported STL winding must be consistent")
    mesh_volume = metadata["stl"]["volume_mm3"]
    metadata["stl"]["relative_volume_error"] = abs(mesh_volume-net)/net
    if abs(mesh_volume-net)/net > .005:
        raise ValueError("Exported mesh/CAD volumes differ by more than 0.5 percent")
    (out / "print-pack.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return {"onepiece_shape": onepiece, "parked_parts": parked,
            "sprues_shape": sprues, "metadata": metadata}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-generated", action="store_true", help="Read part names from generated/part-volumes.json and original STEP files")
    parser.add_argument("--generated-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--layout", choices=("single_column", "columns"))
    parser.add_argument("--packing-config", type=Path,
                        help="JSON rotations/connection_points/protected_boxes/attachment diameters, in assembly coordinates")
    args = parser.parse_args()
    source_hashes = {}
    if args.from_generated:
        names = json.loads((args.generated_dir / "part-volumes.json").read_text())
        source_hashes = {n: hashlib.sha256((args.generated_dir/(n+".step")).read_bytes()).hexdigest() for n in names}
        parts = {n: cq.importers.importStep(str(args.generated_dir / (n+".step"))).val() for n in names}
    else:
        from build_skeleton import build_parts
        parts = build_parts()
    kwargs = {}
    settings = {}
    packing_config_digest = None
    if args.packing_config:
        config_bytes = args.packing_config.read_bytes()
        packing_config_digest = hashlib.sha256(config_bytes).hexdigest()
        settings = json.loads(config_bytes)
        accepted = {"density_g_cm3", "primary_name", "rotations", "connection_points",
                    "gap_mm", "part_gap_mm", "sprue_d_mm", "layout", "parking_height_mm",
                    "attachment_sprue_d_mm"}
        kwargs = {k: v for k, v in settings.items() if k in accepted}
        protected = {}
        for name, boxes in settings.get("protected_boxes", {}).items():
            protected[name] = []
            for x0, x1, y0, y1, z0, z1 in boxes:
                if min(x1-x0, y1-y0, z1-z0) <= 0:
                    raise ValueError("Protected boxes require strictly increasing coordinate bounds")
                protected[name].append(cq.Solid.makeBox(x1-x0, y1-y0, z1-z0, V(x0,y0,z0)))
        for name, paths in settings.get("protected_step", {}).items():
            for filename in paths:
                path = Path(filename)
                if not path.is_absolute():
                    path = args.packing_config.parent / path
                protected.setdefault(name, []).append(cq.importers.importStep(str(path)).val())
        kwargs["protected_regions"] = protected
        if settings.get("require_explicit_contacts"):
            missing = set(parts)-set(settings.get("connection_points", {}))
            if missing:
                raise ValueError("Explicit reviewed contacts required for all parts: " + ", ".join(sorted(missing)))
    if args.layout:
        kwargs["layout"] = args.layout
    result = pack_parts(parts, args.out_dir, **kwargs)
    metadata = result["metadata"]
    if args.from_generated:
        metadata["source_assembly_steps_sha256"] = source_hashes
        if any(hashlib.sha256((args.generated_dir/(n+".step")).read_bytes()).hexdigest() != digest
               for n, digest in source_hashes.items()):
            raise RuntimeError("Source assembly STEP changed during packing; regenerate the package")
    if args.packing_config:
        if hashlib.sha256(args.packing_config.read_bytes()).hexdigest() != packing_config_digest:
            raise RuntimeError("Packing plan changed during packing; regenerate the package")
        metadata["packing_config_sha256"] = packing_config_digest
        metadata["packing_config_contact_review"] = settings.get("contact_review", {})
        metadata["protected_geometry_files_sha256"] = {}
        for paths in settings.get("protected_step", {}).values():
            for filename in paths:
                path = Path(filename)
                if not path.is_absolute():
                    path = args.packing_config.parent/path
                metadata["protected_geometry_files_sha256"][filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.out_dir/"print-pack.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k: result["metadata"][k] for k in ("mass_g", "print_bounds_mm", "solid_count", "stl")}, indent=2))


if __name__ == "__main__":
    main()
