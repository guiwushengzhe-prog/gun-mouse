"""移动下部两安装孔并移除已被共用孔替代的孔；不改变原电路网络。"""
from pathlib import Path
import json
import math
import shutil
import subprocess

import pcbnew as pcb
from preview_layout import BODY_MOUNT_HOLES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "shell/快速结构预览/pcb"
TARGET = OUT / "preview-regular-mount.kicad_pcb"
MM = pcb.FromMM


def move_holes():
    source = OUT / "preview-local-mount.kicad_pcb"
    board = pcb.LoadBoard(str(source))
    keep = []
    for fp in list(board.GetFootprints()):
        reference = fp.GetReference()
        if reference == "H_JOY_LOCAL_1":
            keep.append(fp)
            board.Remove(fp)
            continue
        name = "H5" if reference == "H_BODY_5" else reference
        if name not in {"H4", "H5"}:
            continue
        x, z = BODY_MOUNT_HOLES[name]
        point = pcb.VECTOR2I(MM(-x-3), MM(45-z))
        movement = point-fp.GetPosition()
        fp.Move(movement)
        for zone in board.Zones():
            if zone.GetZoneName() == "SCREW_CLEAR_"+reference:
                zone.Move(movement)
        if name == "H4":
            zone = pcb.ZONE(board)
            zone.SetZoneName("SCREW_CLEAR_H4")
            zone.SetIsRuleArea(True)
            layers = pcb.LSET()
            layers.AddLayer(pcb.F_Cu)
            layers.AddLayer(pcb.B_Cu)
            zone.SetLayerSet(layers)
            zone.SetDoNotAllowTracks(True)
            zone.SetDoNotAllowVias(True)
            zone.SetDoNotAllowCopperPour(True)
            zone.SetDoNotAllowPads(False)
            zone.SetDoNotAllowFootprints(False)
            poly = zone.Outline()
            poly.NewOutline()
            radius = 2.56/math.cos(math.pi/32)
            for i in range(32):
                angle = i*math.tau/32
                poly.Append(MM(-x-3+radius*math.cos(angle)), MM(45-z+radius*math.sin(angle)))
            board.Add(zone)
    for zone in list(board.Zones()):
        if zone.GetZoneName() == "SCREW_CLEAR_H_JOY_LOCAL_1":
            keep.append(zone)
            board.Remove(zone)
    shutil.copy2(source.with_suffix(".kicad_pro"), TARGET.with_suffix(".kicad_pro"))
    pcb.ZONE_FILLER(board).Fill(board.Zones())
    pcb.SaveBoard(str(TARGET), board)
    report = OUT / "regular-mount-check.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--output", str(report), str(TARGET)], check=True)
    result = json.loads(report.read_text(encoding="utf-8"))
    errors = [v for v in result["violations"] if v["severity"] == "error"]
    if errors or result["unconnected_items"]:
        raise RuntimeError((errors, result["unconnected_items"]))
    subprocess.run(["kicad-cli", "pcb", "export", "glb", "--force", "--board-only", "--include-tracks", "--include-pads", "--include-zones", "--include-silkscreen", "--include-soldermask", "--output", str(TARGET.with_suffix(".glb")), str(TARGET)], check=True)
    TARGET.with_suffix(".kicad_prl").unlink(missing_ok=True)
    report.unlink()
    print("已核对规整版孔位及电路规则", flush=True)


if __name__ == "__main__":
    move_holes()
