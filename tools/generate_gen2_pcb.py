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
import sys
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
                            '"wirebank":4,"module":2,"joystick":1,"microswitch":1,"power_switch":1')
    source = source.replace('bank("J_SWITCH",["BAT_RAW","BAT_SW"])',
                            'bank("J_SWITCH",["BAT_RAW","BAT_SW",""])')
    source = source.replace('"microswitch":"#d9d9df"}',
                            '"microswitch":"#d9d9df","power_switch":"#d7ead2","module":"#eadcf5"}')
    source = source.replace('bank("J_MODULE_BAT",["BAT_SW","GND"]);bank("J_MODULE_RAIL",["VBUS_SHARED"])',
                            'bank("J_MODULE_BAT",["BAT_SW","GND"])')
    source = source.replace('bank("J_GY",["3V3","GND","SCL","SDA"])',
                            'bank("J_GY",["3V3","GND","SCL","SDA","","","","","3V3","GND","","","",""])')
    source = source.replace('        a=next(p["xy"] for p in self.pads if p["ref"]=="J_GY" and p["number"]=="2")\n        b=[55.0,a[1]]\n        self.apply_path(self.astar(a,b,self.nets["GND"].GetNetCode()),a,b,"GND")', '')
    source = source.replace('("JOY_SW","VBUS_DET","VBAT_ADC","TRIG","BTN_R","JOY_X","JOY_Y","TOUCH","TOUCH_ELECTRODE","SDA","SCL","VBUS_SHARED","BAT_RAW","BAT_SW","3V3")',
                            '("SDA","SCL","JOY_SW","VBUS_DET","VBAT_ADC","TRIG","BTN_R","JOY_X","JOY_Y","TOUCH","TOUCH_ELECTRODE","VBUS_SHARED","BAT_RAW","BAT_SW","3V3")')
    source = source.replace('if part["kind"]!="wirebank":continue', 'if part["kind"] not in {"wirebank","module"}:continue')
    source = source.replace('elif part["ref"]=="J_GY":destination={"3V3":"GY-601N1 H2 VCC","GND":"GY-601N1 H2 GND","SCL":"GY-601N1 H2 SCL","SDA":"GY-601N1 H2 SDA"}[n]',
                            'elif part["ref"]=="J_GY":destination="GY-601N1 直接焊接；闲脚独立不接线"')
    source = source.replace('if part["ref"]=="J_MCU":destination=f"SuperMini GPIO{pinmap[n]}" if n in pinmap else f"SuperMini {n} pin"',
                            'if part["ref"]=="J_MCU":destination="SuperMini 直接焊接 "+part["pin_labels"][p["number"]]')
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
                            '            if part["kind"] in {"wirebank", "module"} or part["ref"] in {"SW1", "J_SWITCH"}:')
    source = source.replace('escape(part["ref"])',
                            'escape(part["ref"] + ("(B)" if part.get("mount_side") == "bottom" else ""))')
    names = {"write_json", "digest", "kxy", "vec", "add_text", "line", "configure_default_netclass",
             "Router", "add_ground_zone", "validate_electrical", "assembly_map", "export_files"}
    tree = ast.parse(source)
    selected = ast.Module(body=[n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names], type_ignores=[])
    env = dict(globals())
    exec(compile(selected, SOURCE_PATH, "exec"), env)
    env["render_previews"] = lambda: None
    return env


def base_configuration():
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


