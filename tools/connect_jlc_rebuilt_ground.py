"""在已验证的新信号走线之间，为铺铜孤立的地焊盘建立连接。"""
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import plan_jlc_native_routes as r

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/嘉立创最终复绘'
LOG=ROOT/'.logs/嘉立创最终版'
r.GRID=.05
r.NX=round((r.X1-r.X0)/r.GRID)+1
r.NY=round((r.Y1-r.Y0)/r.GRID)+1
r.RASTER_MARGIN_MM=r.GRID*math.sqrt(2)/2+1e-6
r.TRACK_OBSTACLE_RADIUS_MM=.30+.25+r.RASTER_MARGIN_MM
r.PAD_OBSTACLE_ADD_MM=.15+.25+r.RASTER_MARGIN_MM
r.BOARD_EDGE_MARGIN_MM=.15+.5+r.RASTER_MARGIN_MM
r.ANTENNA_ROUTE_MARGIN_MM=.15+r.RASTER_MARGIN_MM
r.MAX_ASTAR_EXPANSIONS=700000
source=json.loads((OUT/'原生复绘布线基准.json').read_text(encoding='utf-8'))
state=json.loads((LOG/'最终复绘原生新走线写入.json').read_text(encoding='utf-8'))['value']
drc=json.loads((LOG/'最终复绘原生铺铜.json').read_text(encoding='utf-8'))['value']['drc']
base=r.board_and_keepout_masks([tuple(p) for p in source['outline']])
actual=json.loads((LOG/'最终复绘制造规则与净空.json').read_text(encoding='utf-8'))['value']['pads']
pads=[]
for p in actual:
    pads.append({'id':p['PrimitiveId'],'reference':p['PadNumber'],'number':'',
                 'x':p['X'],'y':p['Y'],'net':p['Net'],'pad':p['Pad']})
ground={p['id']:p for p in pads if p['net']=='GND'}
floating=set()
for group in drc:
    if group['name']!='Connection Error': raise RuntimeError('必须先解决间距等其他错误')
    for net in group['list']:
        if net['name']!='GND': raise RuntimeError('信号网络仍未连接')
        for error in net['list']: floating.add(error['explanation']['errData']['obj1'])
assert floating<=set(ground)
layer_use={1:{},2:{}}
via_use=defaultdict(list)

def mark_segment(mask,a,b,radius):
    xlo=max(0,math.floor((min(a[0],b[0])-radius-r.X0)/r.GRID))
    xhi=min(r.NX,math.ceil((max(a[0],b[0])+radius-r.X0)/r.GRID)+1)
    ylo=max(0,math.floor((min(a[1],b[1])-radius-r.Y0)/r.GRID))
    yhi=min(r.NY,math.ceil((max(a[1],b[1])+radius-r.Y0)/r.GRID)+1)
    xx,yy=np.meshgrid(r.X0+np.arange(xlo,xhi)*r.GRID,r.Y0+np.arange(ylo,yhi)*r.GRID)
    mask[ylo:yhi,xlo:xhi]|=r.distance_to_segment_grid(xx,yy,a,b)<=radius

for line in state['lines']:
    layer=line['Layer'];net=line['Net']
    mask=layer_use[layer].setdefault(net,np.zeros((r.NY,r.NX),dtype=bool))
    mark_segment(mask,(line['StartX']*.0254,-line['StartY']*.0254),
                 (line['EndX']*.0254,-line['EndY']*.0254),r.TRACK_OBSTACLE_RADIUS_MM)
for v in state['vias']: via_use[v['Net']].append((v['X']*.0254,-v['Y']*.0254))
segments=[];vias=[];summary=[]
connected=set(ground)-floating
while floating:
    other={layer:np.logical_or.reduce(list(layer_use[layer].values())) for layer in (1,2)}
    blocked={layer:r.layer_blocked('GND',layer,base,pads,other) for layer in (1,2)}
    for net,points in via_use.items():
        if net=='GND':continue
        for p in points:
            for layer in (1,2):r.add_circle_obstacle(blocked[layer],p,.35+.15+.25+r.RASTER_MARGIN_MM)
    via_blocked=r.via_blocked_mask('GND',base,pads,layer_use,via_use)
    print('待连地焊盘',[(ground[k]['reference'],[bool(blocked[l][r.cell(r.pad_center_mm(ground[k]))[1],r.cell(r.pad_center_mm(ground[k]))[0]]) for l in (1,2)]) for k in floating],flush=True)
    pairs=sorted((math.dist(r.pad_center_mm(ground[a]),r.pad_center_mm(ground[b])),a,b) for a in floating for b in connected)
    chosen=None
    for _,start_id,end_id in pairs:
        start,end=r.pad_center_mm(ground[start_id]),r.pad_center_mm(ground[end_id])
        path,cost=r.astar_two_layers(blocked,via_blocked,start,end)
        if path: chosen=start_id,end_id,start,end,path,cost;break
    if chosen is None:
        if not summary:raise RuntimeError('现有信号走线下无法完成地线补连')
        break
    start_id,end_id,start,end,path,cost=chosen
    layer=path[0][0];points=[start,r.cell_point(*path[0][1:])]
    cells=[]
    def emit(active,pts):
        pts=r.simplify(pts)
        for a,b in zip(pts,pts[1:]):
            if math.dist(a,b)<1e-8:continue
            segments.append({'net':'GND','layer':active,'startX':a[0]/.0254,'startY':-a[1]/.0254,
                'endX':b[0]/.0254,'endY':-b[1]/.0254,'lineWidth':.30/.0254})
    for active,x,y in path[1:]:
        p=r.cell_point(x,y)
        if active!=layer:
            emit(layer,points)
            if (x,y) not in (r.cell(start),r.cell(end)):
                vias.append({'net':'GND','x':p[0]/.0254,'y':-p[1]/.0254,'hole':.3/.0254,'diameter':.7/.0254})
                via_use['GND'].append(p)
            layer=active;points=[p]
        else:points.append(p)
    points.append(end);emit(layer,points)
    connected.add(start_id);floating.remove(start_id)
    summary.append({'from':ground[start_id]['reference'],'to':ground[end_id]['reference'],'lengthMm':cost})
    print('已规划',summary[-1],flush=True)
result={'segments':segments,'vias':vias,'connections':summary,'trackWidthMm':.3,'viaCount':len(vias),
        'remaining':[ground[x]['reference'] for x in floating]}
(OUT/'原生地线补连.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'connections':summary,'segments':len(segments),'vias':len(vias)},ensure_ascii=False,indent=2))
