"""更新第二代载板；复用 Git 历史中已验证的路由及制造导出函数。

运行环境：KiCad 9 的 Python、NumPy、SciPy。不会改动 E 盘嘉立创工程。
仅在临时目录中修改、填铜和检查；检查成功后更新 pcb/ 中的同名文件。
"""
from __future__ import annotations

import ast
import csv
import hashlib
import heapq
import json
import math
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import pcbnew as pcb
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[1]
PCB_DIR = ROOT / "pcb"
BOARD_NAME = "gun-mouse-supermini-carrier.kicad_pcb"
CONFIG_NAME = "carrier-config.json"
AFFECTED = {"JOY_SW", "JOY_X", "JOY_Y", "3V3", "BAT_RAW", "BAT_SW", "VBUS_DET", "GND"}
SOURCE_COMMIT = "e2848bd"
SOURCE_PATH = "experiments/30g-onepiece-test-shell/build_carrier_pcb.py"
MM = pcb.FromMM
GRID, TRACK_W, CLEARANCE, VIA_D, VIA_DRILL = .254, .30, .25, .70, .30
# KiCad 9 的移除接口把所有权交给 Python；保留对象到导出结束，规避绑定析构问题。
RETIRED = []


def legacy_functions():
    """读取指定历史版本，避免恢复旧目录或复制整套旧交付。"""
    source = subprocess.check_output(["git", "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}"], cwd=ROOT, text=True)
    source = source.replace('"wirebank":8,"joystick":1,"microswitch":1',
                            '"wirebank":7,"joystick":1,"microswitch":1,"power_switch":1')
    source = source.replace('bank("J_SWITCH",["BAT_RAW","BAT_SW"])',
                            'bank("J_SWITCH",["BAT_RAW","BAT_SW",""])')
    source = source.replace('"microswitch":"#d9d9df"}',
                            '"microswitch":"#d9d9df","power_switch":"#d7ead2"}')
    source = source.replace('SS-01GL13 COM', 'SS-01GL COM').replace('SS-01GL13 NO', 'SS-01GL NO')
    source = source.replace('Carrier PCB only; prototype module topology and physical fit checks remain necessary',
                            '仅载板制造文件；模块供电路径与实物装配仍需首件验证')
    source = source.replace('No KiCad schematic supplied; actual PTHs checked against circuit/net/pad contract, independent source review provided',
                            '未提供KiCad原理图；已逐一核对实际金属化通孔与配置中的网络、孔位和孔径')
    source = source.replace('DRC verifies board geometry and routing; real module power topology, physical lead fit and solder workmanship require prototype checks',
                            '设计规则检查验证板上几何和布线；实物引脚适配、焊接、供电及操作功能仍需验证')
    source = source.replace('Not performed: no KiCad schematic supplied; explicit circuit/net/pad contract and independent written review are provided',
                            '未执行原理图电气规则检查：未提供KiCad原理图；已核对实际焊盘与配置定义')
    source = source.replace('            if part["kind"]=="wirebank":',
                            '            if part["kind"]=="wirebank" or part["ref"] in {"SW1", "J_SWITCH"}:')
    names = {"write_json", "digest", "kxy", "vec", "add_text", "line", "configure_default_netclass",
             "Router", "add_ground_zone", "validate_electrical", "assembly_map", "export_files"}
    tree = ast.parse(source)
    selected = ast.Module(body=[n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names], type_ignores=[])
    env = dict(globals())
    exec(compile(selected, SOURCE_PATH, "exec"), env)
    env["render_previews"] = lambda: None
    return env