def simplify_hand_solder(config):
    """只精简当前电路及手焊区，不恢复旧模块、摇杆或安装面。"""
    removed = {"R_JOY", "R_RIGHT", "C_JOY_SW", "C_RIGHT",
               "R_RAIL_H", "R_RAIL_L", "C_RAIL"}
    config["parts"] = [p for p in config["parts"] if p["ref"] not in removed]
    # 引脚常量仍可生成；硬件检测电路已移除，该引脚不再连接或采样。
    config["firmware_pins"]["VBUS_DET"] = 10
    power = config["power"]
    for key in ("low_battery_shutdown_mv", "low_battery_delay_s", "rail_divider", "vbus_detection"):
        power.pop(key, None)
    power.update(low_battery_shutdown_enabled=False, external_power_detection_enabled=False,
                 battery_voltage_display_enabled=True)
    positions = {"R_TRIG": [-48, -10], "R_TOUCH": [-34, -10],
                 "C_TRIG": [-48, -18], "C_JOY_X": [-34, -18],
                 "R_BAT_H": [-48, -26], "R_BAT_L": [-36, -26],
                 "C_BAT": [-48, -32], "C_JOY_Y": [-34, -32]}
    for part in config["parts"]:
        if part["ref"] == "J_MCU":
            for pad in part["pads"]:
                if part["pin_labels"].get(pad["number"]) in {"5V", "10"}:
                    pad["net"] = ""
            part["purpose"] = "两排各9针直焊；保留原控制引脚和电量显示；5V及GPIO10仅机械固定、不接载板电路"
        elif part["ref"] == "SW1":
            part["purpose"] = "现有HW-504整块模块，供3.3V；按下使用内部上拉和软件消抖，两轴保留滤波，无额外限位"
        if part["ref"] not in positions:
            continue
        old_x, old_z = part["position_xz"]
        x, z = positions[part["ref"]]
        part["position_xz"] = [x, z]
        for axis, delta in (("x", x-old_x), ("z", z-old_z)):
            part["envelope"][axis] = [round(v+delta, 4) for v in part["envelope"][axis]]
        pitch = 7.62 if part["kind"] == "resistor" else 5.08
        for i, pad in enumerate(part["pads"]):
            pad.update(xz=[round(x+(-.5 if i == 0 else .5)*pitch, 4), z],
                       drill=[1.1, 1.1], size=[2.6, 2.6], shape="circle")
        part["envelope_basis"] = (
            "轴向电阻本体不超过6.4x2.6毫米，脚距7.62毫米；通孔1.1毫米、焊盘2.6毫米，剪脚后不超过1毫米"
            if part["kind"] == "resistor" else
            "直插陶瓷电容脚距5.08毫米，本体宽不超过6毫米、厚2毫米、焊后高7毫米；通孔1.1毫米、焊盘2.6毫米")
    config["status"] = "八颗电阻电容的手焊结构预览板；保留电量显示，取消低电自动休眠及外部供电识别；模块翻面孔号、摇杆新孔及重新布线待完成，不可下单制造"
    return config


