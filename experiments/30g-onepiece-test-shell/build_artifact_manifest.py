"""Hash the final prototype files and check delivery/configuration consistency."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    pack = read("generated/print-pack.json")
    geometry = read("generated/assembly-check.json")
    pcb = read("pcb/fabrication-manifest.json")
    electrical = read("pcb/electrical-report.json")
    firmware = read("firmware/build-manifest.json")
    config_sha = sha(HERE / "carrier-config.json")
    assert config_sha == pcb["config_sha256"] == electrical["config_sha256"] == firmware["carrier_config_sha256"]
    for name, expected in pcb["files"].items():
        assert sha(HERE / name) == expected, f"Stale PCB artifact: {name}"
    for name, expected in firmware["source_sha256"].items():
        assert sha(HERE / "firmware/gun_mouse_supermini" / name) == expected, f"Stale firmware source: {name}"
    for name, expected in firmware["artifacts"].items():
        assert sha(HERE / "firmware/bin" / name) == expected["sha256"], f"Stale firmware binary: {name}"
    assert geometry["exact_geometry_pass"], "Assembly geometry has unresolved failures"
    assert geometry["conservative_envelope_review_clear"], "Component envelope checks have unresolved failures"
    assert geometry["full_validation_pass"] and geometry["complete_coverage"], "Incomplete assembly/motion coverage"
    hardware_motion = read("generated/joystick-hardware-motion-check.json")
    assert hardware_motion["pass"] and hardware_motion["state_count"] == 32
    assert hardware_motion["assembly_report_sha256"] == sha(HERE / "generated/assembly-check.json")
    for name, expected in hardware_motion["supplement_sources_sha256"].items():
        path = HERE / ("generated" if name.endswith(".step") else "") / name
        assert sha(path) == expected, f"Stale joystick hardware supplement: {name}"
    part_names = set(read("generated/part-volumes.json"))
    assert len(part_names) == 13 and part_names == set(pack["all_input_print_parts_included"])
    for name in part_names:
        filename = name + ".step"
        current = sha(HERE / "generated" / filename)
        assert current == geometry["parts_source_sha256"][filename], f"Stale geometry validation: {filename}"
        assert current == pack["source_assembly_steps_sha256"][name], f"Stale print packing: {filename}"
    for name, expected in geometry["design_sources_sha256"].items():
        assert sha(HERE.parents[1] / name) == expected, f"Stale geometry source: {name}"
    assert sha(HERE / "packing-plan.json") == pack["packing_config_sha256"]
    for name, expected in pack["protected_geometry_files_sha256"].items():
        path = Path(name)
        if not path.is_absolute():
            path = HERE / path
        assert sha(path) == expected, f"Stale sprue protection: {name}"
    for key, filename in pack["files"].items():
        assert sha(HERE / "generated" / filename) == pack["sha256"][key], f"Stale packed model: {filename}"
    assert pack["cad_valid"] and pack["solid_count"] == 1
    assert pack["stl"]["watertight"] and pack["stl"]["connected_bodies"] == 1
    assert pack["mass_g"] < 30.0
    files = {}
    for path in sorted(HERE.rglob("*")):
        if not path.is_file() or path.name == "artifact-manifest.json":
            continue
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".prl", ".kicad_prl") or "-debug." in path.name:
            continue
        if path.name in ("assembly-progress.json", "assembly-static-check.json", "assembly-preliminary.json"):
            continue
        files[str(path.relative_to(HERE))] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    result = {
        "experiment": "SuperMini hand-soldered 30g open-frame prototype",
        "branch": "experiment/30g-onepiece-test-shell",
        "status": "CAD-and-compile-verified; first physical sample pending",
        "carrier_config_sha256": config_sha,
        "pcb_size_mm": [52, 82],
        "main_pcb_smt_parts": 0,
        "print": {key: pack[key] for key in (
            "all_parts_volume_mm3", "sprues_added_volume_mm3",
            "all_print_parts_and_sprues_volume_mm3", "density_g_cm3", "mass_g",
            "maximum_density_for_30g_g_cm3", "solid_count", "print_bounds_mm", "stl")},
        "geometry_checks": {key: geometry[key] for key in (
            "exact_geometry_pass", "conservative_envelope_review_clear", "full_validation_pass", "check_coverage", "not_certified")},
        "firmware_compile": "passed esp32 Arduino 3.3.2; host logic tests passed",
        "limits": ["Mass is calculated from CAD volume, including printed connecting bridges; shop supports are excluded.",
                   "Physical print fit, normal-use strength, actual purchased modules, wiring and firmware remain first-sample checks.",
                   "This experimental carrier has a checked PCB/netlist but no native KiCad schematic/ERC."],
        "files": files,
    }
    (HERE / "artifact-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(files), "print_mass_g": pack["mass_g"], "carrier_config_sha256": config_sha}))


if __name__ == "__main__":
    main()
