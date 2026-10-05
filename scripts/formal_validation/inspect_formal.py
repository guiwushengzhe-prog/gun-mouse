"""读取正式板验证副本；配置文件只读，结果留在本工作树。"""
import argparse
import json
from runtime import ROOT, SCRIPTS, invoke

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session')
parser.add_argument('label')
parser.add_argument('--pour', action='store_true')
args = parser.parse_args()
payload = {'config': json.loads((ROOT / 'config' / 'pcb-shell-v1.json').read_text(encoding='utf-8'))}
if args.pour:
    payload['layout'] = json.loads((ROOT / 'outputs' / 'formal-validation' / 'source-layout.json').read_text(encoding='utf-8'))
    payload['observationWaitMs'] = 3000
value = invoke(args.session, SCRIPTS / ('formal_pour.js' if args.pour else 'formal_inspect.js'), args.label, payload, 120000)
print(json.dumps({'project': value.get('project'), 'counts': value.get('counts'),
                  'pinComparison': value.get('pinComparison'),
                  'widthChecks': {key: value.get('widthChecks', {}).get(key) for key in ['minimumPassed','exactNominalPassed']},
                  'drc': {key: value.get('drc', {}).get(key) for key in ['passed','count']},
                  'saved': value.get('saved'), 'hasBothLayersFilled': value.get('hasBothLayersFilled'),
                  'originalGeometryUnchanged': value.get('originalGeometryUnchanged'), 'errors': value.get('errors')}, ensure_ascii=False))
