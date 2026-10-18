"""落实最终分区并重排受影响铜线；只写最终版目录。复用既有KiCad环境。"""
from collections import Counter
import hashlib
import json
import math
import shutil
import subprocess
import zipfile

import numpy as np
import pcbnew as pcb

import generate_gen2_pcb as generator
from preview_local_mount_pcb import position, segment_distance
from final_regular_layout import ROOT, OUT, RELEASE, PASSIVE_CENTERS, WIRE_HOLES
from prepare_release_pcb import audit_drill

SOURCE = ROOT/"shell/长方条正式预览/pcb/preview-rectangular-mount.kicad_pcb"
DEST = OUT/"pcb"
TARGET = DEST/"gunmouse-final.kicad_pcb"
MM = pcb.FromMM
RETIRED = []


def vector(point):
    return pcb.VECTOR2I(*[MM(value) for value in point])


def xy(point):
    return [-point[0]-3, 45-point[1]]


def run(*args):
    subprocess.run(["kicad-cli", *map(str, args)], check=True)


def route():
    board = pcb.LoadBoard(str(SOURCE))
    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    original = json.loads((ROOT/"pcb/carrier-config.json").read_text(encoding="utf-8"))
    affected, areas = set(), []
    movements = {}
    for part in original["parts"]:
        name = part["ref"]
        if name not in PASSIVE_CENTERS:
            continue
        start, end = part["position_xz"], PASSIVE_CENTERS[name]
        movements[name] = [start[0]-end[0], start[1]-end[1]]
    movements.update({"J_TRIG": [0, 2.54], "J_TOUCH": [0, 4]})
    for name, movement in movements.items():
        fp = footprints[name]
        before = [position(pad.GetPosition()) for pad in fp.Pads()]
        affected.update(pad.GetNetname() for pad in fp.Pads() if pad.GetNetname())
        fp.Move(vector(movement))
        for pad, old in zip(fp.Pads(), before):
            areas.extend([old, position(pad.GetPosition())])
        for drawing in board.GetDrawings():
            if isinstance(drawing, pcb.PCB_TEXT) and drawing.GetText().startswith(name+"."):
                drawing.Move(vector(movement))
    for track in board.GetTracks():
        if any(segment_distance(point, position(track.GetStart()), position(track.GetEnd())) < 1.8 for point in areas):
            affected.add(track.GetNetname())
    # 上部模块与摇杆扇出已通过规则检查；只重排Y>=51毫米的下部电路。
    # 跨分界的铜线保留上段，接线时从其实际铜层出发，不在密集区硬塞过孔。
    anchors, anchor_layers = {}, {}
    for track in list(board.GetTracks()):
        name = track.GetNetname()
        if name not in affected:
            continue
        a, b = position(track.GetStart()), position(track.GetEnd())
        if max(a[1], b[1]) < 51:
            continue
        if not isinstance(track, pcb.PCB_VIA) and min(a[1], b[1]) < 51:
            t = (51-a[1])/(b[1]-a[1])
            end = [a[0]+t*(b[0]-a[0]), 51]
            keep = pcb.PCB_TRACK(board)
            keep.SetStart(vector(a if a[1] < 51 else b))
            keep.SetEnd(vector(end))
            keep.SetWidth(track.GetWidth())
            keep.SetLayer(track.GetLayer())
            keep.SetNetCode(track.GetNetCode())
            board.Add(keep)
            if end not in anchors.setdefault(name, []):
                anchors[name].append(end)
                anchor_layers[(name, tuple(end))] = 0 if track.GetLayer() == pcb.F_Cu else 1
        RETIRED.append(track)
        board.Remove(track)
    # 原版三处接地脚曾用短线接入铜区；移位后重新由实际铜区和必要短线检查。
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == "GND":
                pad.SetLocalZoneConnection(pcb.ZONE_CONNECTION_INHERITED)
    env = generator.legacy_functions()
    nets = {str(net.GetNetname()): net for net in board.GetNetsByNetcode().values()}
    pads = [{"ref": fp.GetReference(), "number": pad.GetNumber(), "xy": position(pad.GetPosition()),
             "size": position(pad.GetSize()), "drill": position(pad.GetDrillSize()),
             "net": pad.GetNetname(), "net_code": pad.GetNetCode()}
            for fp in board.GetFootprints() for pad in fp.Pads()]
    router = env["Router"](board, nets, pads, [xy(p) for p in original["pcb"]["outline_xz"]])
    for track in board.GetTracks():
        a, b = position(track.GetStart()), position(track.GetEnd())
        if isinstance(track, pcb.PCB_VIA):
            router.mark_disc(a, pcb.ToMM(track.GetWidth(pcb.F_Cu))/2+.5, track.GetNetCode(), [0, 1])
            router.mark_hole(a, pcb.ToMM(track.GetDrillValue())/2+.4)
        else:
            count = max(1, math.ceil(math.dist(a, b)/.0635))
            for step in range(count+1):
                router.mark_disc([a[i]+(b[i]-a[i])*step/count for i in (0, 1)],
                                 pcb.ToMM(track.GetWidth())/2+.5, track.GetNetCode(),
                                 [0 if track.GetLayer() == pcb.F_Cu else 1])
    gx, gy = router.x0+np.arange(router.w)*generator.GRID, router.y0+np.arange(router.h)*generator.GRID
    xx, yy = np.meshgrid(gx, gy)
    for zone in board.Zones():
        if not zone.GetIsRuleArea():
            continue
        ring = zone.Outline().COutline(0)
        points = [position(ring.CPoint(i)) for i in range(ring.PointCount())]
        inside, boundary = np.zeros_like(xx, dtype=bool), np.full_like(xx, 1e6)
        for a, b in zip(points, points[1:]+points[:1]):
            if abs(b[1]-a[1]) > 1e-10:
                inside ^= ((a[1]>yy)!=(b[1]>yy)) & (xx<(b[0]-a[0])*(yy-a[1])/(b[1]-a[1])+a[0])
            dx, dy = b[0]-a[0], b[1]-a[1]
            t = np.clip(((xx-a[0])*dx+(yy-a[1])*dy)/(dx*dx+dy*dy), 0, 1)
            boundary = np.minimum(boundary, np.hypot(xx-a[0]-t*dx, yy-a[1]-t*dy))
        mask = inside | (boundary < .3)
        for layer, ki in enumerate([pcb.F_Cu, pcb.B_Cu]):
            if zone.IsOnLayer(ki):
                router.owner[layer, mask] = -1
        router.hole_keepout[mask] = True
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcb.PAD_ATTRIB_NPTH:
                router.mark_disc(position(pad.GetPosition()), max(position(pad.GetDrillSize()))/2+.8, -1, [0, 1])
    priorities = {"JOY_Y": 0, "JOY_X": 1, "TRIG": 2, "TOUCH": 3, "VBAT_ADC": 4,
                  "JOY_SW": 5, "BTN_R": 6, "TOUCH_ELECTRODE": 7, "3V3": 8, "BAT_SW": 9}
    for name in sorted(affected-{"GND", ""}, key=lambda name: (priorities.get(name, 10), name)):
        old = anchors.get(name, [])
        terminals = old+[p["xy"] for p in pads if p["net"] == name and p["xy"][1] >= 51]
        connected = set(range(len(old))) if old else {0}
        while len(connected) < len(terminals):
            ia, ib = min(((a, b) for a in connected for b in range(len(terminals)) if b not in connected),
                         key=lambda pair: math.dist(terminals[pair[0]], terminals[pair[1]]))
            a, b = terminals[ia], terminals[ib]
            layer = anchor_layers.get((name, tuple(a)))
            if layer is not None:
                px, py = router.point(a)
                previous = router.owner[1-layer, py, px]
                router.owner[1-layer, py, px] = -1
            path = router.astar(a, b, nets[name].GetNetCode())
            if layer is not None:
                router.owner[1-layer, py, px] = previous
            router.apply_path(path, a, b, name)
            connected.add(ib)
        print("重连", name, len(terminals), flush=True)
    for name, number in (("SW1", "1"), ("J_GY", "2"), ("SW1_ALT", "5")):
        next(p for p in footprints[name].Pads() if p.GetNumber() == number).SetLocalZoneConnection(pcb.ZONE_CONNECTION_FULL)
    for point in ([53, 45], [28, 37.499], [39, 45]):
        via = pcb.PCB_VIA(board)
        via.SetPosition(vector(point))
        via.SetViaType(pcb.VIATYPE_THROUGH)
        via.SetLayerPair(pcb.F_Cu, pcb.B_Cu)
        via.SetWidth(pcb.F_Cu, MM(.7))
        via.SetWidth(pcb.B_Cu, MM(.7))
        via.SetDrill(MM(.3))
        via.SetNet(nets["GND"])
        board.Add(via)
    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE.with_suffix(".kicad_pro"), TARGET.with_suffix(".kicad_pro"))
    pcb.SaveBoard(str(TARGET), board)
    board = pcb.LoadBoard(str(TARGET))
    pcb.ZONE_FILLER(board).Fill(board.Zones())
    pcb.SaveBoard(str(TARGET), board)
    return check(board)


