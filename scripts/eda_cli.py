"""通过原生命令行调用嘉立创专业版，并核对结构化返回值。"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


# CreateProcessW 的上限包含末尾空字符；自动切换留出引导和路径余量。
WINDOWS_COMMAND_LINE_MAX = 32767
INLINE_THRESHOLD = 30000


def command_line_units(command):
    """按照 Python 实际使用的 Windows 引号规则计算 UTF-16 长度。"""
    return len(subprocess.list2cmdline(command).encode("utf-16-le")) // 2 + 1


def take_option(command, option):
    """提取调用选项，防止文件参数和命令行参数重复或互相覆盖。"""
    result = []
    values = []
    index = 0
    while index < len(command):
        item = command[index]
        if item == option:
            if index + 1 >= len(command):
                raise ValueError(f"选项 {option} 缺少值。")
            values.append(command[index + 1])
            index += 2
        elif item.startswith(option + "="):
            values.append(item[len(option) + 1:])
            index += 1
        else:
            result.append(item)
            index += 1
    if len(values) > 1:
        raise ValueError(f"选项 {option} 重复。")
    return result, values[0] if values else None


def prepare_command(executable, command, project, code_file=None, args_file=None, transport="auto"):
    """准备短文件引导或原调用；不连接编辑器，不修改电路设计。"""
    command = list(command)
    if command[0] != "invoke":
        if code_file or args_file or transport == "file":
            raise ValueError("文件代码、文件参数和文件传输仅适用于 invoke 调用。")
        inline = [str(executable), *command]
        metadata = {"mode": "inline", "command_line_utf16_units": command_line_units(inline)}
        if metadata["command_line_utf16_units"] > WINDOWS_COMMAND_LINE_MAX:
            raise ValueError("命令超过 Windows 命令行长度上限；请缩短命令。")
        return inline, metadata

    command, source = take_option(command, "--code")
    command, arguments_text = take_option(command, "--args")
    if code_file:
        if source is not None:
            raise ValueError("--code-file 与 --code 不能同时使用。")
        source = code_file.read_text(encoding="utf-8-sig")
    if args_file:
        if arguments_text is not None:
            raise ValueError("--args-file 与 --args 不能同时使用。")
        arguments_text = args_file.read_text(encoding="utf-8-sig")
    arguments = json.loads(arguments_text) if arguments_text is not None else None
    inline = [str(executable), *command]
    if source is not None:
        inline.extend(["--code", source])
    if arguments_text is not None:
        inline.extend(["--args", json.dumps(arguments, ensure_ascii=False)])
    inline_units = command_line_units(inline)
    use_file = transport == "file" or (transport == "auto" and inline_units > INLINE_THRESHOLD)
    metadata = {"mode": "inline", "command_line_utf16_units": inline_units}
    if not use_file:
        if inline_units > WINDOWS_COMMAND_LINE_MAX:
            raise ValueError(
                f"命令需 {inline_units} 个 UTF-16 字符，超过 Windows 上限 "
                f"{WINDOWS_COMMAND_LINE_MAX}；请使用 --transport auto 或 file。"
            )
        return inline, metadata
    if source is None:
        raise ValueError("文件传输需要调用代码；只有 --fn 的调用请分批传参或提供 --code-file。")

    # 留存载荷供超时排查。此目录在本工作树内且已被 .gitignore 忽略。
    payload_dir = project / ".logs" / "eda-cli-payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    payload_path = payload_dir / (uuid.uuid4().hex + ".json")
    payload = json.dumps({"code": source, "hasArgs": arguments_text is not None, "args": arguments},
                         ensure_ascii=False).encode("utf-8")
    payload_path.write_bytes(payload)
    # 仅将路径传给官方文件 API。AsyncFunction 与 invoke 一样执行异步函数体，
    # 显式保留 eda 与 __CLI__；args 未指定时沿用编辑器的默认值。
    bootstrap = (
        "const file=await eda.sys_FileSystem.readFileFromFileSystem("
        + json.dumps(payload_path.resolve().as_posix(), ensure_ascii=False) + ");"
        "if(!file)throw new Error('调用载荷不可读，请检查官方文件 API 的项目路径及外部交互权限');"
        "const payload=JSON.parse(await file.text());"
        "const cli=payload.hasArgs?{...__CLI__,args:payload.args}:__CLI__;"
        "const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;"
        "return await new AsyncFunction('eda','__CLI__',payload.code)(eda,cli);"
    )
    transferred = [str(executable), *command, "--code", bootstrap]
    units = command_line_units(transferred)
    if units > WINDOWS_COMMAND_LINE_MAX:
        raise ValueError("短引导之外的命令选项仍超过 Windows 命令行上限。")
    metadata = {
        "mode": "file", "command_line_utf16_units": units,
        "inline_command_line_utf16_units": inline_units,
        "payload_file": str(payload_path.resolve()),
        "payload_bytes": len(payload), "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "requires": "官方 SYS_FileSystem 项目目录访问及外部交互权限",
    }
    return transferred, metadata


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, help="将返回值保存到指定文件。")
    parser.add_argument("--code-file", type=Path, help="从文件读取调用代码，避免命令行多层转义。")
    parser.add_argument("--args-file", type=Path, help="从文件读取调用参数。")
    parser.add_argument("--transport", choices=("auto", "inline", "file"), default="auto",
                        help="调用传输方式；auto 在长命令时通过官方文件 API 读取代码和参数。")
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
    invocation, transport = prepare_command(executable, command, project,
                                           args.code_file, args.args_file, args.transport)
    # 首次调用可能启动常驻编辑器。文件重定向避免其继承输出管道后让调用一直等待。
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        result = subprocess.run(
            invocation, cwd=project,
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
    response["_local_transport"] = transport
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.quiet:
        print(json.dumps({"ok": response.get("ok"), "evidence": str(args.evidence),
                          "transport": transport["mode"]}, ensure_ascii=False))
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
