"""同步长方条正式预览的摇杆、接线孔和机械孔，仅生成独立预览板。"""
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pcbnew as pcb
import generate_gen2_pcb as generator
from preview_local_mount_pcb import position, segment_distance

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shell/快速结构预览/pcb/preview-regular-mount.kicad_pcb"
OUT = ROOT / "shell/长方条正式预览/pcb"
TARGET = OUT / "preview-rectangular-mount.kicad_pcb"
MM = pcb.FromMM
RETIRED = []


def vector(point):
    return pcb.VECTOR2I(*[MM(value) for value in point])


def xy(point):
    return [-point[0]-3, 45-point[1]]


def main():
    board = pcb.LoadBoard(str(SOURCE))
    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    areas = []
    for name, movement in (("SW1", [3.2, 0]), ("J_TRIG", [0, 3]), ("J_SWITCH", [0, -4])):
        fp = footprints[name]
        old = {pad.GetNumber(): position(pad.GetPosition()) for pad in fp.Pads()}
        fp.Move(vector(movement))
        for pad in fp.Pads():
            start, end = old[pad.GetNumber()], position(pad.GetPosition())
            areas.extend([(start, 1.8, 2.6), (end, 1.8, 2.6)])
        for drawing in board.GetDrawings():
            if isinstance(drawing, pcb.PCB_TEXT) and (drawing.GetText().startswith(name+".") or (name == "J_SWITCH" and drawing.GetText() in {"ON", "OFF"})):
                drawing.Move(vector(movement))
    switch = footprints["SW2"]
    destinations = {"1": (-30, -14.54), "2": (-30, -12)}
    old_switch = {pad.GetNumber(): position(pad.GetPosition()) for pad in switch.Pads()}
    switch.Move(vector(xy((-30, -13.27)))-switch.GetPosition())
    switch.SetValue("右键软线接点")
    for pad in switch.Pads():
        start, end = old_switch[pad.GetNumber()], xy(destinations[pad.GetNumber()])
        pad.SetPosition(vector(end))
        areas.extend([(start, 1.8, 2.6), (end, 1.8, 2.6)])
    # 此处仅作两根软线焊孔；旧微动本体丝印不再对应新孔位。
    for item in list(switch.GraphicalItems()):
        RETIRED.append(item)
        switch.Remove(item)
    for drawing in list(board.GetDrawings()):
        if isinstance(drawing, pcb.PCB_TEXT) and drawing.GetText().startswith("SW2."):
            RETIRED.append(drawing)
            board.Remove(drawing)
    for label, point in [('SW2.2', [30, 57]), ('SW2.1 GND', [27, 61.4])]:
        text = pcb.PCB_TEXT(board)
        text.SetText(label)
        text.SetPosition(vector(point))
        text.SetTextSize(vector([.8, .8]))
        text.SetTextThickness(MM(.1))
        text.SetLayer(pcb.F_SilkS)
        board.Add(text)
    hole = footprints["H_JOY_LOCAL_2"]
    new_hole = xy((-36.5, -4))
    movement = vector(new_hole)-hole.GetPosition()
    hole.Move(movement)
    for zone in board.Zones():
        if zone.GetZoneName() == "SCREW_CLEAR_H_JOY_LOCAL_2":
            zone.Move(movement)
    areas.append((new_hole, 3.15, 3.8))
    affected = {"JOY_SW", "JOY_X", "JOY_Y", "3V3", "BTN_R", "TRIG"}
    for track in board.GetTracks():
        a, b = position(track.GetStart()), position(track.GetEnd())
        if any(segment_distance(c, a, b) < radius for c, radius, _ in areas):
            affected.add(track.GetNetname())
    # 新机械孔覆盖旧摇杆信号过孔，完整重排这些网络，避免留下孔内铜线或悬空过孔。
    for track in list(board.GetTracks()):
        if track.GetNetname() in affected:
            RETIRED.append(track)
            board.Remove(track)
    env = generator.legacy_functions()
    nets = {str(n.GetNetname()): n for n in board.GetNetsByNetcode().values()}
    pads = [{"xy": position(p.GetPosition()), "size": position(p.GetSize()),
             "drill": position(p.GetDrillSize()), "net_code": p.GetNetCode()}
            for fp in board.GetFootprints() for p in fp.Pads()]
    config = json.loads((ROOT/"pcb/carrier-config.json").read_text(encoding="utf-8"))
    router = env["Router"](board, nets, pads, [xy(p) for p in config["pcb"]["outline_xz"]])
    for track in board.GetTracks():
        if isinstance(track, pcb.PCB_VIA):
            router.mark_disc(position(track.GetPosition()), pcb.ToMM(track.GetWidth(pcb.F_Cu))/2+.5, track.GetNetCode(), [0, 1])
        else:
            a, b = position(track.GetStart()), position(track.GetEnd())
            count = max(1, math.ceil(math.dist(a, b)/.0635))
            for step in range(count+1):
                router.mark_disc([a[i]+(b[i]-a[i])*step/count for i in (0, 1)],
                                 pcb.ToMM(track.GetWidth())/2+.5, track.GetNetCode(),
                                 [0 if track.GetLayer() == pcb.F_Cu else 1])
    gx = router.x0+np.arange(router.w)*generator.GRID
    gy = router.y0+np.arange(router.h)*generator.GRID
    xx, yy = np.meshgrid(gx, gy)
    for zone in board.Zones():
        if not zone.GetIsRuleArea():
            continue
        ring = zone.Outline().COutline(0)
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
    # 非镀孔的孔边铜距离按板框0.5毫米要求，而非普通0.25毫米铜间距。
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcb.PAD_ATTRIB_NPTH:
                router.mark_disc(position(pad.GetPosition()), max(position(pad.GetDrillSize()))/2+.8, -1, [0, 1])
    start, end = [28.42, 36.5], [27.3, 38.2]
    router.apply_path(router.astar(start, end, nets['GND'].GetNetCode()), start, end, 'GND')
    for net in sorted(affected-{"GND"}, key=lambda name: ({"BTN_R": 0, "TRIG": 1, "JOY_X": 2, "JOY_Y": 3, "JOY_SW": 4, "3V3": 7, "BAT_RAW": 8, "BAT_SW": 9}.get(name, 5), name)):
        terminals = [p["xy"] for p in pads if p["net_code"] == nets[net].GetNetCode()]
        connected = {0}
        while len(connected) < len(terminals):
            ia, ib = min(((ia, ib) for ia in connected for ib in range(len(terminals)) if ib not in connected),
                         key=lambda pair: math.dist(terminals[pair[0]], terminals[pair[1]]))
            start, end = terminals[ia], terminals[ib]
            router.apply_path(router.astar(start, end, nets[net].GetNetCode()), start, end, net)
            connected.add(ib)
        print("重连网络", net, len(terminals), flush=True)
    # 给热焊盘补到开放接地铜区的短线，由填铜后的连通检查验证。
    for start, end in [([38.98, 40], [43, 43]),
                       ([39.504, 27.26], [42, 30]), ([37, 63.5], [40, 64])]:
        router.apply_path(router.astar(start, end, nets['GND'].GetNetCode()), start, end, 'GND')
    # 三处地脚由0.3毫米短铜线接地；关闭该焊盘直接吸附孤立铜区，避免只剩单条热桥。
    for name, number in [('SW1', '1'), ('C_JOY_X', '2'), ('J_GY', '2')]:
        next(p for p in footprints[name].Pads() if p.GetNumber() == number).SetLocalZoneConnection(pcb.ZONE_CONNECTION_NONE)
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE.with_suffix(".kicad_pro"), TARGET.with_suffix(".kicad_pro"))
    pcb.SaveBoard(str(TARGET), board)
    board = pcb.LoadBoard(str(TARGET))
    pcb.ZONE_FILLER(board).Fill(board.Zones())
    pcb.SaveBoard(str(TARGET), board)
    report = OUT/"规则检查.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--output", str(report), str(TARGET)], check=True)
    data = json.loads(report.read_text(encoding="utf-8"))
    errors = [v for v in data.get("violations", []) if v["severity"] == "error"]
    disconnected = data.get("unconnected_items", [])
    print("规则检查", len(errors), "错误", len(disconnected), "未连接", flush=True)
    if errors or disconnected:
        print(json.dumps(errors+disconnected, ensure_ascii=False, indent=2), flush=True)
        raise RuntimeError("正式预览板仍有规则问题")
    subprocess.run(["kicad-cli", "pcb", "export", "glb", "--force", "--board-only", "--include-tracks", "--include-pads", "--include-zones", "--include-silkscreen", "--include-soldermask", "--output", str(TARGET.with_suffix(".glb")), str(TARGET)], check=True)
    TARGET.with_suffix(".kicad_prl").unlink(missing_ok=True)
    summary = {"错误": len(errors), "未连接": len(disconnected),
               "警告": dict(Counter(v["type"] for v in data["violations"] if v["severity"] != "error")),
               "摇杆平移毫米": [-3.2, 0, 0], "支座固定孔装配坐标毫米": [-36.5, -4],
               "右键两根接线孔装配坐标毫米": destinations,
               "左键接线孔装配坐标毫米": {"1": [-25.5, -12], "2": [-25.5, -9.46]},
               "电源开关中心装配坐标毫米": [-53, 8],
               "用途": "正式装配预览板；尚未替换制造交付包，不替代实物试装与通电检查"}
    checked = {}
    for name in ['SW1', 'SW2', 'J_TRIG', 'J_SWITCH', 'H_JOY_LOCAL_2', 'H3', 'H4', 'H_BODY_5']:
        checked[name] = [{"焊盘号": pad.GetNumber(), "网络": pad.GetNetname(),
                          "装配坐标毫米": [round(-position(pad.GetPosition())[0]-3, 6), round(45-position(pad.GetPosition())[1], 6)],
                          "孔径毫米": position(pad.GetDrillSize())}
                         for pad in footprints[name].Pads()]
    summary['实际孔位核对'] = checked
    (OUT/"孔位与布线核对.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