def configuration(reset_layout=False):
    config = json.loads((PCB_DIR / CONFIG_NAME).read_text(encoding="utf-8"))
    if not reset_layout:
        return simplify_hand_solder(config)
    config["version"] = "supermini-tht-carrier-v2"
    config["pcb"]["kicad_mapping"] = "(Kx,Ky)=(-X-3,45-Z); MCU/GY components face +Y; HW504 PCB is perpendicular, shaft points -X"
    config["pcb"]["antenna_keepout_xz"] = [[-35, 17], [-27, 17], [-27, 28], [-35, 28]]
    config["status"] = "模块直焊工程版；SuperMini两排孔距15.24mm由用户指定暂定，最终实物尺寸仍需核实"
    config["battery"].update(
        name="602060 单节带保护锂电池",
        cell_size_mm=[6, 20, 60],
        center_xyz=[-37.7, -12.7, -72],
        size_xyz=[20, 8, 80],
        source="用户电芯602060；含保护板总长约70-80mm，按80mm包络、厚8mm容纳；保护板出线朝整机+Z，实际外皮宽厚待试放",
    )
    config["modules"]["mcu"].update(
        x=[-33.5, -10], z=[13.5, 31.5], component_face_y=2.97,
        board_thickness=1.6, front_allowance=3.5, back_wire_allowance=0,
        row_pitch_mm=15.24, row_pitch_status="用户同意先按15.24mm；不把其他批次15.46mm当成本实物尺寸",
        carrier_gap_mm=3, limits="两排各9针直焊，USB朝+X；背面B+/B-仍用两根短线，天线中央区双面禁铜、走线和过孔",
    )
    config["modules"]["imu"].update(
        x=[-58.965, -41.2], z=[11.7, 32.3], component_face_y=2.57,
        board_thickness=1.2, front_allowance=2.8, back_wire_allowance=0,
        row_pitch_mm=15.24, carrier_gap_mm=3,
        limits="左8右6，右排首末孔分别对齐左排第2和第7孔；两排全焊，闲脚独立不接线",
    )
    parts = {p["ref"]: p for p in config["parts"]}

    def pad(number, x, z, net, drill=1, size=1.8):
        return {"number": str(number), "xz": [round(x, 4), round(z, 4)], "net": net,
                "drill": [drill, drill], "size": [size, size], "shape": "circle"}

    def module(ref, value, position, pads, x, z, height, purpose, labels):
        parts[ref] = {"ref": ref, "kind": "module", "value": value,
                      "position_xz": position, "pads": pads, "npth": [], "populate": True,
                      "mount_side": "top", "pin_labels": labels,
                      "envelope": {"x": x, "z": z, "y_above_board": height, "lead_below_board": 1},
                      "envelope_basis": "用户确认排针间距2.54mm，模块与载板间隙3mm；SuperMini排距15.24mm暂定",
                      "purpose": purpose}

    left = ["TX43", "RX44", "1", "2", "3", "4", "5", "6", "7"]
    right = ["5V", "GND", "3V3", "13", "12", "11", "10", "9", "8"]
    left_nets = ["", "", "JOY_X", "JOY_Y", "", "JOY_SW", "SDA", "SCL", "TOUCH"]
    right_nets = ["VBUS_SHARED", "GND", "3V3", "", "BTN_R", "", "VBUS_DET", "VBAT_ADC", "TRIG"]
    row_pitch = config["modules"]["mcu"]["row_pitch_mm"]
    mcu_pads = [pad(i+1, -11.59-2.54*i, 22.5-row_pitch/2, net, 1.3, 2.1) for i, net in enumerate(left_nets)]
    mcu_pads += [pad(i+10, -11.59-2.54*i, 22.5+row_pitch/2, net, 1.3, 2.1) for i, net in enumerate(right_nets)]
    module("J_MCU", "ESP32-S3 SuperMini 2x9", [-21.75, 22.5], mcu_pads,
           [-33.5, -10], [13.5, 31.5], 8.1, "两排各9针直焊；固定原GPIO；5V孔仅作共享电源检测",
           {str(i+1): name for i, name in enumerate(left+right)})
    gy_left = ["3V3", "GND", "SCL", "SDA", "", "", "", ""]
    gy_right = ["3V3", "GND", "", "", "", ""]
    gy_pads = [pad(i+1, -42.504, 31-2.54*i, net, 1.1, 1.9) for i, net in enumerate(gy_left)]
    gy_pads += [pad(14-i, -57.744, 28.46-2.54*i, net, 1.1, 1.9) for i, net in enumerate(gy_right)]
    module("J_GY", "GY-601N1-LSM6DSV16X 8+6", [-50.0825, 22], gy_pads,
           [-58.965, -41.2], [11.7, 32.3], 7, "重复VCC/GND同网，SCL/SDA接原GPIO6/5；其他脚保持模块默认配置、各自空网",
           {str(i): name for i, name in enumerate(["VCC", "GND", "SCL", "SDA", "SA0", "CS", "INT1", "INT2", "PS", "INTOUT", "DT", "RC", "GND", "VCC"], 1)})
    parts["SW1"] = {"ref": "SW1", "kind": "joystick", "value": "HW-504 34x26mm", "position_xz": [-51, 20],
        "pads": [pad(i+1, -51, 25.08-2.54*i, net, 1.2, 2) for i, net in enumerate(["GND", "3V3", "JOY_X", "JOY_Y", "JOY_SW"])],
        "npth": [], "populate": True, "mount_side": "bottom", "mount_face_y": -3.23,
        "axis_direction_xyz": [-1, 0, 0], "module_board_xyz": [[-51.8, -50.2], [-38, -4], [7, 33]],
        "envelope": {"x": [-51.8, -50.2], "z": [7, 33], "y_above_board": 34.77, "lead_below_board": 1},
        "envelope_basis": "用户实测黑板34x26mm、五针2.54mm；按现有弯针垂直插入载板，模块向背面伸出",
        "assembly": "五针从Z高到低：GND、3V3、VRX、VRY、SW；摇杆轴-X，接触按键逻辑和GPIO不变",
        "purpose": "现有HW-504整块模块，供3.3V；保留原外部上拉及滤波，无额外限位"}
    switch = parts["J_SWITCH"]
    switch.update(value="SS12D10 G5", position_xz=[-41.5, -38.3],
        pads=[pad(i+1, x, -38.3, net, 1.8, 3) for i, (x, net) in enumerate(zip([-46.2, -41.5, -36.8], ["BAT_RAW", "BAT_SW", ""]))],
        envelope={"x": [-47.95, -35.05], "z": [-41.75, -34.85], "y_above_board": 11.9, "lead_below_board": 1},
        envelope_basis="用户SS12D10 G5尺寸图：相邻4.7mm、首末9.4mm，扁脚1.3x0.8mm，采用1.8mm圆孔/3mm焊盘；柄5mm",
        purpose="1=BAT_RAW、2=BAT_SW公共脚、3独立空网；拨向1脚侧为ON；电池两线永久焊板，不接外置开关线",
        source="用户购买的SS12D10 G5商品尺寸图")
    config["power"]["battery_switch"] = "BAT_RAW -> SS12D10 G5 pins 1-2 -> BAT_SW; pin3 isolated; toward pin1=ON"
    for ref, coords in {"J_BAT": [(-55.7, -36), (-55.7, -38.54)],
                        "J_MODULE_BAT": [(-19, 35), (-21.54, 35)]}.items():
        part = parts[ref]
        part["position_xz"] = list(coords[0])
        for info, (x, z) in zip(part["pads"], coords): info["xz"] = [x, z]
        part["envelope"]["x"] = [min(x for x, z in coords)-1, max(x for x, z in coords)+1]
        part["envelope"]["z"] = [min(z for x, z in coords)-1, max(z for x, z in coords)+1]
    parts.pop("J_MODULE_RAIL", None)
    config["parts"] = list(parts.values())
    # 保持板框和电路数量，把手焊区域的异网焊盘拉开。
    positions = {
        "R_JOY": [-47, -11], "R_RIGHT": [-35.6, -11],
        "R_TRIG": [-47, -18], "R_TOUCH": [-35.6, -18],
        "R_BAT_H": [-47, -25], "R_BAT_L": [-35.6, -25],
        "R_RAIL_H": [-47, -32], "R_RAIL_L": [-35.6, -32],
        "C_JOY_SW": [-42, -7.5], "C_RIGHT": [-32, -7.5],
        "C_TRIG": [-42, -14.5], "C_BAT": [-42, -28.5], "C_RAIL": [-32.6, -28.5],
        "C_JOY_X": [-42, -21.5], "C_JOY_Y": [-32, -21.5],
    }
    for part in config["parts"]:
        if part["kind"] not in {"resistor", "capacitor"}:
            continue
        old_x, old_z = part["position_xz"]
        x, z = positions.get(part["ref"], part["position_xz"])
        part["position_xz"] = [x, z]
        for axis, delta in [("x", x-old_x), ("z", z-old_z)]:
            part["envelope"][axis] = [round(v+delta, 4) for v in part["envelope"][axis]]
        pitch = 7.62 if part["kind"] == "resistor" else 5.08
        for i, pad in enumerate(part["pads"]):
            pad["xz"] = [round(x+(-.5 if i == 0 else .5)*pitch, 4), z]
        if part["kind"] == "capacitor":
            part["envelope_basis"] = "采购直插陶瓷电容，脚距5.08mm，本体宽<=6mm、厚<=2mm、焊后高<=7mm；不采用2.54mm脚距"
    return simplify_hand_solder(config)


