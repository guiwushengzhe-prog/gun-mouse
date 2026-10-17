"""仅在快速预览目录增加摇杆支座的两个就近穿板孔。"""
from pathlib import Path
import math
import json
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
import pcbnew as pcb
import generate_gen2_pcb as generator
from preview_local_joystick_mount import LOCAL_HOLES as HOLES

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pcb/gun-mouse-supermini-carrier.kicad_pcb"
OUT = ROOT / "shell/快速结构预览/pcb"
MM = pcb.FromMM
RETIRED = []


def xy(point):
    return [-point[0]-3, 45-point[1]]


def position(vector):
    return [pcb.ToMM(vector.x), pcb.ToMM(vector.y)]


def segment_distance(point, a, b):
    vx, vy = b[0]-a[0], b[1]-a[1]
    t = max(0, min(1, ((point[0]-a[0])*vx+(point[1]-a[1])*vy)/(vx*vx+vy*vy))) if vx*vx+vy*vy else 0
    return math.dist(point, [a[0]+t*vx, a[1]+t*vy])


def inspect(board):
    for hole in HOLES:
        center = xy(hole)
        pads = []
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                radius = max(position(pad.GetSize()))/2
                gap = math.dist(center, position(pad.GetPosition()))-radius-2.31
                if gap < .5:
                    pads.append((round(gap, 3), fp.GetReference(), pad.GetNumber(), position(pad.GetPosition())))
        tracks = []
        for track in board.GetTracks():
            radius = pcb.ToMM(track.GetWidth(pcb.F_Cu) if isinstance(track, pcb.PCB_VIA) else track.GetWidth())/2
            gap = segment_distance(center, position(track.GetStart()), position(track.GetEnd()))-radius-2.56
            if gap < .1:
                tracks.append((round(gap, 3), track.GetNetname(), board.GetLayerName(track.GetLayer()), position(track.GetStart()), position(track.GetEnd())))
        print(hole, "焊盘净距", sorted(pads), "走线", tracks, flush=True)


def key(point):
    return tuple(round(v, 6) for v in point)


def inside_intervals(a, b, centers, radius):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = dx*dx+dy*dy
    intervals = []
    for center in centers:
        ax, ay = a[0]-center[0], a[1]-center[1]
        bb = 2*(ax*dx+ay*dy)
        cc = ax*ax+ay*ay-radius*radius
        discriminant = bb*bb-4*length*cc
        if discriminant > 0:
            lo = max(0, (-bb-math.sqrt(discriminant))/(2*length))
            hi = min(1, (-bb+math.sqrt(discriminant))/(2*length))
            if hi > lo:
                intervals.append([lo, hi])
    merged = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(hi, merged[-1][1])
        else:
            merged.append([lo, hi])
    return merged


