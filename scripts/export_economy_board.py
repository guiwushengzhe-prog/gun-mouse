"""用嘉立创专业版从独立新工程导出生产资料并检查规则。"""
import argparse
import base64
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "economy-eda"
DELIVER = ROOT / "deliverables" / "经济型改版" / "制板文件"
PYTHON = "E:\\GunMouseCAD\\Miniforge3\\python.exe"
EDA = ROOT / "scripts" / "pcb_shell_v1" / "eda"


def call(command, evidence, code=None, args=None):
    cmd = [PYTHON, str(ROOT / "scripts" / "eda_cli.py"), "--quiet", "--evidence", str(OUT / evidence), "--timeout-seconds", "660"]
    if code:
        cmd += ["--code-file", str(code)]
    if args is not None:
        payload = OUT / (evidence + "-args.json")
        payload.write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
        cmd += ["--args-file", str(payload)]
    subprocess.run(cmd + ["--", *command], cwd=ROOT, check=True, creationflags=subprocess.CREATE_NO_WINDOW, env={**os.environ, "PYTHONUTF8": "1"})
    return json.loads((OUT / evidence).read_text(encoding="utf-8"))["value"]


def invoke(session, code, evidence, args=None):
    return call(["invoke", "--session", session, "--ext-uuid", "eda", "--timeout", "600000"], evidence, code, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--factory", action="store_true", help="导出保留工厂焊接扳机小板的版本")
    parser.add_argument("--single", action="store_true", help="导出取消扳机小板、开关自焊的单板推荐版")
    args = parser.parse_args()
    global OUT, DELIVER
    project_name = "gun-mouse-economy-factory-v3" if args.factory else "gun-mouse-economy-v2"
    if args.factory:
        OUT = ROOT / "outputs" / "economy-factory-eda"
        DELIVER = ROOT / "deliverables" / "经济型工厂代焊版" / "制板文件"
    if args.single:
        project_name = "gun-mouse-economy-single-v4"
        OUT = ROOT / "outputs" / "economy-single-eda"
        DELIVER = ROOT / "deliverables" / "经济型单板自焊版" / "制板文件"
    OUT.mkdir(parents=True, exist_ok=True)
    DELIVER.mkdir(parents=True, exist_ok=True)
    rules = invoke(args.session, EDA / "drc.js", "drc.json")
    print(json.dumps({"规则检查": rules}, ensure_ascii=False), flush=True)
    if rules["count"] != 0:
        raise RuntimeError("新主板规则检查有问题，先解决后导出")
    for kind, target in [("gerber", project_name + "-Gerber.zip"), ("netlist", "新主板网表.enet"), ("sch-netlist", "新原理图网表.enet"), ("pnp", "原生坐标.csv"), ("bom", "原生物料.csv")]:
        metadata = invoke(args.session, EDA / "export_file.js", f"export-{kind}.json", {"kind": kind, "name": project_name, "netlistType": "JLCEDA"})
        chunks = []
        for n in range(1000):
            data = invoke(args.session, EDA / "fetch_chunk.js", "chunk.json", {"n": n})
            chunks.append(data["chunk"])
            if data["done"]:
                break
        blob = base64.b64decode("".join(chunks))
        assert len(blob) == metadata["size"]
        destination = DELIVER / target if kind == "gerber" else OUT / target
        destination.write_bytes(blob)
        print(json.dumps({"导出": target, "字节": len(blob)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
