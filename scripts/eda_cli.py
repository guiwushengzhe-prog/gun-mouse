"""通过原生命令行调用嘉立创专业版，并核对结构化返回值。"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, help="将返回值保存到指定文件。")
    parser.add_argument("--code-file", type=Path, help="从文件读取调用代码，避免命令行多层转义。")
    parser.add_argument("--args-file", type=Path, help="从文件读取调用参数。")
    parser.add_argument("--quiet", action="store_true", help="只显示执行状态，文件内容保存在证据文件中。")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("请提供命令，例如 -- doctor 或 -- open --headless true。")
    tools = json.loads((project / "config" / "tools.json").read_text(encoding="utf-8-sig"))
    executable = Path(tools["eda_executable"])
    if not executable.is_file():
        raise ValueError(f"未找到嘉立创专业版：{executable}")
    if args.code_file:
        command.extend(["--code", args.code_file.read_text(encoding="utf-8-sig")])
    if args.args_file:
        payload = json.loads(args.args_file.read_text(encoding="utf-8-sig"))
        command.extend(["--args", json.dumps(payload, ensure_ascii=False)])
    # 首次调用可能启动常驻编辑器。文件重定向避免其继承输出管道后让调用一直等待。
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        result = subprocess.run(
            [str(executable), *command], cwd=project,
            stdout=stdout_file, stderr=stderr_file, timeout=args.timeout_seconds,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        stdout_file.seek(0)
        stderr_file.seek(0)
        output = stdout_file.read().decode("utf-8", errors="replace").strip()
        stderr = stderr_file.read().decode("utf-8", errors="replace")
    try:
        response = json.loads(output)
    except json.JSONDecodeError:
        raise ValueError(f"命令没有返回可识别的结构化结果：{output}\n{stderr}")
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.quiet:
        print(json.dumps({"ok": response.get("ok"), "evidence": str(args.evidence)}, ensure_ascii=False))
    else:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    if result.returncode != 0 or response.get("ok") is not True:
        raise ValueError(f"嘉立创命令执行失败，退出码 {result.returncode}。")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
