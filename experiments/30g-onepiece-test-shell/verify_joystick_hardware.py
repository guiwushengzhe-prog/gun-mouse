"""Independently check the full report's joystick poses against M2 hardware.

This supplement reuses the declared cup-head/shaft/hex-nut geometry, checks
actual knob STEP poses with BRep intersections, and binds its input hashes.
It does not replace the full assembly/motion validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cadquery as cq

from verify_open_frame import ROOT, _motion_shape, fastener_shapes, shape_pair


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts-dir",type=Path,required=True)
    parser.add_argument("--assembly-report",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.assembly_report.read_text(encoding="utf-8"))
    source_mismatches=[name for name,expected in report["design_sources_sha256"].items()
                       if digest(ROOT/name)!=expected]
    step_mismatches=[name for name,expected in report["parts_source_sha256"].items()
                     if digest(args.parts_dir/name)!=expected]
    if source_mismatches or step_mismatches or not report.get("full_validation_pass"):
        raise SystemExit("Full report is not a passing snapshot of current sources/STEP files")
    knob=cq.importers.importStep(str(args.parts_dir/"joystick_cap.step")).val()
    hardware={spec["id"]+"/"+kind:shape
              for spec in report["complete_validation_plan"]["fasteners"]
              for kind,shape in fastener_shapes(spec).items() if kind!="tool"}
    states=[state for state in report["complete_validation_plan"]["motions"]
            if state.get("part")=="joystick_cap"]
    checks={}
    for state in states:
        moving=_motion_shape(knob,state)
        pairs={name:shape_pair(moving,shape) for name,shape in hardware.items()}
        checks[state["name"]]={name:pair for name,pair in pairs.items()
                               if not pair["clear_of_volume_interference"]}
    passed=len(states)==32 and len(hardware)==43 and not any(checks.values())
    summary={"pass":passed,"cadquery_version":cq.__version__,
        "state_count":len(states),"hardware_solid_count":len(hardware),
        "method":"BRep intersections for the full report's 32 joystick tilt/press/shaft-height poses and all 43 shaft/head/nut solids",
        "CAD_nominal_hardware_hits":checks,
        "assembly_report_sha256":digest(args.assembly_report),
        "source_SHA_match_current":True,
        "supplement_sources_sha256":{
            Path(__file__).name:digest(Path(__file__)),
            "verify_open_frame.py":digest(Path(__file__).with_name("verify_open_frame.py")),
            "joystick_cap.step":digest(args.parts_dir/"joystick_cap.step")},
        "limitations":"32 specified states; no continuous arbitrary-axis articulation proof, measured real joystick pivot, or actual L-key handle geometry"}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(args.output),"pass":passed,
                      "states":len(states),"hardware_solids":len(hardware)}))
    if not passed:
        raise SystemExit(1)


if __name__=="__main__":
    main()
