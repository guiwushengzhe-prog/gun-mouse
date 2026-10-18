const project=await eda.dmt_Project.getCurrentProjectInfo();
if(project?.friendlyName!=='枪型飞鼠最终版') throw new Error('最终版工程不匹配');
// 本机编辑器整理重叠短线时，遗漏了原纵轴线路中间的共线段；从两端读回坐标恢复连续走线。
const lines=await eda.pcb_PrimitiveLine.getAll();
const first=lines.find(x=>x.getState_PrimitiveId()==='ie534');
const last=lines.find(x=>x.getState_PrimitiveId()==='ie532');
if(!first||!last||[first,last].some(x=>x.getState_Net()!=='JOY_Y'||x.getState_Layer()!==1)) {
  throw new Error('修复目标线路不符');
}
const a=[first.getState_EndX(),first.getState_EndY()];
const b=[last.getState_StartX(),last.getState_StartY()];
if(Math.abs(a[0]-b[0])>.001||Math.abs(a[1]-b[1]-300)>.001) throw new Error('目标线段位置不符');
const exists=lines.some(x=>x.getState_Net()==='JOY_Y'&&x.getState_Layer()===1&&
  Math.abs(x.getState_StartX()-a[0])<.001&&Math.abs(x.getState_StartY()-a[1])<.001&&
  Math.abs(x.getState_EndX()-b[0])<.001&&Math.abs(x.getState_EndY()-b[1])<.001);
let added=null;
if(!exists) {
  const line=await eda.pcb_PrimitiveLine.create('JOY_Y',1,...a,...b,first.getState_LineWidth(),false);
  if(!line) throw new Error('恢复纵轴走线失败');
  added=line.getState_PrimitiveId();
}
for(const pour of await eda.pcb_PrimitivePour.getAll()) await pour.rebuildCopperRegion();
await eda.pcb_Document.save();
return {added,from:a,to:b,drc:await eda.pcb_Drc.check(true,false,true)};
