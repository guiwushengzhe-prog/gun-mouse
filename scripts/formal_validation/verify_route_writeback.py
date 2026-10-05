"""新建独立PCB副本，写回路线，关闭重开后逐段核对；不修正原生算法的漏接。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from prepare_projects import parse_records
from audit_route_gerber import audit
from runtime import ROOT, OUT, SCRIPTS, invoke, export


def cli(label, *arguments):
    OUT.mkdir(parents=True,exist_ok=True)
    evidence = OUT / (label + '.json')
    result = subprocess.run([sys.executable,str(ROOT/'scripts'/'eda_cli.py'),'--quiet',
        '--evidence',str(evidence),'--',*arguments],cwd=ROOT,capture_output=True,text=True,
        encoding='utf-8',timeout=60)
    response = json.loads(evidence.read_text(encoding='utf-8'))
    if result.returncode or response.get('ok') is not True:
        raise RuntimeError(f"{response.get('error',result.stderr)}；证据：{evidence}")
    return response['value']


def unwrap(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    return value.get('value', value)


def compare_routes(source, reopened, mapping):
    # 本机原生文件按0.0001密耳序列化；允许半个量化单位，网络等属性须严格相同。
    tolerance = 0.000051
    target_lines = {p['id']: p for p in reopened['lines']}
    target_vias = {p['id']: p for p in reopened['vias']}
    source_lines = {p['id']: p for p in source['lines']}
    source_vias = {p['id']: p for p in source['vias']}
    differences, deviations = [], []
    if len(target_lines) != len(source_lines) or len(target_vias) != len(source_vias):
        differences.append({'kind': 'count', 'source': source['counts'], 'actual': reopened['counts']})
    for kind, before, after in [('lines', source_lines, target_lines), ('vias', source_vias, target_vias)]:
        for pair in mapping[kind]:
            original, actual = before[pair['sourceId']], after.get(pair['id'])
            if actual is None:
                differences.append({'kind': kind, 'sourceId': original['id'], 'missing': True})
                continue
            actual = {**actual, 'id': original['id']}
            if kind == 'lines':
                forward = max(abs(original[k] - actual[k]) for k in ('x1','y1','x2','y2'))
                reverse = max(abs(original[a] - actual[b]) for a,b in
                              [('x1','x2'),('y1','y2'),('x2','x1'),('y2','y1')])
                if reverse < forward:
                    actual['x1'],actual['x2'] = actual['x2'],actual['x1']
                    actual['y1'],actual['y2'] = actual['y2'],actual['y1']
            for key, expected in original.items():
                observed = actual.get(key)
                if key in {'x1','y1','x2','y2','x','y','width','holeDiameter','diameter'}:
                    deviation = abs(expected-observed) if isinstance(observed,(int,float)) else math.inf
                    deviations.append(deviation)
                    if not math.isfinite(deviation) or deviation > tolerance:
                        differences.append({'kind':kind,'id':original['id'],'field':key,'expected':expected,'actual':observed})
                elif expected != observed:
                    differences.append({'kind':kind,'id':original['id'],'field':key,'expected':expected,'actual':observed})
    return {'passed': not differences, 'differences': differences, 'coordinateAndWidthToleranceMil': tolerance,
            'maximumNumericDeviationMil':max(deviations,default=0), 'segments':len(target_lines),'vias':len(target_vias)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    if not args.label or not all(c.isascii() and (c.isalnum() or c == '-') for c in args.label):
        raise ValueError('label只能使用英文字母、数字和连字符')
    source = unwrap(args.snapshot)
    name = 'gun-mouse-formal-route' if source['project']['friendlyName'] == 'gun-mouse-formal-route' else 'gun-mouse-formal-roundtrip'
    directory = ROOT / 'outputs' / 'route-writeback-fix' / args.label
    if directory.exists():
        raise FileExistsError(directory)
    original_dir = ROOT / 'pcb' / 'gun-mouse-v1'
    original_board = original_dir / 'pcb' / 'PCB1.epcb2'
    original_sha = hashlib.sha256(original_board.read_bytes()).hexdigest()
    shutil.copytree(original_dir, directory)
    original_index = directory / 'gun-mouse-v1.eprj3'
    index_path = directory / (name + '.eprj3')
    index = json.loads(original_index.read_text(encoding='utf-8-sig'))
    owner = uuid.uuid4().hex
    for key in ('owner_uuid','creator_uuid','modifier_uuid'):
        index[key] = owner
    index['profile']['owner']['uuid'] = owner
    index['name'] = name
    index['content'] = '独立布线写回验证；原生漏接未修，不作为制造定稿'
    original_index.rename(index_path)
    index_path.write_bytes((json.dumps(index,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    retained, doc_type = [], None
    for line, header, body in parse_records(directory / 'pcb' / 'PCB1.epcb2'):
        if header['type'] == 'DOCHEAD':
            doc_type = body.get('docType')
        if doc_type == 'PCB' and (header['type'] == 'VIA' or
                (header['type'] in ('LINE','ARC','POLY') and body.get('layerId') in (1,2))):
            continue
        retained.append(line)
    (directory / 'pcb' / 'PCB1.epcb2').write_bytes(('\n'.join(retained)+'\n').encode('utf-8'))
    (directory / 'README.md').write_text('独立写回验证副本，不能直接制造。布线合格与设计验收另行判断。\n',encoding='utf-8')
    label = args.label
    session = None
    try:
        session = cli(label+'-open','open','--path',str(index_path),'--headless','true')['sessionId']
        opened = invoke(session,SCRIPTS/'open_formal.js',label+'-activate',{'projectName':name})
        written = invoke(session,SCRIPTS/'apply_routes.js',label+'-write',{'snapshot':source,
            'target':{'projectUuid':opened['projectUuid'],'boardUuid':opened['board']}},150000)
        captured = invoke(session,SCRIPTS/'snapshot_routes.js',label+'-before-close')
        cli(label+'-close','session','close','--session',session,'--destroy')
        session = None
        session = cli(label+'-reopen','open','--path',str(index_path),'--headless','true')['sessionId']
        invoke(session,SCRIPTS/'open_formal.js',label+'-reactivate',{'projectName':name})
        reopened = invoke(session,SCRIPTS/'snapshot_routes.js',label+'-reopened')
        comparison = compare_routes(source,reopened,written['created'])
        if not comparison['passed']:
            raise RuntimeError('重开后路线核对失败：'+json.dumps(comparison,ensure_ascii=False))
        config = json.loads((ROOT/'config'/'pcb-shell-v1.json').read_text(encoding='utf-8'))
        inspected = invoke(session,SCRIPTS/'formal_inspect.js',label+'-inspect',{'config':config},120000)
        if not inspected['pinComparison']['passed'] or inspected['errors']:
            raise RuntimeError('原器件引脚网络或检查读取不一致')
        exported = export(session,name,'gerber',label+'-gerber.zip')
        manufacturing_geometry = audit(source,Path(exported['target']))
        (OUT/(label+'-gerber-audit.json')).write_text(json.dumps(manufacturing_geometry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if not manufacturing_geometry['passed']:
            raise RuntimeError('制造铜层路线核对未通过')
        original_unchanged = hashlib.sha256(original_board.read_bytes()).hexdigest() == original_sha
        if not original_unchanged:
            raise RuntimeError('原始电路板校验值改变，不能报告验证通过')
        report = {'passed':True,'sourceSnapshot':str(args.snapshot.resolve()),'target':str(index_path),
                  'sourceCounts':source['counts'],'beforeCloseCounts':captured['counts'],'reopenedCounts':reopened['counts'],
                  'geometryComparison':comparison,'originalBoardSha256':original_sha,
                  'originalBoardUnchanged':original_unchanged,
                  'drc':inspected['drc'],'pinComparison':inspected['pinComparison'],'gerber':exported,
                  'manufacturingGeometry':manufacturing_geometry,
                  'manufacturingReady':False,
                  'scope':'写回与持久化核对；不自动修补原生算法漏接，不改原交付或外壳'}
        (OUT/(label+'-report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('passed','reopenedCounts','geometryComparison','manufacturingReady','originalBoardUnchanged')},ensure_ascii=False))
    except Exception:
        # 隔离副本失败时先只读留存当前几何，避免关闭会话后证据随未保存状态消失。
        if session:
            try:
                invoke(session,SCRIPTS/'snapshot_routes.js',label+'-failure-snapshot')
            except Exception as capture_error:
                print('失败状态读取也未完成：'+str(capture_error),file=sys.stderr)
        raise
    finally:
        if session:
            cli(label+'-final-close','session','close','--session',session,'--destroy')


if __name__ == '__main__':
    main()
