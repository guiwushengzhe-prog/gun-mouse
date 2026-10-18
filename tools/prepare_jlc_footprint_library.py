"""仅复用原封装库，生成供嘉立创载入的封装样本；不复制旧PCB文档。"""
import json
from pathlib import Path
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/嘉立创最终复绘'
OUT.mkdir(parents=True,exist_ok=True)

def records(source):
    for line in source.splitlines():
        if '||' not in line: continue
        h,b=line.split('||',1)
        yield json.loads(h),json.loads(b.removesuffix('|')) if b.removesuffix('|') else None

def text(rows):
    return '|\n'.join(json.dumps(h,ensure_ascii=False,separators=(',',':'))+'||'+
                     (json.dumps(b,ensure_ascii=False,separators=(',',':')) if b is not None else '') for h,b in rows)

library=[]
include=False
for h,b in records((ROOT/'pcb/嘉立创最终版/pcb/枪型飞鼠最终主板.epcb2').read_text(encoding='utf-8')):
    if h['type']=='DOCHEAD': include=b['docType'] in ('DEVICE','FOOTPRINT')
    if include: library.append((h,b))
assert sum(h['type']=='DOCHEAD' for h,b in library)==42
reference=json.loads((ROOT/'.logs/嘉立创最终版/最终原生几何与连接.json').read_text(encoding='utf-8'))['value']
parts=[c for c in reference['components'] if not c['Designator'].startswith('H')]
assert len(parts)==18
blank=list(records((ROOT/'outputs/嘉立创原生重绘/原生空白主板基准.epcb2').read_text(encoding='utf-8')))
blank[0][1]['uuid']=uuid.uuid4().hex[:16]
for h,b in blank:
    if h['type']=='META': b['title']='仅供封装复用的样本';b['board']=''
ticket=1000
for i,c in enumerate(parts):
    ident='e'+str(ticket);ticket+=1
    x,y=(i%5)*1500,(i//5)*1500
    device=c['Component']['uuid']
    fpname=c['OtherProperty'].get('FootprintName','')
    blank.append(({'type':'COMPONENT','ticket':ticket,'id':ident},{'partitionId':'','groupId':0,
        'layerId':1,'x':x,'y':y,'angle':0,'attrs':{'Unique ID':uuid.uuid4().hex[:16],
        'FootprintName':fpname,'DeviceName':json.dumps(device,separators=(',',':'))},
        'locked':False,'zIndex':-1,'pinSwap':False,'pinSwapInfo':{},'footprintPrimitives':False}))
    for key,val in [('Device',device['uuid']),('Designator','LIB_'+c['Designator']),('FootprintName',fpname)]:
        ticket+=1
        blank.append(({'type':'ATTR','ticket':ticket,'id':'e'+str(ticket)},
            {'partitionId':'','groupID':0,'parentId':ident,'layerId':3,'x':x,'y':y,
             'key':key,'value':val,'keyVisible':False,'valueVisible':False,'fontFamily':'default',
             'fontSize':50,'strokeWidth':5.9,'bold':0,'italic':0,'origin':'CENTER_MIDDLE',
             'angle':0,'reverse':False,'expansion':0,'mirror':False,'locked':False,'zIndex':-1}))
    for p in c['Pads']:
        ticket+=1
        blank.append(({'type':'PAD_NET','ticket':ticket,
            'id':json.dumps(['PAD_NET',ident,p['padNumber'],p['primitiveId']],separators=(',',':'))},
            {'partitionId':'','padNet':'','padLen':None,'propagationDelay':None,'attrsMap':{}}))
path=OUT/'仅复用封装库的原生样本.epro2'
with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
    z.writestr('project2.json',json.dumps({'title':'最终复绘封装库样本','cbb_project':False,
        'editorVersion':'4.1.66','introduction':'仅复用封装库，不包含原PCB文档。','description':'','custom_tags':''},ensure_ascii=False))
    z.writestr('封装样本.epru',text(library+blank))
print(path)