def write_bom(config):
    """更新同名物料清单；不生成额外交付或制造包。"""
    with (PCB_DIR / "BOM.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Reference", "Value / Type", "Qty", "Assembly", "Purchase / Fit Requirement", "Nets / Purpose"])
        for part in config["parts"]:
            if not part.get("populate", True):
                continue
            assembly = ("现成模块两排针手焊到载板" if part["kind"] == "module" else
                        "导线直接焊接" if part["kind"] == "wirebank" else "直插手工焊接")
            writer.writerow([part["ref"], part["value"], 1, assembly,
                             part.get("envelope_basis", ""), part.get("purpose", part.get("assembly", ""))])


def relocate(board, config, env):
    # 保留当前载板的原板框和四个安装孔，更新所有实装孔位；不恢复历史PCB。
    for fp in list(board.GetFootprints()):
        if fp.GetReference().startswith("H"):
            continue
        RETIRED.append(fp)
        board.Remove(fp)
    for info in config["parts"]:
        fp = pcb.FOOTPRINT(board)
        fp.SetReference(info["ref"])
        fp.SetFPID(pcb.LIB_ID("GunMouseHandSolder", info["ref"]))
        fp.SetAttributes(pcb.FP_THROUGH_HOLE)
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        board.Add(fp)
        print(f"更新封装 {info['ref']}", flush=True)
        if info.get("mount_side") == "bottom" and fp.GetLayer() != pcb.B_Cu:
            fp.Flip(env["vec"](env["kxy"](info["position_xz"])), pcb.FLIP_DIRECTION_LEFT_RIGHT)
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
            p.SetShape(pcb.PAD_SHAPE_OVAL if pinfo["shape"] == "oval" else pcb.PAD_SHAPE_CIRCLE)
            p.SetDrillShape(pcb.PAD_DRILL_SHAPE_OBLONG if pinfo["drill"][0] != pinfo["drill"][1] else pcb.PAD_DRILL_SHAPE_CIRCLE)
            p.SetNet(board.FindNet(pinfo["net"]) if pinfo["net"] else board.FindNet(0))
        for p, pinfo in zip([p for p in fp.Pads() if not p.GetNumber()], info["npth"]):
            p.SetPosition(env["vec"](env["kxy"](pinfo["xz"])))
        for item in list(fp.GraphicalItems()):
            RETIRED.append(item)
            fp.Remove(item)
        e = info["envelope"]
        a, b = env["kxy"]([max(e["x"]), max(e["z"])]), env["kxy"]([min(e["x"]), min(e["z"])])
        courtyard, fab = (pcb.B_CrtYd, pcb.B_Fab) if info.get("mount_side") == "bottom" else (pcb.F_CrtYd, pcb.F_Fab)
        for layer, margin, width in [(courtyard, .25, .05), (fab, 0, .1)]:
            corners = [(a[0]-margin, a[1]-margin), (b[0]+margin, a[1]-margin),
                       (b[0]+margin, b[1]+margin), (a[0]-margin, b[1]+margin)]
            for start, end in zip(corners, corners[1:] + corners[:1]):
                line = pcb.PCB_SHAPE(fp)
                line.SetShape(pcb.SHAPE_T_SEGMENT)
                line.SetStart(env["vec"](start)); line.SetEnd(env["vec"](end))
                line.SetWidth(MM(width)); line.SetLayer(layer); fp.Add(line)
    for item in list(board.GetDrawings()):
        if isinstance(item, pcb.PCB_TEXT):
            RETIRED.append(item)
            board.Remove(item)
    env["add_text"](board, "S3 MODULE CARRIER v2", env["kxy"]([-39, 38]), .8)
    env["add_text"](board, "BAT OFF BEFORE PC USB", env["kxy"]([-41, 5]), .8)
    env["add_text"](board, "ON", env["kxy"]([-49.8, -38.3]), .8)
    env["add_text"](board, "OFF", env["kxy"]([-32.7, -38.3]), .8)
    for part in config["parts"]:
        for p in part["pads"]:
            name = part.get("pin_labels", {}).get(p["number"], p["net"] or "NC")
            env["add_text"](board, part["ref"]+"."+p["number"]+" "+name,
                            env["kxy"](p["xz"]), .6, pcb.F_Fab)


