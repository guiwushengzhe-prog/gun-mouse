"""Render assembly-coordinate CadQuery parts without rebuilding their geometry.

Python API::

    images = render_parts(parts, out_dir=None, references=assembly_references)

CLI::

    python render_open_frame.py --from-generated --no-references

The generated STEP files must be assembly-coordinate exports, not parked print
files. Reference components are conservative envelopes, not detailed vendor CAD.
CadQuery and VTK are required. VTK's X11 builds also need DISPLAY or Xvfb on PATH;
if available, a temporary local Xvfb is started automatically for offscreen use.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import cadquery as cq
import vtk

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
DEFAULT_OUTPUT = HERE / "generated" / "renders"
IMAGE_SIZE = (1600, 1300)
COLORS = {
    "frame": (0.94, 0.95, 0.97),
    "moving": (1.0, 0.40, 0.11),
    "pcb": (0.10, 0.43, 0.24),
    "dev": (0.05, 0.24, 0.17),
    "battery": (0.80, 0.82, 0.84),
    "component": (0.26, 0.29, 0.33),
    "connector": (0.73, 0.66, 0.46),
}
MOVING_PARTS = {"trigger", "touch_cover", "right_cap", "joystick_cap"}
VIEW_SPECS = (
    ("assembly-front", "ASSEMBLY / LEFT SIDE", (0.28, 1.0, 0.20), False),
    ("assembly-back", "ASSEMBLY / RIGHT SIDE", (0.28, -1.0, 0.20), False),
    ("assembly-isometric", "ASSEMBLY / ISOMETRIC", (0.85, 1.5, 0.60), False),
    ("assembly-exploded", "ASSEMBLY / EXPLODED", (0.65, 1.5, 0.45), True),
)


def _shape(value):
    if isinstance(value, dict):
        value = value["shape"]
    if isinstance(value, cq.Workplane):
        values = value.vals()
        value = values[0] if len(values) == 1 else cq.Compound.makeCompound(values)
    if not isinstance(value, cq.Shape):
        raise TypeError(f"Expected a CadQuery shape, got {type(value).__name__}")
    return value


def _polydata(shape):
    """Create triangle data directly from OCCT tessellation; no temporary STL."""
    vertices, triangles = shape.tessellate(0.075, 0.12)
    if not vertices or not triangles:
        raise ValueError("Cannot render a shape without tessellated faces")
    points = vtk.vtkPoints()
    for vertex in vertices:
        points.InsertNextPoint(vertex.x, vertex.y, vertex.z)
    cells = vtk.vtkCellArray()
    for indices in triangles:
        cells.InsertNextCell(3)
        for index in indices:
            cells.InsertCellPoint(index)
    data = vtk.vtkPolyData()
    data.SetPoints(points)
    data.SetPolys(cells)
    # OCCT faces share coincident positions but not necessarily vertex indices.
    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(data)
    clean.SetTolerance(1e-7)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputConnection(clean.GetOutputPort())
    normals.SetFeatureAngle(38)
    normals.SplittingOn()
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.Update()
    result = vtk.vtkPolyData()
    result.DeepCopy(normals.GetOutput())
    return result


def _actor(mesh, color):
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(mesh)
    mapper.ScalarVisibilityOff()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    material = actor.GetProperty()
    material.SetColor(*color)
    material.SetInterpolationToPhong()
    material.SetAmbient(0.36)
    material.SetDiffuse(0.68)
    material.SetSpecular(0.22)
    material.SetSpecularPower(32)
    return actor


def _text(renderer, value, x, y, size, color=(0.17, 0.22, 0.28)):
    actor = vtk.vtkTextActor()
    actor.SetInput(value)
    actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
    actor.SetPosition(x, y)
    prop = actor.GetTextProperty()
    prop.SetFontFamilyToArial()
    prop.SetFontSize(size)
    prop.SetColor(*color)
    renderer.AddActor2D(actor)


def _explode(name, kind, daughter=False, board_group=None):
    """Presentation offsets only; saved STEP and input solids stay unchanged."""
    offsets = {
        "frame": (0, -38, 0),
        "control_bridge": (0, 40, 0),
        "trigger_gate": (0, 30, 0),
        "trigger": (24, 0, 0),
        "touch_cover": (42, 14, 0),
        "right_cap": (0, 67, 0),
        "joystick_cap": (0, 67, 8),
        "pcb_board": (0, 5, 0),
        "daughter_board": (8, 0, 0),
        "battery": (0, -64, 0),
        "dev_board": (0, -14, 12),
        "supermini_clamp": (0, -5, 12),
        "imu": (0, 30, 12),
        "imu_board": (0, 30, 12),
        "imu_cradle": (0, 15, 12),
        "imu_clamp": (0, 55, 12),
        "trigger_switch": (-25, 14, 0),
        "trigger_holder": (-25, 14, 0),
    }
    if name.startswith("pcb_clamp_"):
        return (0, 30, 0)
    if kind == "component":
        group = {"carrier": "pcb_board", "supermini": "dev_board"}.get(board_group, board_group)
        if group in offsets:
            return offsets[group]
        if name in offsets:
            return offsets[name]
        return offsets["daughter_board" if daughter else "pcb_board"]
    return offsets.get(name, (0, 0, 0))


def _reference_kind(name):
    lower = name.lower()
    if "battery" in lower or "cell" in lower:
        return "battery"
    if "supermini" in lower or "dev_board" in lower or "esp32" in lower:
        return "dev"
    if "pcb" in lower or "perfboard" in lower or lower.endswith("_board"):
        return "pcb"
    return "component"


def _scene_items(parts, cfg, include_references, references=None):
    items = []
    for name, value in parts.items():
        shape = _shape(value)
        kind = "moving" if name in MOVING_PARTS else "frame"
        items.append({"name": name, "kind": kind, "shape": shape,
                      "color": COLORS[kind], "daughter": False, "board_group": None})
    reference_metadata = None
    if include_references:
        if references is None:
            raise ValueError("Provide explicit assembly-coordinate references for this module design, "
                             "or use include_references=False. Legacy EVT-A PCB references are not used automatically.")
        refs = references
        reference_metadata = refs.get("metadata")
        for name, value in refs.items():
            if not isinstance(value, (cq.Shape, cq.Workplane)) and not (isinstance(value, dict) and "shape" in value):
                continue
            kind = value.get("kind", _reference_kind(name)) if isinstance(value, dict) else _reference_kind(name)
            color = value.get("color", COLORS[kind]) if isinstance(value, dict) else COLORS[kind]
            items.append({"name": name, "kind": kind, "shape": _shape(value),
                          "color": color, "daughter": name == "daughter_board", "board_group": name})
        for index, envelope in enumerate(refs.get("component_envelopes", [])):
            ref = envelope.get("ref", f"component_{index}")
            color = COLORS["connector"] if ref.startswith(("USB", "J", "LED")) else COLORS["component"]
            items.append({"name": f"{ref}_{envelope.get('side', 'top')}_{index}",
                          "kind": "component", "shape": _shape(envelope), "color": color,
                          "daughter": bool(envelope.get("daughter")),
                          "board_group": envelope.get("board_group")})
    return items, reference_metadata


@contextmanager
def _display_context():
    """Guard VTK X11 builds against their fatal no-DISPLAY abort."""
    if os.name == "nt" or sys.platform == "darwin":
        # Native Windows/Cocoa VTK render windows do not use an X11 DISPLAY.
        yield
        return
    if os.environ.get("DISPLAY") or hasattr(vtk, "vtkEGLRenderWindow") or hasattr(vtk, "vtkOSOpenGLRenderWindow"):
        yield
        return
    binary = os.environ.get("OPEN_FRAME_XVFB") or shutil.which("Xvfb")
    if not binary:
        raise RuntimeError("This VTK build requires X11. Set DISPLAY, install Xvfb, "
                           "or point OPEN_FRAME_XVFB at an Xvfb executable.")
    socket_directory = Path("/tmp/.X11-unix")
    if not socket_directory.exists():
        socket_directory.mkdir(mode=0o1777)
    display = next((n for n in range(91, 191)
                    if not Path(f"/tmp/.X11-unix/X{n}").exists()
                    and not Path(f"/tmp/.X{n}-lock").exists()), None)
    if display is None:
        raise RuntimeError("No free temporary X display in the range :91 to :190")
    process = None
    with tempfile.TemporaryFile() as log:
        try:
            process = subprocess.Popen([binary, f":{display}", "-screen", "0", "1600x1300x24",
                                        "-nolisten", "tcp", "-ac"], stdout=log, stderr=log)
            deadline = time.monotonic() + 8
            while not Path(f"/tmp/.X11-unix/X{display}").exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    log.seek(0)
                    raise RuntimeError("Temporary Xvfb failed: " + log.read().decode(errors="replace")[-2000:])
                time.sleep(0.05)
            os.environ["DISPLAY"] = f":{display}"
            yield
        finally:
            os.environ.pop("DISPLAY", None)
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def _new_window():
    # EGL/OSMesa builds support headless use without a temporary X server.
    if os.name == "nt" or sys.platform == "darwin":
        window = vtk.vtkRenderWindow()
    elif not os.environ.get("DISPLAY") and hasattr(vtk, "vtkEGLRenderWindow"):
        window = vtk.vtkEGLRenderWindow()
    elif not os.environ.get("DISPLAY") and hasattr(vtk, "vtkOSOpenGLRenderWindow"):
        window = vtk.vtkOSOpenGLRenderWindow()
    else:
        window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(*IMAGE_SIZE)
    window.SetMultiSamples(8)
    return window


def _render_view(items, title, direction, exploded, path, include_references):
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.88, 0.91, 0.94)
    renderer.SetBackground2(0.98, 0.985, 0.99)
    renderer.GradientBackgroundOn()
    renderer.AutomaticLightCreationOff()
    actors = []
    for item in items:
        actor = _actor(item["mesh"], item["color"])
        if exploded:
            actor.SetPosition(*_explode(item["name"], item["kind"], item["daughter"], item["board_group"]))
        renderer.AddActor(actor)
        actors.append(actor)
    bounds = [min(a.GetBounds()[i] for a in actors) if i % 2 == 0
              else max(a.GetBounds()[i] for a in actors) for i in range(6)]
    centre = tuple((bounds[i] + bounds[i+1]) / 2 for i in (0, 2, 4))
    extent = max(bounds[i+1] - bounds[i] for i in (0, 2, 4))
    norm = math.sqrt(sum(d*d for d in direction))
    eye = tuple(centre[i] + direction[i] / norm * max(extent, 1) * 3 for i in range(3))
    camera = renderer.GetActiveCamera()
    camera.SetFocalPoint(*centre)
    camera.SetPosition(*eye)
    camera.SetViewUp(0, 0, 1)
    camera.ParallelProjectionOn()
    renderer.ResetCamera(bounds)
    camera.SetParallelScale(camera.GetParallelScale() * 1.17)
    renderer.ResetCameraClippingRange()
    for dx, dy, dz, strength in ((0.7, 1.0, 1.8, 0.80), (-1.0, -0.6, 0.4, 0.46), (0.6, -1.0, 1.0, 0.50)):
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPosition(centre[0]+dx*extent, centre[1]+dy*extent, centre[2]+dz*extent)
        light.SetFocalPoint(*centre)
        light.SetIntensity(strength)
        renderer.AddLight(light)
    fill = vtk.vtkLight()
    fill.SetLightTypeToHeadlight()
    fill.SetIntensity(0.40)
    renderer.AddLight(fill)
    _text(renderer, title, 0.035, 0.943, 29)
    subtitle = "Assembly coordinates in mm"
    if include_references:
        subtitle += "  |  Static component envelopes"
    if exploded:
        subtitle += "  |  Display offsets only"
    _text(renderer, subtitle, 0.035, 0.910, 17, (0.38, 0.43, 0.48))
    labels = [("FRAME / CLAMPS", "frame"), ("MOVING CAPS / TRIGGER", "moving")]
    if include_references:
        labels += [("PCB", "pcb"), ("DEV BOARD", "dev"), ("BATTERY", "battery")]
    for index, (label, color) in enumerate(labels):
        # Darken white/grey label colors to remain readable against the background.
        label_color = (0.40, 0.44, 0.49) if color in ("frame", "battery") else COLORS[color]
        _text(renderer, label, 0.035+index*0.185, 0.031, 17, label_color)
    window = _new_window()
    try:
        window.AddRenderer(renderer)
        window.Render()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(window)
        capture.SetInputBufferTypeToRGB()
        capture.ReadFrontBufferOff()
        capture.Update()
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(str(path))
        writer.SetInputConnection(capture.GetOutputPort())
        writer.Write()
        if not path.exists() or path.stat().st_size < 1000:
            raise RuntimeError(f"PNG output missing or empty: {path}")
    finally:
        window.Finalize()
    return {"path": str(path.resolve()), "width": IMAGE_SIZE[0], "height": IMAGE_SIZE[1],
            "camera_position_mm": list(camera.GetPosition()), "camera_target_mm": list(centre),
            "exploded": exploded, "bounds_mm": list(bounds)}


def render_parts(parts, cfg=None, out_dir=None, include_references=True, references=None):
    """Render front/back/isometric/exploded PNGs and return image metadata.

    ``parts`` maps part names to CadQuery Shape/Workplane or ``{"shape": ...}``.
    ``references`` is an explicit mapping of assembly-coordinate reference shapes
    or dicts containing ``shape`` and optional ``kind`` / ``color``. A ``metadata``
    entry is recorded as provenance. References never count toward print mass.
    ``cfg`` is retained for caller compatibility; it cannot silently load legacy
    PCB geometry after the module design changes.
    This function never calls build_parts, imports STEP, or transforms input shapes.
    Set ``include_references=False`` for geometry-only or small API smoke renders.
    A metadata JSON is written alongside the images for reproducible orientation.
    """
    if not parts:
        raise ValueError("At least one printable part is required")
    cfg = cfg or {}
    output = Path(out_dir) if out_dir is not None else DEFAULT_OUTPUT
    output.mkdir(parents=True, exist_ok=True)
    items, reference_metadata = _scene_items(parts, cfg, include_references, references)
    for item in items:
        item["mesh"] = _polydata(item["shape"])
    images = {}
    with _display_context():
        for filename, title, direction, exploded in VIEW_SPECS:
            images[filename] = _render_view(items, title, direction, exploded,
                                           output / f"{filename}.png", include_references)
    result = {"units": "mm", "coordinate_system": "X forward, Y left, Z up",
              "images": images, "print_parts": list(parts), "include_references": bool(include_references),
              "exploded_display_offsets_mm": {
                  item["name"]: list(_explode(item["name"], item["kind"], item["daughter"], item["board_group"]))
                  for item in items},
              "reference_geometry": reference_metadata,
              "notes": ["Images illustrate geometry; they do not establish strength or clearance.",
                        "Exploded view translates display actors only; source CAD is unchanged."]}
    metadata_path = output / "render-metadata.json"
    result["metadata_path"] = str(metadata_path.resolve())
    metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return result


def _generated_parts(directory):
    # A volume manifest identifies finalized exports and excludes debug compounds.
    manifest = directory / "part-volumes.json"
    if manifest.exists():
        names = list(json.loads(manifest.read_text(encoding="utf-8")))
        paths = [directory / f"{name}.step" for name in names]
    else:
        raise FileNotFoundError("part-volumes.json is required to select independent assembly-coordinate "
                                "print parts; parked one-piece or assembly compound files must not be rendered as parts")
    if not paths:
        raise FileNotFoundError(f"No final assembly STEP files found in {directory}")
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing final STEP exports: " + ", ".join(missing))
    return {path.stem: _shape(cq.importers.importStep(str(path))) for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-generated", action="store_true", help="Read exported STEP, never rebuild geometry")
    parser.add_argument("--generated-dir", type=Path, default=HERE / "generated")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, help="Optional current assembly config")
    parser.add_argument("--reference-manifest", type=Path,
                        help="JSON mapping reference names to assembly-coordinate STEP paths, optional metadata")
    parser.add_argument("--current-references", action="store_true",
                        help="Explicitly build current carrier/module references from carrier-config.json and open-frame-config.json")
    parser.add_argument("--no-references", action="store_true", help="Render printable parts only")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    if args.from_generated:
        parts = _generated_parts(args.generated_dir)
    else:
        # Lazy import keeps module API and STEP-only CLI independent of the builder.
        from build_skeleton import build_parts
        parts = build_parts()
    refs = None
    if args.current_references and (args.reference_manifest or args.no_references):
        parser.error("--current-references requires references and cannot be combined with --reference-manifest")
    if args.current_references:
        from reference_models import build_references
        refs = build_references(assembly_cfg=cfg if args.config else None)
    if args.reference_manifest:
        manifest = json.loads(args.reference_manifest.read_text(encoding="utf-8"))
        refs = {"metadata": manifest.get("metadata", {})}
        for name, value in manifest.items():
            if name == "metadata":
                continue
            description = {"path": value} if isinstance(value, str) else dict(value)
            path = Path(description.pop("path"))
            if not path.is_absolute():
                path = args.reference_manifest.parent / path
            description["shape"] = _shape(cq.importers.importStep(str(path)))
            refs[name] = description
    result = render_parts(parts, cfg, args.out_dir, not args.no_references, references=refs)
    print(json.dumps({"images": {name: spec["path"] for name, spec in result["images"].items()},
                      "print_part_count": len(result["print_parts"]),
                      "include_references": result["include_references"],
                      "metadata_path": result["metadata_path"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
