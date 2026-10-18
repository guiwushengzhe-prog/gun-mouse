"""局部重排围住摇杆地焊盘的按压信号走线，给地线留出通道。"""
import json
import math
from collections import defaultdict
from pathlib import Path
import numpy as np
import plan_jlc_native_routes as r

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/嘉立创最终复绘';LOG=ROOT/'.logs/嘉立创最终版'
r.GRID=.05;r.NX=round(52/r.GRID)+1;r.NY=round(82/r.GRID)+1
r.RASTER_MARGIN_MM=r.GRID*math.sqrt(2)/2+1e-6
r.TRACK_OBSTACLE_RADIUS_MM=.55+r.RASTER_MARGIN_MM
r.PAD_OBSTACLE_ADD_MM=.40+r.RASTER_MARGIN_MM
r.BOARD_EDGE_MARGIN_MM=.65+r.RASTER_MARGIN_MM
r.ANTENNA_ROUTE_MARGIN_MM=.15+r.RASTER_MARGIN_MM;r.MAX_ASTAR_EXPANSIONS=800000
state=json.loads((LOG/'最终复绘地线连接写入.json').read_text(encoding='utf-8'))['value']
geometry=json.loads((OUT/'原生复绘布线基准.json').read_text(encoding='utf-8'))
allpads=[{**p,'reference':c['reference']} for c in geometry['components'] for p in c['pads']]+geometry['mechanicalPads']
base=r.board_and_keepout_masks([tuple(p) for p in geometry['outline']])
def segment(net,layer,a,b):return {'net':net,'layer':layer,'startX':a[0]/.0254,'startY':-a[1]/.0254,'endX':b[0]/.0254,'endY':-b[1]/.0254,'lineWidth':.3/.0254}
def mark(mask,a,b):
    rad=r.TRACK_OBSTACLE_RADIUS_MM
    x0=max(0,math.floor((min(a[0],b[0])-rad-r.X0)/r.GRID));x1=min(r.NX,math.ceil((max(a[0],b[0])+rad-r.X0)/r.GRID)+1)
    y0=max(0,math.floor((min(a[1],b[1])-rad-r.Y0)/r.GRID));y1=min(r.NY,math.ceil((max(a[1],b[1])+rad-r.Y0)/r.GRID)+1)
    xx,yy=np.meshgrid(r.X0+np.arange(x0,x1)*r.GRID,r.Y0+np.arange(y0,y1)*r.GRID)
    mask[y0:y1,x0:x1]|=r.distance_to_segment_grid(xx,yy,a,b)<=rad

def solve(rip):
    lines=[{'net':x['Net'],'layer':x['Layer'],'startX':x['StartX'],'startY':x['StartY'],'endX':x['EndX'],'endY':x['EndY'],'lineWidth':x['LineWidth']} for x in state['lines'] if x['Net'] not in rip]
    vias=[{'net':x['Net'],'x':x['X'],'y':x['Y'],'hole':x['HoleDiameter'],'diameter':x['Diameter']} for x in state['vias'] if x['Net'] not in rip]
    layer_use={1:{},2:{}};via_use=defaultdict(list)
    for s in lines:
        mask=layer_use[s['layer']].setdefault(s['net'],np.zeros((r.NY,r.NX),bool))
        mark(mask,(s['startX']*.0254,-s['startY']*.0254),(s['endX']*.0254,-s['endY']*.0254))
    for v in vias:via_use[v['net']].append((v['x']*.0254,-v['y']*.0254))
    summary=[]
    def connect(net,start,end):
        other={l:np.logical_or.reduce([m for n,m in layer_use[l].items() if n!=net]) for l in (1,2)}
        blocked={l:r.layer_blocked(net,l,base,allpads,other) for l in (1,2)}
        for n,pts in via_use.items():
            if n!=net:
                for p in pts:
                    for l in (1,2):r.add_circle_obstacle(blocked[l],p,.75+r.RASTER_MARGIN_MM)
        vb=r.via_blocked_mask(net,base,allpads,layer_use,via_use)
        path,cost=r.astar_two_layers(blocked,vb,start,end)
        if path is None:return False
        layer=path[0][0];pts=[start,r.cell_point(*path[0][1:])]
        def emit(l,points):
            points=r.simplify(points)
            for a,b in zip(points,points[1:]):
                if math.dist(a,b)<1e-8:continue
                lines.append(segment(net,l,a,b));mask=layer_use[l].setdefault(net,np.zeros((r.NY,r.NX),bool));mark(mask,a,b)
        for l,x,y in path[1:]:
            p=r.cell_point(x,y)
            if l!=layer:
                emit(layer,pts)
                if (x,y) not in (r.cell(start),r.cell(end)) and not any(math.dist(p,q)<.001 for q in via_use[net]):
                    vias.append({'net':net,'x':p[0]/.0254,'y':-p[1]/.0254,'hole':.3/.0254,'diameter':.7/.0254});via_use[net].append(p)
                layer=l;pts=[p]
            else:pts.append(p)
        pts.append(end);emit(layer,pts);summary.append({'net':net,'from':start,'to':end,'length':cost});return True
    ground=[p for p in allpads if p.get('net')=='GND']
    start=next(p for p in ground if p['reference']=='SW1' and p['number']=='1')
    targets=sorted([p for p in ground if p is not start],key=lambda p:math.dist(r.pad_center_mm(p),r.pad_center_mm(start)))
    if not any(connect('GND',r.pad_center_mm(start),r.pad_center_mm(p)) for p in targets):return None
    print('摇杆地线已规划；重新布置',rip,flush=True)
    for net in rip:
        group=[p for p in allpads if p.get('net')==net]
        root=min(range(len(group)),key=lambda i:sum(math.dist(r.pad_center_mm(group[i]),r.pad_center_mm(p)) for p in group))
        connected={root};remaining=set(range(len(group)))-connected
        while remaining:
            pairs=sorted((math.dist(r.pad_center_mm(group[i]),r.pad_center_mm(group[j])),i,j) for i in connected for j in remaining)
            for _,i,j in pairs:
                if connect(net,r.pad_center_mm(group[i]),r.pad_center_mm(group[j])):
                    connected.add(j);remaining.remove(j);break
            else:return None
    return {'segments':lines,'vias':vias,'summary':summary,'ripupNets':rip,'viaCount':len(vias),'trackWidthMm':.3}

for rip in [['JOY_SW'],['JOY_Y'],['JOY_SW','JOY_Y'],['JOY_Y','JOY_SW']]:
    print('局部重排',rip,flush=True)
    result=solve(rip)
    if result:
        (OUT/'原生复绘地线完成路径.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'走线':len(result['segments']),'过孔':len(result['vias']),'局部重排网络':rip},ensure_ascii=False));break
else:raise RuntimeError('局部重排未找到可行路径')
