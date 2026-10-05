"""通过现有命令行封装分块取回独立试验板铜层文件，并只读统计区域命令。"""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def invoke(session, code, label, arguments=None):
    evidence = ROOT / ".logs" / (label + ".json")
    command = [sys.executable, str(ROOT / "scripts" / "eda_cli.py"),
               "--quiet", "--code-file", str(code), "--evidence", str(evidence),
               "--timeout-seconds", "45"]
    if arguments is not None:
        args_file = ROOT / ".logs" / (label + "-args.json")
        args_file.write_text(json.dumps(arguments), encoding="utf-8")
        command += ["--args-file", str(args_file)]
    command += ["--", "invoke", "--session", session, "--ext-uuid", "eda", "--timeout", "35000"]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=55)
    return json.loads(evidence.read_text(encoding="utf-8"))["value"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    if not target.is_relative_to(ROOT) or target.exists():
        parser.error("输出必须是试验工作树内的新文件，不覆盖已有成果")
    label = target.stem
    info = invoke(args.session, Path(__file__).with_name("export_probe.js"), label + "-export")
    chunks = []
    for n in range(100):
        part = invoke(args.session, ROOT / "scripts" / "pcb_shell_v1" / "eda" / "fetch_chunk.js",
                      label + "-chunk" + str(n), {"n": n})
        chunks.append(part["chunk"])
        if part["done"]:
            break
    else:
        raise RuntimeError("导出超过实验文件大小边界")
    data = base64.b64decode("".join(chunks), validate=True)
    if len(data) != info["size"]:
        raise RuntimeError("取回文件长度不符")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(data)
    copper = []
    with zipfile.ZipFile(target) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError("压缩包损坏：" + bad)
        for name in archive.namelist():
            if name.lower().endswith((".gtl", ".gbl")):
                text = archive.read(name).decode("ascii", errors="replace")
                copper.append({"name": name, "bytes": len(text), "regionStartCount": text.count("G36*"),
                               "regionEndCount": text.count("G37*"),
                               "linearInterpolationCount": text.count("G01"),
                               "drawCommandCount": text.count("D01*"), "flashCount": text.count("D03*")})
    result = {"file": str(target), "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "copper": copper, "note": "独立试验板；区域命令数量不能代替电气与制造验收"}
    target.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
