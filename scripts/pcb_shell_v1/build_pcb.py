"""通过嘉立创专业版命令行接口生成枪型飞鼠主板（含可掰下的扳机小板）并导出制造文件。

步骤：重建工程 → 放置器件/板框/孔/丝印 → 在工程文件中写入焊盘网络 → 生成同网表的原理图 → 程序布线（含地网络，不铺铜）
→ 设计规则检查 → 导出 Gerber、BOM、坐标文件、网表和三维模型。

运行（布线器需要 numpy，使用 CadQuery 环境的 Python）：
    $env:PYTHONUTF8 = '1'
    & 'E:\\GunMouseCAD\\CadQuery\\python.exe' scripts\\pcb_shell_v1\\build_pcb.py
先运行 layout.py 生成 outputs/pcb-shell-v1/layout.json。
"""

import argparse
import base64
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import MIL, OUTPUT, ROOT, load_config, write_json  # noqa: E402
import route_grid  # noqa: E402

PROJECT_NAME = "gun-mouse-v1"
PROJECT_DIR = ROOT / "pcb" / PROJECT_NAME
DELIVER = ROOT / "deliverables" / "pcb-shell-v1"
EVIDENCE = OUTPUT / "eda-evidence"
TOOLS = json.loads((ROOT / "config" / "tools.json").read_text(encoding="utf-8-sig"))


def eda(command, evidence, code=None, args=None, timeout_s=300):
    """调用 eda_cli.py，返回结构化结果中的 value。"""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    cmd = [TOOLS["miniforge_python"], str(ROOT / "scripts" / "eda_cli.py"),
           "--evidence", str(EVIDENCE / evidence), "--quiet", "--timeout-seconds", str(timeout_s)]
    if code:
        cmd += ["--code-file", str(HERE / "eda" / code)]
    if args is not None:
        args_path = EVIDENCE / (evidence.replace(".json", "") + "-args.json")
        args_path.write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
        cmd += ["--args-file", str(args_path)]
    cmd += ["--", *command]
    subprocess.run(cmd, check=True, cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW,
                   env={**__import__("os").environ, "PYTHONUTF8": "1"})
    return json.loads((EVIDENCE / evidence).read_text(encoding="utf-8"))["value"]