def generate():
    board = pcb.LoadBoard(str(SOURCE))
    for fp in board.GetFootprints():
        if fp.GetReference() == "SW2":
            for pad in list(fp.Pads()):
                if pad.GetNumber() == "3":
                    assert not pad.GetNetname()
                    RETIRED.append(pad)
                    fp.Remove(pad)
    inspect(board)
    centers = [xy(h) for h in HOLES]
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() != pcb.PAD_ATTRIB_NPTH:
                radius = max(position(pad.GetSize()))/2
                assert all(math.dist(c, position(pad.GetPosition())) > 2.31+radius+.05 for c in centers), (fp.GetReference(), pad.GetNumber())
    old = list(board.GetTracks())
    removed = [t for t in old if not isinstance(t, pcb.PCB_VIA)
               and any(segment_distance(c, position(t.GetStart()), position(t.GetEnd())) < 3.05 for c in centers)]
    groups = defaultdict(list)
    for track in removed:
        RETIRED.append(track)
        board.Remove(track)
        a, b = position(track.GetStart()), position(track.GetEnd())
        intervals = inside_intervals(a, b, centers, 3.7)
        at = lambda t: [a[i]+(b[i]-a[i])*t for i in (0, 1)]
        previous = 0
        for lo, hi in intervals:
            if lo > previous+1e-6:
                kept = pcb.PCB_TRACK(board)
                kept.SetStart(pcb.VECTOR2I(*[MM(v) for v in at(previous)]))
                kept.SetEnd(pcb.VECTOR2I(*[MM(v) for v in at(lo)]))
                kept.SetWidth(track.GetWidth())
                kept.SetLayer(track.GetLayer())
                kept.SetNet(track.GetNet())
                board.Add(kept)
            groups[(track.GetNetname(), track.GetLayer())].append((at(lo), at(hi)))
            previous = hi
        if previous < 1-1e-6:
            kept = pcb.PCB_TRACK(board)
            kept.SetStart(pcb.VECTOR2I(*[MM(v) for v in at(previous)]))
            kept.SetEnd(track.GetEnd())
            kept.SetWidth(track.GetWidth())
            kept.SetLayer(track.GetLayer())
            kept.SetNet(track.GetNet())
            board.Add(kept)
    jobs = []
    for (net, layer), edges in groups.items():
        adjacency = defaultdict(list)
        for a, b in edges:
            adjacency[key(a)].append(key(b))
            adjacency[key(b)].append(key(a))
        unseen = set(adjacency)
        while unseen:
            stack = [unseen.pop()]
            component = set(stack)
            while stack:
                for node in adjacency[stack.pop()]:
                    if node not in component:
                        component.add(node)
                        unseen.discard(node)
                        stack.append(node)
            ends = [p for p in component if len(adjacency[p]) == 1]
            assert len(ends) == 2, (net, ends)
            jobs.append((net, layer, *ends))
    for i, center in enumerate(centers, 1):
        fp = pcb.FOOTPRINT(board)
        fp.SetReference(f"H_JOY_LOCAL_{i}")
        fp.SetPosition(pcb.VECTOR2I(*[MM(v) for v in center]))
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        pad = pcb.PAD(fp)
        pad.SetAttribute(pcb.PAD_ATTRIB_NPTH)
        pad.SetLayerSet(pcb.PAD.UnplatedHoleMask())
        pad.SetShape(pcb.PAD_SHAPE_CIRCLE)
        pad.SetSize(pcb.VECTOR2I(MM(2.4), MM(2.4)))
        pad.SetDrillSize(pcb.VECTOR2I(MM(2.4), MM(2.4)))
        pad.SetPosition(pcb.VECTOR2I(*[MM(v) for v in center]))
        fp.Add(pad)
        board.Add(fp)
        zone = pcb.ZONE(board)
        zone.SetZoneName(f"JOY_LOCAL_SCREW_{i}")
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
        for j in range(32):
            angle = j*math.tau/32
            poly.Append(MM(center[0]+radius*math.cos(angle)), MM(center[1]+radius*math.sin(angle)))
        board.Add(zone)
    env = generator.legacy_functions()
    nets = {str(n.GetNetname()): n for n in board.GetNetsByNetcode().values()}
    pads = [{"xy": position(p.GetPosition()), "size": position(p.GetSize()), "drill": position(p.GetDrillSize()), "net_code": p.GetNetCode()}
            for fp in board.GetFootprints() for p in fp.Pads()]
    config = json.loads((ROOT/"pcb/carrier-config.json").read_text(encoding="utf-8"))
    outline = [xy(p) for p in config["pcb"]["outline_xz"]]
    router = env["Router"](board, nets, pads, outline)
    for track in board.GetTracks():
        if isinstance(track, pcb.PCB_VIA):
            router.mark_disc(position(track.GetPosition()), pcb.ToMM(track.GetWidth(pcb.F_Cu))/2+.5, track.GetNetCode(), [0, 1])
        else:
            a, b = position(track.GetStart()), position(track.GetEnd())
            count = max(1, math.ceil(math.dist(a, b)/.0635))
            for step in range(count+1):
                router.mark_disc([a[i]+(b[i]-a[i])*step/count for i in (0, 1)], pcb.ToMM(track.GetWidth())/2+.5, track.GetNetCode(), [0 if track.GetLayer() == pcb.F_Cu else 1])
    # 同时尊重旧板全部禁铜区；这次只局部绕线，不碰其余网络。
    import numpy as np
    gx = router.x0+np.arange(router.w)*generator.GRID
    gy = router.y0+np.arange(router.h)*generator.GRID
    xx, yy = np.meshgrid(gx, gy)
    for zone in board.Zones():
        if not zone.GetIsRuleArea():
            continue
        poly = zone.Outline()
        ring = poly.COutline(0)
        points = [position(ring.CPoint(i)) for i in range(ring.PointCount())]
        inside = np.zeros_like(xx, dtype=bool)
        boundary = np.full_like(xx, 1e6)
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
    for net, layer, start, end in sorted(jobs, key=lambda job: ({"TRIG": 0, "VBAT_ADC": 1, "JOY_X": 2, "JOY_Y": 3}.get(job[0], 4), -math.dist(job[2], job[3]))):
        layer_i = 0 if layer == pcb.F_Cu else 1
        for endpoint in (start, end):
            x0, x1, y0, y1, mask = router.disc_cells(endpoint, .23)
            router.owner[layer_i, y0:y1, x0:x1][mask] = nets[net].GetNetCode()
        opposite = router.owner[1-layer_i].copy()
        router.owner[1-layer_i] = -1
        try:
            path = router.astar(start, end, nets[net].GetNetCode())
        except RuntimeError:
            router.owner[1-layer_i] = opposite
            sx, sy = router.point(start)
            ex, ey = router.point(end)
            previous = (router.owner[1-layer_i, sy, sx], router.owner[1-layer_i, ey, ex])
            router.owner[1-layer_i, sy, sx] = -1
            router.owner[1-layer_i, ey, ex] = -1
            path = router.astar(start, end, nets[net].GetNetCode())
            router.owner[1-layer_i, sy, sx], router.owner[1-layer_i, ey, ex] = previous
        previous_ids = {t.m_Uuid.AsString() for t in board.GetTracks()}
        router.apply_path(path, start, end, net)
        if net == "JOY_X":
            # 此处原X/Y对角线仅有0.25毫米间隙，栅格接头局部改0.27毫米线宽。
            for track in board.GetTracks():
                if not isinstance(track, pcb.PCB_VIA) and track.m_Uuid.AsString() not in previous_ids:
                    track.SetWidth(MM(.27))
        if all(node[2] == layer_i for node in path):
            router.owner[1-layer_i] = opposite
        print("局部绕线", net, board.GetLayerName(layer), start, end, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT/"preview-local-mount.kicad_pcb"
    project = target.with_suffix(".kicad_pro")
    shutil.copy2(SOURCE.with_suffix(".kicad_pro"), project)
    pcb.SaveBoard(str(target), board)
    loaded = pcb.LoadBoard(str(target))
    pcb.ZONE_FILLER(loaded).Fill(loaded.Zones())
    pcb.SaveBoard(str(target), loaded)
    with tempfile.TemporaryDirectory(prefix="gunmouse-local-mount-") as temporary:
        report = Path(temporary)/"drc.json"
        subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error", "--output", str(report), str(target)], check=True)
        data = json.loads(report.read_text())
        errors = data.get("violations", [])+data.get("unconnected_items", [])
        if errors:
            print(json.dumps(errors, ensure_ascii=False, indent=2), flush=True)
            raise RuntimeError(f"预览板规则检查仍有{len(errors)}项")
    subprocess.run(["kicad-cli", "pcb", "export", "glb", "--force", "--board-only", "--include-tracks", "--include-pads", "--include-zones", "--include-silkscreen", "--include-soldermask", "--output", str(OUT/"preview-local-mount.glb"), str(target)], check=True)
    target.with_suffix(".kicad_prl").unlink(missing_ok=True)
    print("已导出预览板", target, flush=True)


if __name__ == "__main__":
    generate() if "--generate" in sys.argv else inspect(pcb.LoadBoard(str(SOURCE)))
