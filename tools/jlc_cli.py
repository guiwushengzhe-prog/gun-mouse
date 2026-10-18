"""调用本机嘉立创专业版，并保存每一步的结构化返回值。"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
EXE = Path(r"E:\各种软件\嘉立创专业版4\lceda-pro.exe")
LOG = ROOT/".logs/嘉立创最终版"


def call(command, record, timeout=180):
    LOG.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.run([str(EXE), *command], cwd=ROOT,
                                 stdout=out, stderr=err, timeout=timeout,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        out.seek(0)
        err.seek(0)
        response = json.loads(out.read().decode("utf-8-sig"))
        error = err.read().decode("utf-8", errors="replace")
    (LOG/(record+".json")).write_text(json.dumps(response, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if process.returncode or response.get("ok") is not True:
        raise RuntimeError((record, response, error))
    return response.get("value")


def invoke(session, script, record, args=None, timeout=180):
    code = Path(script).read_text(encoding="utf-8-sig")
    # 官方文件接口读取大段代码，避开Windows命令行长度上限。
    payload = LOG/(record+"-payload.json")
    LOG.mkdir(parents=True, exist_ok=True)
    payload.write_text(json.dumps({"code": code, "args": args}, ensure_ascii=False), encoding="utf-8")
    bootstrap = (
        "const f=await eda.sys_FileSystem.readFileFromFileSystem("
        +json.dumps(payload.as_posix(), ensure_ascii=False)+");"
        "if(!f)throw new Error('调用文件无法读取');const p=JSON.parse(await f.text());"
        "const A=Object.getPrototypeOf(async function(){}).constructor;"
        "return await new A('eda','__CLI__',p.code)(eda,{...__CLI__,args:p.args});"
    )
    return call(["invoke", "--session", session, "--ext-uuid", "eda", "--code", bootstrap,
                 "--timeout", str((timeout-10)*1000)], record, timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True)
    parser.add_argument("--session")
    parser.add_argument("--script", type=Path)
    parser.add_argument("--args-file", type=Path)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    if options.script:
        args = json.loads(options.args_file.read_text(encoding="utf-8")) if options.args_file else None
        value = invoke(options.session, options.script, options.record, args)
    else:
        value = call(options.command, options.record)
    print(json.dumps({"记录": options.record, "成功": True} if options.quiet else value,
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