def antenna_keepout(board, config, env):
    zone = pcb.ZONE(board)
    zone.SetIsRuleArea(True)
    layers = pcb.LSET()
    layers.AddLayer(pcb.F_Cu)
    layers.AddLayer(pcb.B_Cu)
    zone.SetLayerSet(layers)
    zone.SetDoNotAllowTracks(True)
    zone.SetDoNotAllowVias(True)
    zone.SetDoNotAllowCopperPour(True)
    zone.SetDoNotAllowPads(True)
    poly = zone.Outline()
    poly.NewOutline()
    for xy in map(env["kxy"], config["pcb"]["antenna_keepout_xz"]):
        poly.Append(MM(xy[0]), MM(xy[1]))
    board.Add(zone)


def route_antenna_keepout(router, config, env):
    points = [env["kxy"](p) for p in config["pcb"]["antenna_keepout_xz"]]
    xs = router.x0+np.arange(router.w)*GRID
    ys = router.y0+np.arange(router.h)*GRID
    xx, yy = np.meshgrid(xs, ys)
    margin = TRACK_W/2+CLEARANCE+.18
    mask = ((xx >= min(p[0] for p in points)-margin) & (xx <= max(p[0] for p in points)+margin)
            & (yy >= min(p[1] for p in points)-margin) & (yy <= max(p[1] for p in points)+margin))
    router.owner[:, mask] = -1
    router.hole_keepout[mask] = True