def configuration():
    config = json.loads((PCB_DIR / CONFIG_NAME).read_text(encoding="utf-8"))
    if config["version"] == "supermini-tht-carrier-v2":
        return config
    assert config["version"] == "supermini-tht-carrier-v1"
    config["version"] = "supermini-tht-carrier-v2"
    config["power"]["battery_switch"] = "BAT_RAW -> J_SWITCH board-mounted SPDT pins 1-2 -> BAT_SW; pin3 isolated"
    parts = {p["ref"]: p for p in config["parts"]}
    joy = parts["SW1"]
    # 用户实物仅能由旧板背面插入；围绕真实轴心作左右镜像，纠正孔型手性。
    # 不能围绕旧封装原点 (31.201,22.781) 镜像，它不是轴心 (30,22)。
    for p in joy["pads"] + joy["npth"]:
        p["xz"][0] = round(-66 - p["xz"][0], 4)
    joy["position_xz"] = [-33, 23]
    for envelope in [joy["envelope"], *[e for e in joy["envelopes"] if e["kind"] == "box"]]:
        envelope["x"] = [round(-66 - x, 4) for x in reversed(envelope["x"])]
    joy["source"] = "Alps RKJXV1224005 official drawing plus user physical reverse-side fit; all 16 holes mirrored about shaft Kx=30 mm"
    joy["assembly"] = "Top-side insertion; no added mechanical travel limit; verify all 16 holes using the 1:1 drawing and actual part before ordering"
    switch = parts["J_SWITCH"]
    switch.update(kind="power_switch", value="SS-12D01-G030", position_xz=[-57.3, 15],
                  purpose="Board-mounted battery-positive switch: 1=BAT_RAW, 2=BAT_SW common, 3=isolated; no external switch wire",
                  envelope={"x": [-59.25, -55.35], "z": [10.6, 19.4], "y_above_board": 6.5, "lead_below_board": 1},
                  envelope_basis="G-Switch SS-12D01-G030: body 8.8x3.9x3.5 mm, actuator 3 mm, three leads at 2.5 mm pitch; clip tails <=1 mm",
                  source="https://datasheet.lcsc.com/datasheet/pdf/af2c04499242010f9bc8773a044bd472.pdf?productCode=C5446804")
    switch["pads"] = [{"number": str(i + 1), "xz": [-57.3, z], "net": net,
                       "drill": [1, 1], "size": [1.8, 1.8], "shape": "circle"}
                      for i, (z, net) in enumerate([(17.5, "BAT_RAW"), (15, "BAT_SW"), (12.5, "")])]
    # 给 H4 螺母让出空间，不再要求把电容腿临时弯开。
    cap = parts["C_RAIL"]
    cap["position_xz"][0] = round(cap["position_xz"][0] - .6, 4)
    for p in cap["pads"]:
        p["xz"][0] = round(p["xz"][0] - .6, 4)
    cap["envelope"]["x"] = [round(x - .6, 4) for x in cap["envelope"]["x"]]
    parts["J_TRIG"]["purpose"] = "Existing SS-01GL COM/NO wired trigger; no PCB slots"
    return config


def relocate(board, config, env):
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for info in config["parts"]:
        if info["ref"] not in {"SW1", "J_SWITCH", "C_RAIL"}:
            continue
        fp = fps[info["ref"]]
        print(f"更新封装 {info['ref']}", flush=True)
        fp.SetPosition(env["vec"](env["kxy"](info["position_xz"])))
        fp.SetValue(info["value"])
        numbered = {p.GetNumber(): p for p in fp.Pads() if p.GetNumber()}
        for pinfo in info["pads"]:
            p = numbered.get(pinfo["number"])
            if p is None:
                p = pcb.PAD(fp)
                p.SetNumber(pinfo["number"])
                p.SetAttribute(pcb.PAD_ATTRIB_PTH)
                p.SetShape(pcb.PAD_SHAPE_CIRCLE)
                p.SetLayerSet(pcb.PAD.PTHMask())
                fp.Add(p)
            p.SetPosition(env["vec"](env["kxy"](pinfo["xz"])))
            p.SetSize(env["vec"](pinfo["size"]))
            p.SetDrillSize(env["vec"](pinfo["drill"]))
            p.SetNet(board.FindNet(pinfo["net"]) if pinfo["net"] else board.FindNet(0))
        for p, pinfo in zip([p for p in fp.Pads() if not p.GetNumber()], info["npth"]):
            p.SetPosition(env["vec"](env["kxy"](pinfo["xz"])))
        for item in list(fp.GraphicalItems()):
            RETIRED.append(item)
            fp.Remove(item)
        e = info["envelope"]
        a, b = env["kxy"]([max(e["x"]), max(e["z"])]), env["kxy"]([min(e["x"]), min(e["z"])])
        for layer, margin, width in [(pcb.F_CrtYd, .25, .05), (pcb.F_Fab, 0, .1)]:
            corners = [(a[0]-margin, a[1]-margin), (b[0]+margin, a[1]-margin),
                       (b[0]+margin, b[1]+margin), (a[0]-margin, b[1]+margin)]
            for start, end in zip(corners, corners[1:] + corners[:1]):
                line = pcb.PCB_SHAPE(fp)
                line.SetShape(pcb.SHAPE_T_SEGMENT)
                line.SetStart(env["vec"](start)); line.SetEnd(env["vec"](end))
                line.SetWidth(MM(width)); line.SetLayer(layer); fp.Add(line)
    for item in list(board.GetDrawings()):
        if isinstance(item, pcb.PCB_TEXT):
            xy = [pcb.ToMM(item.GetPosition().x), pcb.ToMM(item.GetPosition().y)]
            if item.GetText() == "S3 THT CARRIER v1":
                item.SetText("S3 THT CARRIER v2")
            elif 49 < xy[0] < 56.5 and 25 < xy[1] < 34:
                RETIRED.append(item)
                board.Remove(item)
            elif item.GetText() == "C_RAIL":
                item.SetPosition(env["vec"]([xy[0] + .6, xy[1]]))
    # 此地焊盘的底层被信号走线包围；直接连接铜面，避免假热焊桥孤岛。
    fps["C_JOY_Y"].FindPadByNumber("2").SetLocalZoneConnection(pcb.ZONE_CONNECTION_FULL)
    env["add_text"](board, "PWR", [50.4, 27], .8)
    env["add_text"](board, "ON", [50.5, 29], .8)
    env["add_text"](board, "OFF", [50.5, 32.5], .8)


