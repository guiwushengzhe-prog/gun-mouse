"""核对已取回的正式板证据；不调用编辑器、不修改任何设计。"""
from collections import Counter
import hashlib
import json
from runtime import ROOT, OUT
import sys
sys.path.insert(0,str(ROOT/'scripts'/'pcb_shell_v1'))
from audit_netlist import read_documents

def read(name):
    value = json.loads((OUT / name).read_text(encoding='utf-8-sig'))
    return value.get('value', value)

def geometry(items):
    result = []
    for item in items:
        value = {key: field for key, field in item.items() if key != 'id'}
        if 'x1' in value and (value['x1'],value['y1']) > (value['x2'],value['y2']):
            value['x1'],value['x2'] = value['x2'],value['x1']
            value['y1'],value['y2'] = value['y2'],value['y1']
        result.append(json.dumps(value,sort_keys=True,separators=(',',':')))
    return Counter(result)

source = read('baseline-routes.json')
reopened = read('roundtrip-reopened-routes.json')
apply = read('roundtrip-apply-retry.json')
roundtrip = {'sourceCounts': source['counts'], 'reopenedCounts': reopened['counts'],
             'lineGeometryAndAttributesEqual': geometry(source['lines']) == geometry(reopened['lines']),
             'viaGeometryAndAttributesEqual': geometry(source['vias']) == geometry(reopened['vias']),
             'saved': apply['saved'], 'mappedLibraryFields': apply.get('mappedLibraryFieldCount'),
             'reopenedDrc': read('roundtrip-reopened-inspect.json')['drc']}
roundtrip['passed'] = (roundtrip['saved'] and roundtrip['lineGeometryAndAttributesEqual']
                       and roundtrip['viaGeometryAndAttributesEqual'] and roundtrip['reopenedDrc']['passed'])
cfg = json.loads((ROOT / 'config' / 'pcb-shell-v1.json').read_text(encoding='utf-8'))
expected = {part['ref']: part['nets'] for part in cfg['parts']}
def compiled(name):
    return {part['props']['Designator']: (uid,part) for uid,part in read(name)['components'].items()}
sch = compiled('baseline-sch-netlist.enet')
pcb = compiled('baseline-netlist.enet')
def pins(parts):
    return {ref: {pin: value['net'] for pin,value in part['pinInfoMap'].items() if value.get('net')}
            for ref,(_,part) in parts.items()}
sch_pins, pcb_pins = pins(sch), pins(pcb)
identity_keys = ['Footprint','Device','Supplier Part','Manufacturer Part','Convert to PCB','Unique ID','Designator']
differences = []
for ref in sorted(sch.keys() & pcb.keys()):
    if sch[ref][0] != pcb[ref][0]:
        differences.append({'ref':ref,'field':'compiledComponentId','schematic':sch[ref][0],'pcb':pcb[ref][0]})
    for key in identity_keys:
        a,b = sch[ref][1]['props'].get(key),pcb[ref][1]['props'].get(key)
        if a != b:
            differences.append({'ref':ref,'field':key,'schematic':a,'pcb':b})
netlists = {'componentCount':len(sch), 'connectedPinCount':sum(map(len,sch_pins.values())),
            'schematicMatchesConfig':sch_pins == expected, 'pcbMatchesConfig':pcb_pins == expected,
            'schematicMatchesPcb':sch_pins == pcb_pins, 'identityDifferences':differences}
netlists['passed'] = (netlists['componentCount']==48 and netlists['connectedPinCount']==160
                      and sch_pins == expected == pcb_pins and not differences)
baseline = read('baseline-inspect.json')
copper = read('copper-reopened-inspect.json')
native = read('native-routes.json')
native_after = read('native-after-write-unsaved.json')
native_keys = {json.dumps((p['net'],p['layer'],*sorted([(p['x1'],p['y1']),(p['x2'],p['y2'])]),p['width']),separators=(',',':')):p for p in native['lines']}
actual_keys = {json.dumps((p['net'],p['layer'],*sorted([(p['startX'],p['startY']),(p['endX'],p['endY'])]),p['width']),separators=(',',':')) for p in native_after['lines']}
missing = []
for key in native_keys.keys()-actual_keys:
    p = native_keys[key]
    missing.append({'sourceId':p['id'],'net':p['net'],'lengthMm':((p['x1']-p['x2'])**2+(p['y1']-p['y2'])**2)**.5*.0254})
def errors(items, found=None):
    found = {} if found is None else found
    for item in items:
        if item.get('globalIndex') and item.get('errorType'):
            found[item['globalIndex']] = {key:item.get(key) for key in ['errorType','net','obj1','pos']}
        errors(item.get('list',[]),found)
    return list(found.values())
native_check = read('native-route-preview.json')
native_report = {'algorithm':'本机嘉立创原生自动布线；菜单兼容入口', 'capturedCounts':native['counts'],
                 'widthRulesObserved':native_check['widthChecks']['exactNominalPassed'],
                 'nativeUnconnectedErrors':errors(native_check['drc']['items']),
                 'publicWritebackReadLineCount':native_after['counts']['lineCount'],
                 'missingShortSegments':sorted(missing,key=lambda p:p['sourceId']),
                 'saveCalledByApply':False,'acceptedAsEquivalent':False,'manufacturingAccepted':False,
                 'note':'专用启动接口未修；正式板原生结果不完整，写回还丢失三条极短段。失败副本不能替代原交付。'}
native_path = ROOT/'pcb'/'gun-mouse-formal-route'/'pcb'/'PCB1.epcb2'
native_records = read_documents(native_path)[-1][1]
native_report['diskAfterOwnedSessionClosed'] = {
    'copperLines':sum(head['type']=='LINE' and body.get('layerId') in (1,2) for head,body,_ in native_records),
    'vias':sum(head['type']=='VIA' for head,_,_ in native_records),
    'sha256':hashlib.sha256(native_path.read_bytes()).hexdigest()}
source_file = ROOT/'pcb'/'gun-mouse-v1'/'pcb'/'PCB1.epcb2'
result = {'roundtrip':roundtrip,'compiledNetlists':netlists,
          'baseline':{'counts':baseline['counts'],'pinComparison':baseline['pinComparison'],'drc':baseline['drc']},
          'copperReopened':{'counts':copper['counts'],'drc':copper['drc'],'pinComparison':copper['pinComparison']},
          'nativeRouterDiagnostic':native_report,
          'sourceBoardSha256':hashlib.sha256(source_file.read_bytes()).hexdigest(),
          'scope':'正式PCB的接口与文件检查，原设计保持；实物制造验收未完成'}
target = OUT/'formal-electrical-summary.json'
target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'roundtripPassed':roundtrip['passed'],'netlistsPassed':netlists['passed'],
                  'nativeUnconnectedCount':len(native_report['nativeUnconnectedErrors']),
                  'nativeMissingShortSegments':len(missing),'report':str(target)},ensure_ascii=False))
if not roundtrip['passed'] or not netlists['passed']:
    raise SystemExit(1)
