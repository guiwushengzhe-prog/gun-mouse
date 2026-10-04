"""用程序完成嘉立创示例板到 CadQuery 外壳的导出和装配验证。"""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys


root = Path(__file__).resolve().parents[1]
tools = json.loads((root / "config" / "tools.json").read_text(encoding="utf-8-sig"))
output = root / "outputs" / "toolchain-demo"
output.mkdir(parents=True, exist_ok=True)
environment = dict(os.environ, PYTHONUTF8="1")


def call_eda(command, evidence, code_file=None, args_file=None):
    args = [tools["miniforge_python"], str(root / "scripts" / "eda_cli.py"),
            "--evidence", str(output / evidence), "--quiet"]
    if code_file:
        args.extend(["--code-file", str(root / "scripts" / code_file)])
    if args_file:
        args.extend(["--args-file", str(root / "config" / args_file)])
    args.extend(["--", *command])
    subprocess.run(args, check=True, env=environment, cwd=root,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads((output / evidence).read_text(encoding="utf-8"))["value"]


def main():
    initial = call_eda(["doctor"], "doctor-before.json")
    index = root / "pcb" / "toolchain-demo" / "toolchain-demo.eprj3"
    if not index.exists():
        subprocess.run([tools["miniforge_python"], str(root / "scripts" / "create_eda_demo.py")],
                       check=True, env=environment, cwd=root)
    opened = call_eda(["open", "--path", str(index), "--headless", "true"], "session-open.json")
    session = opened["sessionId"]
    try:
        setup = (
            "let p,b; for(let i=0;i<20;i++){"
            "p=await eda.dmt_Project.getCurrentProjectInfo();"
            "b=p?.data?.find(x=>x.itemType==='Board' && x.name==='Board1');"
            "if(p && p.friendlyName==='toolchain-demo' && b?.pcb) break;"
            "await new Promise(r=>setTimeout(r,500));}"
            "if(!p || p.friendlyName!=='toolchain-demo') throw new Error('验证工程尚未加载完成');"
            "if(!b || !b.pcb) throw new Error('缺少验证板');"
            "await eda.dmt_EditorControl.openDocument(b.pcb.uuid);"
            "await new Promise(r=>setTimeout(r,2500));"
            "return {outlines:(await eda.pcb_PrimitivePolyline.getAllPrimitiveId()).length,"
            "holes:(await eda.pcb_PrimitivePad.getAllPrimitiveId()).length};"
        )
        state = call_eda(["invoke", "--session", session, "--ext-uuid", "eda", "--code", setup], "board-state.json")
        if state == {"outlines": 0, "holes": 0}:
            call_eda(["invoke", "--session", session, "--ext-uuid", "eda"], "board-created.json",
                     code_file="create_demo_board.js", args_file="toolchain-demo.json")
        elif state != {"outlines": 1, "holes": 4}:
            raise ValueError("示例板图元数量不符合预期，保留原工程并停止验证。")
        file = call_eda(["invoke", "--session", session, "--ext-uuid", "eda", "--timeout", "120000"],
                        "board-export.json", code_file="export_demo_board.js")
        data = base64.b64decode(file["base64"], validate=True)
        if len(data) != file["size"] or not data.startswith(b"ISO-10303-21;"):
            raise ValueError("导出的三维文件长度或格式不正确。")
        board_path = output / "eda-board-export.step"
        board_path.write_bytes(data)
        subprocess.run([tools["cadquery_python"], str(root / "scripts" / "build_shell.py"),
                        "--board-step", str(board_path), "--output", str(output)],
                       check=True, env=environment, cwd=root)
        print("电路板导出、外壳生成与装配验证完成。")
    finally:
        call_eda(["session", "close", "--session", session, "--destroy"], "session-close.json")
        if not initial["connected"]:
            remaining = call_eda(["session", "list"], "sessions-after.json")
            if not any(item.get("status") == "alive" for item in remaining):
                call_eda(["stop"], "backend-stop.json")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"工具联动验证失败：{error}", file=sys.stderr)
        sys.exit(1)
