"""用嘉立创程序复核已保存的正式验证副本，不修改或重建PCB。"""
import argparse
import json
import subprocess
import sys
from runtime import ROOT, OUT, SCRIPTS, ALLOWED, invoke

def cli(label, *arguments):
    path = OUT / (label + '.json')
    command = [sys.executable,str(ROOT / 'scripts' / 'eda_cli.py'),'--quiet','--evidence',str(path),'--',*arguments]
    result = subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60)
    value = json.loads(path.read_text(encoding='utf-8'))
    if result.returncode or value.get('ok') is not True:
        raise RuntimeError(f"{value.get('error',result.stderr)}；证据：{path}")
    return value['value']

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('project',choices=sorted(ALLOWED))
args = parser.parse_args()
OUT.mkdir(parents=True,exist_ok=True)
index = ROOT / 'pcb' / args.project / (args.project+'.eprj3')
if not index.is_file():
    raise FileNotFoundError(index)
label = args.project+'-saved-validation'
matches = []
for entry in cli(label+'-sessions','session','list'):
    if entry.get('status') != 'alive':
        continue
    info = invoke(entry['sessionId'],SCRIPTS/'current_project.js',label+'-probe-'+str(entry['renderId']))
    if info and info.get('name') == args.project:
        matches.append(entry['sessionId'])
if len(matches) > 1:
    raise RuntimeError('同名工程存在多个活动会话，请明确会话，不自动关闭任何窗口')
created_here = not matches
session = matches[0] if matches else cli(label+'-open','open','--path',str(index),'--headless','true')['sessionId']
try:
    opened = invoke(session,SCRIPTS/'open_formal.js',label+'-activate',{'projectName':args.project})
    config = json.loads((ROOT/'config'/'pcb-shell-v1.json').read_text(encoding='utf-8'))
    report = invoke(session,SCRIPTS/'formal_inspect.js',label,{'config':config},120000)
    passed = (report['pinComparison']['passed'] and report['widthChecks']['minimumPassed']
              and report['drc']['passed'] and not report['errors'])
    print(json.dumps({'project':args.project,'passed':passed,'counts':report['counts'],
                      'drc':{'passed':report['drc']['passed'],'count':report['drc']['count']},
                      'evidence':str(OUT/(label+'.json'))},ensure_ascii=False))
finally:
    if created_here:
        cli(label+'-close','session','close','--session',session,'--destroy')
raise SystemExit(0 if passed else 1)