def check(board=None):
    board = board or pcb.LoadBoard(str(TARGET))
    for cleanup in range(12):
        run("pcb", "drc", "--format", "json", "--severity-all", "--output", DEST/"规则检查.json", TARGET)
        rules = json.loads((DEST/"规则检查.json").read_text(encoding="utf-8"))
        dangling = {item["uuid"] for v in rules["violations"] if v["type"] == "track_dangling" for item in v["items"]}
        if not dangling or rules["unconnected_items"] or any(v["severity"] == "error" for v in rules["violations"]):
            break
        for track in list(board.GetTracks()):
            if track.m_Uuid.AsString() in dangling:
                RETIRED.append(track)
                board.Remove(track)
        pcb.ZONE_FILLER(board).Fill(board.Zones())
        pcb.SaveBoard(str(TARGET), board)
    errors = [v for v in rules["violations"] if v["severity"] == "error"]
    if errors or rules["unconnected_items"]:
        print(json.dumps(errors+rules["unconnected_items"], ensure_ascii=False, indent=2), flush=True)
        raise RuntimeError((len(errors), len(rules["unconnected_items"])))
    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    audit = {"错误": 0, "未连接": 0, "警告": dict(Counter(v["type"] for v in rules["violations"])),
             "实际孔位核对": {name: [{"焊盘号": p.GetNumber(), "网络": p.GetNetname(),
                                     "装配坐标毫米": [round(-position(p.GetPosition())[0]-3, 6), round(45-position(p.GetPosition())[1], 6)],
                                     "孔径毫米": position(p.GetDrillSize())} for p in fp.Pads()]
                           for name, fp in footprints.items()}}
    for name, center in PASSIVE_CENTERS.items():
        actual = audit["实际孔位核对"][name]
        for i, pad in enumerate(sorted(actual, key=lambda p: p["焊盘号"])):
            assert math.dist(pad["装配坐标毫米"], [center[0]+(-5.08 if i == 0 else 5.08), center[1]]) < 1e-5
    for name, holes in WIRE_HOLES.items():
        for pad in audit["实际孔位核对"][name]:
            assert math.dist(pad["装配坐标毫米"], holes[pad["焊盘号"]]) < 1e-5
    (DEST/"孔位与布线核对.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    run("pcb", "export", "glb", "--force", "--board-only", "--include-tracks", "--include-pads", "--include-zones",
        "--include-silkscreen", "--include-soldermask", "--output", TARGET.with_suffix(".glb"), TARGET)
    TARGET.with_suffix(".kicad_prl").unlink(missing_ok=True)
    return board


