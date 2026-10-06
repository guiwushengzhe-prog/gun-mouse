"""在自建无界面会话中修改单板副本属性、同步通道关联、规则检查并导出；结束时只关闭本脚本打开的会话。"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_single_board import NAME, OUT, write_arguments  # noqa: E402

PYTHON = "E:\\GunMouseCAD\\Miniforge3\\python.exe"
EDA = ROOT / "scripts" / "pcb_shell_v1" / "eda"
ENV = {**os.environ, "PYTHONUTF8": "1"}


def run(evidence, command, code=None, args=None, timeout=660):
    cmd = [PYTHON, str(ROOT / "scripts" / "eda_cli.py"), "--quiet", "--evidence", str(OUT / evidence),
           "--timeout-seconds", str(timeout)]
    if code:
        cmd += ["--code-file", str(code)]
    if args is not None:
        payload = OUT / (evidence + "-args.json")
        payload.write_bytes(json.dumps(args, ensure_ascii=False).encode("utf-8"))
        cmd += ["--args-file", str(payload)]
    subprocess.run(cmd + ["--", *command], cwd=ROOT, check=True, env=ENV,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    value = json.loads((OUT / evidence).read_text(encoding="utf-8"))
    if value.get("ok") is not True:
        raise RuntimeError(f"{evidence}: {value.get('error')}")
    return value["value"]


def invoke(session, code, evidence, args=None):
    return run(evidence, ["invoke", "--session", session, "--ext-uuid", "eda", "--timeout", "600000"], code, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-properties", action="store_true", help="属性已写入时只同步、检查并导出")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    index = ROOT / "pcb" / NAME / (NAME + ".eprj3")
    session = run("open.json", ["open", "--path", str(index), "--headless", "true"], timeout=300)["sessionId"]
    print(json.dumps({"会话": session}, ensure_ascii=False), flush=True)
    try:
        info = invoke(session, ROOT / "scripts" / "wait_single_project.js", "probe.json", {"projectName": NAME})
        print(json.dumps({"工程": info}, ensure_ascii=False)[:400], flush=True)
        if not args.skip_properties:
            changed = invoke(session, ROOT / "scripts" / "economy_bom_properties.js", "bom-properties.json",
                             write_arguments())
            print(json.dumps({"属性修改": changed}, ensure_ascii=False), flush=True)
        synced = invoke(session, EDA / "sync_channel_ids.js", "sync-channel.json", {"projectName": NAME})
        print(json.dumps({"通道关联": synced}, ensure_ascii=False), flush=True)
        subprocess.run([PYTHON, str(ROOT / "scripts" / "export_economy_board.py"), "--session", session, "--single"],
                       cwd=ROOT, check=True, env=ENV, creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        run("close.json", ["session", "close", "--session", session, "--destroy"], timeout=120)
        print(json.dumps({"已关闭自建会话": session}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