def generate(geometry_only=False, reset_layout=False):
    config = configuration(reset_layout=reset_layout)
    AFFECTED.update(p["net"] for part in config["parts"] if part["kind"] in {"resistor", "capacitor"}
                    for p in part["pads"] if p["net"])
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
            RETIRED.append(track)
            board.Remove(track)
        for zone in list(board.Zones()):
            RETIRED.append(zone)
            board.Remove(zone)
        antenna_keepout(board, config, env)
        if geometry_only:
            pcb.SaveBoard(str(board_path), board)
            shutil.copy2(board_path, PCB_DIR / BOARD_NAME)
            env["write_json"](PCB_DIR / CONFIG_NAME, config)
            write_bom(config)
            print("已更新八颗小元件焊孔和同名物料清单；模块孔号及布线仍待同步，不可下单。", flush=True)
            return
        nets = {str(n.GetNetname()): n for n in board.GetNetsByNetcode().values()}
        pads = []
        for fp in board.GetFootprints():
            for p in fp.Pads():
                pads.append({"ref": fp.GetReference(), "number": p.GetNumber(), "xy": [pcb.ToMM(p.GetPosition().x), pcb.ToMM(p.GetPosition().y)],
                             "net": p.GetNetname(), "net_code": p.GetNetCode(), "size": [pcb.ToMM(p.GetSize().x), pcb.ToMM(p.GetSize().y)],
                             "drill": [pcb.ToMM(p.GetDrillSize().x), pcb.ToMM(p.GetDrillSize().y)]})
        outline = [env["kxy"](p) for p in config["pcb"]["outline_xz"]]
        router = env["Router"](board, nets, pads, outline)
        route_antenna_keepout(router, config, env)
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
        router.route()
        board = env["add_ground_zone"](board, nets, outline)
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
    generate(geometry_only="--geometry-only" in sys.argv, reset_layout="--reset-layout" in sys.argv)