def invoke(session, code, evidence, args=None, timeout_ms=240000):
    return eda(["invoke", "--session", session, "--ext-uuid", "eda", "--timeout", str(timeout_ms)],
               evidence, code=code, args=args, timeout_s=timeout_ms // 1000 + 60)


def mils(points):
    return [[round(u / MIL, 3), round(v / MIL, 3)] for u, v in points]


def place_args(layout):
    parts = [{"ref": p["ref"], "lcsc": p["lcsc"], "x": round(p["u"] / MIL, 3), "y": round(p["v"] / MIL, 3),
              "rot": p["rot"]} for p in layout["parts"]]
    holes = [{"id": h["id"], "x": round(h["uv"][0] / MIL, 3), "y": round(h["uv"][1] / MIL, 3),
              "d": round(h["d"] / MIL, 3)} for h in layout["mount_holes"]]
    for i, (u, v) in enumerate(layout["mousebites_uv"], 1):
        holes.append({"id": f"MB{i}", "x": round(u / MIL, 3), "y": round(v / MIL, 3),
                      "d": round(layout["mousebite_d"] / MIL, 3)})
    texts = [{"layer": t["layer"], "x": round(t["u"] / MIL, 3), "y": round(t["v"] / MIL, 3), "text": t["text"],
              "size": round(t["size"] / MIL, 1), "stroke": round(t["size"] * 0.15 / MIL, 1), "rot": t["rot"]}
             for t in layout["texts"]]
    return {"parts": parts, "outline": mils(layout["outline_uv"]),
            "cutouts": [mils(c["uv"]) for c in layout["cutouts"]], "holes": holes, "texts": texts}


def schematic_args(layout):
    """原理图排布：两排排母单独放左侧，其余器件按 8 列网格排开（坐标为原理图单位）。"""
    parts = []
    k = 0
    for p in layout["parts"]:
        if p["ref"] in ("J1", "J2"):
            x, y = (-2600 if p["ref"] == "J1" else -1600), 0
        else:
            x, y = (k % 8) * 1300, -(k // 8) * 1100
            k += 1
        parts.append({"ref": p["ref"], "lcsc": p["lcsc"], "x": x, "y": y, "nets": p["nets"]})
    return {"parts": parts}


def pcb_file():
    files = list((PROJECT_DIR / "pcb").glob("*.epcb2"))
    if len(files) != 1:
        raise RuntimeError(f"期望 1 个电路板文件，实际 {len(files)}")
    return files[0]


def write_pad_nets(layout, placed):
    """在 .epcb2 中按（器件图元 ID, 焊盘号）写入网络名。编辑器会自动重新载入磁盘修改。"""
    want = {}
    for p in layout["parts"]:
        comp = placed[p["ref"]]
        for pad, net in p["nets"].items():
            want[(comp, pad)] = net
    path = pcb_file()
    lines = path.read_text(encoding="utf-8").split("\n")
    hit = 0
    max_ticket = 0
    for line in lines:
        if "||" in line:
            try:
                max_ticket = max(max_ticket, json.loads(line.split("||", 1)[0]).get("ticket", 0))
            except json.JSONDecodeError:
                pass
    for i, line in enumerate(lines):
        if not line.startswith('{"type":"PAD_NET"'):
            continue
        head, body = line.split("||", 1)
        h = json.loads(head)
        ident = json.loads(h["id"])
        key = (ident[1], ident[2])
        if key not in want:
            continue
        b = json.loads(body.rstrip("|"))
        if b.get("padNet") == want[key]:
            hit += 1
            continue
        b["padNet"] = want[key]
        max_ticket += 1
        h["ticket"] = max_ticket
        lines[i] = (json.dumps(h, ensure_ascii=False, separators=(",", ":")) + "||"
                    + json.dumps(b, ensure_ascii=False, separators=(",", ":")) + "|")
        hit += 1
    path.write_text("\n".join(lines), encoding="utf-8", newline="")
    return hit, len(want)


def fetch(session, kind, name, target):
    info = invoke(session, "export_file.js", f"export-{kind}.json", {"kind": kind, "name": name}, 600000)
    chunks = []
    n = 0
    while True:
        part = invoke(session, "fetch_chunk.js", "chunk.json", {"n": n}, 120000)
        chunks.append(part["chunk"])
        n += 1
        if part["done"]:
            break
    data = base64.b64decode("".join(chunks))
    if len(data) != info["size"]:
        raise RuntimeError(f"{kind} 文件长度不符：{len(data)} != {info['size']}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"file": str(target.relative_to(ROOT)), "size": len(data), "name": info["name"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-session", action="store_true", help="完成后保留后台会话，便于调试")
    args = parser.parse_args()
    cfg = load_config()
    layout = json.loads((OUTPUT / "layout.json").read_text(encoding="utf-8"))

    initial = eda(["doctor"], "doctor.json")
    sessions = eda(["session", "list"], "sessions-before.json")
    index = PROJECT_DIR / f"{PROJECT_NAME}.eprj3"
    # 关闭上次 --keep-session 留下的本工程会话（会话列表不含路径，按记录的编号关闭）
    kept = OUTPUT / "kept-session.txt"
    if kept.exists():
        old = kept.read_text(encoding="utf-8").strip()
        if any(s.get("sessionId") == old and s.get("status") == "alive" for s in sessions or []):
            eda(["session", "close", "--session", old, "--destroy"], "session-close-old.json")
        kept.unlink()
    if PROJECT_DIR.exists():
        shutil.rmtree(PROJECT_DIR)
    subprocess.run([TOOLS["miniforge_python"], str(ROOT / "scripts" / "eda" / "create_project.py"),
                    str(PROJECT_DIR), PROJECT_NAME, "枪型飞鼠主板 V1（程序生成）"], check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    opened = eda(["open", "--path", str(index), "--headless", "true"], "session-open.json")
    session = opened["sessionId"]
    report = {"config_version": cfg["version"], "session": session}
    try:
        placed = invoke(session, "place.js", "place.json", place_args(layout), 600000)
        report["placed_components"] = placed["components"]
        time.sleep(3)
        hit, total = write_pad_nets(layout, placed["placed"])
        report["pad_nets_written"] = [hit, total]
        if hit != total:
            raise RuntimeError(f"焊盘网络只匹配 {hit}/{total}")
        expected = {p["ref"]: p["nets"] for p in layout["parts"]}
        for attempt in range(20):
            time.sleep(3)
            loaded = invoke(session, "pad_nets.js", "pad-nets.json", None, 60000)
            missing = [(r, pad) for r, nets in expected.items() for pad, net in nets.items()
                       if loaded.get(r, {}).get(pad) != net]
            if not missing:
                break
        else:
            raise RuntimeError(f"编辑器未载入焊盘网络：{missing[:10]}")
        report["pad_nets_loaded_check_attempts"] = attempt + 1
        report["schematic"] = invoke(session, "schematic.js", "schematic.json", schematic_args(layout), 900000)
        # 补齐唯一编号、型号/阻容值和关联属性；保持器件位置及网络不变。
        report["schematic_link"] = invoke(session, "link_ids.js", "link-ids.json", None, 300000)
        report["schematic_properties"] = invoke(session, "sync_schematic_props.js", "sync-sch-props.json", None, 60000)
        report["channel_association"] = invoke(session, "sync_channel_ids.js", "sync-channel-ids.json", None, 60000)
        # 嘉立创自动布线在后台会话中不会启动，改用本地网格布线器（route_grid.py），再交给嘉立创做规则检查
        pads = invoke(session, "pads.js", "pads.json", None, 120000)
        write_json(OUTPUT / "pads.json", pads)
        lines, vias, rrep, router = route_grid.route(layout, pads)
        route_grid.draw(router, lines, vias, OUTPUT / "routing-check.png")
        report["routing"] = rrep
        if rrep["failed"]:
            raise RuntimeError(f"布线未完成：{rrep['failed']}")
        line_args = [[n, 1 if L == 0 else 2, round(u1 / MIL, 3), round(v1 / MIL, 3), round(u2 / MIL, 3),
                      round(v2 / MIL, 3), round(w / MIL, 3)] for n, L, w, u1, v1, u2, v2 in lines]
        via_args = [[n, round(u / MIL, 3), round(v / MIL, 3)] for n, u, v in vias]
        common_args = {"via_hole": round(route_grid.VIA_HOLE / MIL, 3), "via_d": round(route_grid.VIA_D / MIL, 3)}
        # 命令行长度有限（约 32KB），分批写入；必须先建过孔再建导线
        written = [invoke(session, "routes.js", "routes-0.json",
                          {**common_args, "clear": True, "vias": via_args, "lines": []}, 600000)]
        for k in range(0, len(line_args), 120):
            written.append(invoke(session, "routes.js", f"routes-{k // 120 + 1}.json",
                                  {**common_args, "vias": [], "lines": line_args[k:k + 120]}, 600000))
        # 后台会话中覆铜填充无法计算（rebuildCopperRegion 内部报错），不铺铜；地网络已由导线完整连通
        report["routes_written"] = {"lines": sum(w["lines"] for w in written), "vias": sum(w["vias"] for w in written),
                                    "failed": sum(w["failedCount"] for w in written)}
        if report["routes_written"]["failed"]:
            raise RuntimeError(f"有 {report['routes_written']['failed']} 个导线或过孔未能创建")
        drc = invoke(session, "drc.js", "drc.json", None, 600000)
        report["drc_count"] = drc["count"]
        write_json(OUTPUT / "drc-report.json", drc)
        out = DELIVER / "制板文件"
        report["exports"] = [
            fetch(session, "gerber", "gun-mouse-v1-gerber", out / "gun-mouse-v1-Gerber.zip"),
            fetch(session, "bom", "gun-mouse-v1-bom", out / "gun-mouse-v1-BOM.csv"),
            fetch(session, "pnp", "gun-mouse-v1-pnp", out / "gun-mouse-v1-坐标文件.csv"),
            fetch(session, "netlist", "gun-mouse-v1-netlist", out / "gun-mouse-v1-网表.enet"),
            fetch(session, "step", "gun-mouse-v1-board", OUTPUT / "pcb-with-parts.step"),
        ]
    finally:
        if args.keep_session:
            (OUTPUT / "kept-session.txt").write_text(session, encoding="utf-8")
        else:
            eda(["session", "close", "--session", session, "--destroy"], "session-close.json")
            if not initial.get("connected"):
                remaining = eda(["session", "list"], "sessions-after.json")
                if not any(s.get("status") == "alive" for s in remaining or []):
                    eda(["stop"], "backend-stop.json")
        write_json(OUTPUT / "pcb-build-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