def fabricate(board):
    out = RELEASE/"电路板"
    gerber = out/"制造文件"
    gerber.mkdir(parents=True, exist_ok=True)
    for extension in (".kicad_pcb", ".kicad_pro"):
        shutil.copy2(TARGET.with_suffix(extension), out/("gunmouse-final"+extension))
    run("pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts",
        "--subtract-soldermask", "--output", gerber, TARGET)
    run("pcb", "export", "drill", "--format", "excellon", "--drill-origin", "absolute", "--excellon-zeros-format", "decimal",
        "--excellon-oval-format", "alternate", "--excellon-units", "mm", "--excellon-separate-th", "--output", gerber, TARGET)
    holes = {"PTH": [], "NPTH": []}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            size = position(pad.GetDrillSize())
            if min(size) > 0:
                holes["NPTH" if pad.GetAttribute() == pcb.PAD_ATTRIB_NPTH else "PTH"].append({"中心毫米": position(pad.GetPosition()), "孔径毫米": size})
    for track in board.GetTracks():
        if isinstance(track, pcb.PCB_VIA):
            diameter = pcb.ToMM(track.GetDrill())
            holes["PTH"].append({"中心毫米": position(track.GetPosition()), "孔径毫米": [diameter, diameter]})
    counts = {kind: audit_drill(gerber/f"gunmouse-final-{kind}.drl", values) for kind, values in holes.items()}
    files = sorted(gerber.iterdir())
    assert len(files) == 10 and {p.suffix for p in files} == {".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gm1", ".gbrjob", ".drl"}
    archive = RELEASE/"枪型飞鼠_最终版_上传打板.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in files:
            z.write(path, path.name)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = {"铜层数": 2, "板厚毫米": 1.6, "铜厚微米": [35, 35], "钻孔核对": counts,
              "主板SHA256": digest(TARGET), "打板压缩包SHA256": digest(archive),
              "文件SHA256": {p.name: digest(p) for p in files}}
    (out/"制造核对.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    fabricate(route())