def generate():
    config = configuration()
    env = legacy_functions()
    with tempfile.TemporaryDirectory(prefix="gun-mouse-gen2-") as tmp:
        stage = Path(tmp)
        env.update(HERE=stage, OUT=stage / "pcb", CONFIG=stage / CONFIG_NAME,
                   BOARD_FILE=stage / "pcb" / BOARD_NAME)
        env["OUT"].mkdir()
        env["write_json"](env["CONFIG"], config)
        board_path = env["BOARD_FILE"]
        shutil.copy2(PCB_DIR / BOARD_NAME, board_path)
        shutil.copy2((PCB_DIR / BOARD_NAME).with_suffix(".kicad_pro"), board_path.with_suffix(".kicad_pro"))
        board = pcb.LoadBoard(str(board_path))
        relocate(board, config, env)
        for track in list(board.GetTracks()):
            if track.GetNetname() in AFFECTED:
                RETIRED.append(track)
                board.Remove(track)
        for zone in list(board.Zones()):
            RETIRED.append(zone)
            board.Remove(zone)
        nets = {str(n.GetNetname()): n for n in board.GetNetsByNetcode().values()}
        pads = []
        for fp in board.GetFootprints():
            for p in fp.Pads():
                pads.append({"ref": fp.GetReference(), "number": p.GetNumber(), "xy": [pcb.ToMM(p.GetPosition().x), pcb.ToMM(p.GetPosition().y)],
                             "net": p.GetNetname(), "net_code": p.GetNetCode(), "size": [pcb.ToMM(p.GetSize().x), pcb.ToMM(p.GetSize().y)],
                             "drill": [pcb.ToMM(p.GetDrillSize().x), pcb.ToMM(p.GetDrillSize().y)]})
        outline = [env["kxy"](p) for p in config["pcb"]["outline_xz"]]
        router = env["Router"](board, nets, pads, outline)
        for track in board.GetTracks():
            net = track.GetNetCode()
            if isinstance(track, pcb.PCB_VIA):
                xy = [pcb.ToMM(track.GetPosition().x), pcb.ToMM(track.GetPosition().y)]
                router.mark_disc(xy, pcb.ToMM(track.GetWidth(pcb.F_Cu)) / 2 + TRACK_W/2 + CLEARANCE + .18, net, [0, 1])
                router.mark_hole(xy, pcb.ToMM(track.GetDrillValue()) / 2 + VIA_DRILL/2 + .25 + .18)
            else:
                a = [pcb.ToMM(track.GetStart().x), pcb.ToMM(track.GetStart().y)]
                b = [pcb.ToMM(track.GetEnd().x), pcb.ToMM(track.GetEnd().y)]
                steps = max(1, math.ceil(math.dist(a, b) / (GRID / 2)))
                for step in range(steps + 1):
                    xy = [a[i] + (b[i]-a[i])*step/steps for i in (0, 1)]
                    router.mark_disc(xy, pcb.ToMM(track.GetWidth())/2 + TRACK_W/2 + CLEARANCE + .18, net,
                                     [0 if track.GetLayer() == pcb.F_Cu else 1])
        router.pads = [p for p in pads if p["net"] in AFFECTED]
        router.route()
        board = env["add_ground_zone"](board, nets, outline)
        old_layout = json.loads((PCB_DIR / "carrier-layout.json").read_text(encoding="utf-8"))
        router.route_records = [r for r in old_layout["routed_connections"] if r["net"] not in AFFECTED] + router.route_records
        router.via_count = sum(isinstance(t, pcb.PCB_VIA) for t in board.GetTracks())
        try:
            env["export_files"](config, board, router, pads)
        except RuntimeError:
            report = env["OUT"] / "drc-report.json"
            if report.exists():
                print(report.read_text(encoding="utf-8"), flush=True)
            raise
        for item in env["OUT"].rglob("*"):
            if item.is_file() and "Gerber" not in item.relative_to(env["OUT"]).parts and item.suffix != ".kicad_prl":
                dest = PCB_DIR / item.relative_to(env["OUT"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
        shutil.copy2(env["CONFIG"], PCB_DIR / CONFIG_NAME)
        print("第二代载板及同名制造文件已更新；未进行实物插装或通电验收。", flush=True)


if __name__ == "__main__":
    generate()
