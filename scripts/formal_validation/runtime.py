"""正式设计验证副本的调用和导出；不改原工程，不隐瞒软件返回的失败。"""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs' / 'formal-validation'
SCRIPTS = Path(__file__).parent
ALLOWED = {'gun-mouse-formal-baseline', 'gun-mouse-formal-roundtrip',
           'gun-mouse-formal-route', 'gun-mouse-formal-copper'}

def invoke(session, script, label, arguments=None, timeout=60000):
    OUT.mkdir(parents=True, exist_ok=True)
    evidence = OUT / (label + '.json')
    command = [sys.executable, str(ROOT / 'scripts' / 'eda_cli.py'), '--quiet',
               '--code-file', str(script), '--evidence', str(evidence),
               '--timeout-seconds', str(timeout // 1000 + 30)]
    if arguments is not None:
        path = ROOT / '.logs' / (label + '-args.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(arguments, ensure_ascii=False), encoding='utf-8')
        command += ['--args-file', str(path)]
    command += ['--', 'invoke', '--session', session, '--ext-uuid', 'eda', '--timeout', str(timeout)]
    result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True,
                            text=True, encoding='utf-8', timeout=timeout // 1000 + 40)
    response = json.loads(evidence.read_text(encoding='utf-8'))
    if result.returncode or response.get('ok') is not True:
        raise RuntimeError(f"{response.get('error', result.stderr)}；证据：{evidence}")
    return response['value']

def export(session, project, kind, filename):
    if project not in ALLOWED or Path(filename).name != filename:
        raise ValueError('导出只限验证副本和单个文件名')
    target = OUT / filename
    if target.exists():
        raise FileExistsError(target)
    label = target.stem
    info = invoke(session, SCRIPTS / 'export_formal.js', label + '-export',
                  {'projectName': project, 'kind': kind, 'target': target.as_posix()}, 150000)
    if info['saved'] is not True:
        pieces = []
        for n in range(100):
            part = invoke(session, ROOT / 'scripts' / 'pcb_shell_v1' / 'eda' / 'fetch_chunk.js',
                          label + '-chunk' + str(n), {'n': n})
            pieces.append(part['chunk'])
            if part['done']:
                break
        else:
            raise RuntimeError('文件超过分块边界')
        data = base64.b64decode(''.join(pieces), validate=True)
        if len(data) != info['bytes']:
            raise RuntimeError('原生导出文件长度与取回长度不一致')
        with target.open('xb') as stream:
            stream.write(data)
    if not target.is_file() or target.stat().st_size != info['bytes']:
        raise RuntimeError('导出文件未实际落盘')
    result = {**info, 'localSaved': True, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    (OUT / (label + '-file.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session')
    parser.add_argument('project', choices=sorted(ALLOWED))
    parser.add_argument('kind', choices=['gerber','netlist','sch-netlist','bom','pnp','step','stepbare','pdf'])
    parser.add_argument('filename')
    args = parser.parse_args()
    print(json.dumps(export(args.session, args.project, args.kind, args.filename), ensure_ascii=False))
