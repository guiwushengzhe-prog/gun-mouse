"""读取嘉立创新板实际焊盘计算路径，再由嘉立创接口绘制；不读取旧走线。"""
import json
import sys
from pathlib import Path

import plan_jlc_native_routes as planner

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/嘉立创最终复绘'
data=json.loads((ROOT/'.logs/嘉立创最终版/最终复绘制造规则与净空.json').read_text(encoding='utf-8'))['value']
groups={}
mechanical=[]
for p in data['pads']:
    label=p['PadNumber']
    ref,num=label.rsplit('.',1) if '.' in label else (label,'')
    pad={'number':num,'x':p['X'],'y':p['Y'],'pad':p['Pad'],'net':p['Net'],
         'rotation':p['Rotation'],'hole':p.get('Hole'),'plated':p['Metallization']}
    if p['Metallization']:
        groups.setdefault(ref,[]).append(pad)
    else:
        mechanical.append({'reference':ref,**pad})
geometry={'components':[{'reference':ref,'pads':pads} for ref,pads in groups.items()],
          'mechanicalPads':mechanical,
          'outline':[[5,5],[57,5],[57,87],[20,87],[20,35],[5,35]]}
assert len(groups)==18 and sum(len(x) for x in groups.values())==71 and len(mechanical)==12
OUT.mkdir(exist_ok=True,parents=True)
planner.SOURCE=OUT/'原生复绘布线基准.json'
planner.OUTPUT=OUT/('原生复绘全部网络走线.json' if '--ground' in sys.argv else '原生复绘新走线.json')
planner.SOURCE.write_text(json.dumps(geometry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
planner.main(include_ground='--ground' in sys.argv)
