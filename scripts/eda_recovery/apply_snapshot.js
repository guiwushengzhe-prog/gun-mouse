// 仅将独立四焊盘小板的原生布线快照写回；不是任意 PCB 的通用布线器。
const snapshot = __CLI__.args?.value;
if (!snapshot || snapshot.project !== 'eda-recovery-probe') throw new Error('缺少原生布线快照');
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== 'eda-recovery-probe') throw new Error('只允许实验工程');
const board = project.data.find(x => x.itemType === 'Board');
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (current?.uuid !== board?.pcb?.uuid || snapshot.board !== current.uuid) {
  throw new Error('活动板与快照板不一致');
}
if (!snapshot.allDirectConnectionsPresent || snapshot.traces.length !== 2 || snapshot.viaCount !== 0) {
  throw new Error('只允许已经核对的两条直线、零过孔实验快照');
}
if ((await eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 1)).length ||
    (await eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 2)).length ||
    (await eda.pcb_PrimitiveVia.getAllPrimitiveId()).length) {
  throw new Error('原板已有走线或过孔，拒绝覆盖或重复添加');
}
const pads = await eda.pcb_PrimitivePad.getAll();
if (pads.length !== 4 || snapshot.pads.length !== 4) throw new Error('实验焊盘数不一致');
for (const saved of snapshot.pads) {
  const p = pads.find(p => p.getState_PrimitiveId() === saved.id);
  if (!p || p.getState_Net() !== saved.net || p.getState_PadNumber() !== saved.name ||
      Math.abs(p.getState_X() - saved.x) > 1e-6 || Math.abs(p.getState_Y() - saved.y) > 1e-6) {
    throw new Error('原焊盘已变化，拒绝应用快照');
  }
}
const created = [];
for (const line of snapshot.traces) {
  if (!['GND', 'SIGNAL'].includes(line.net) || ![1, 2].includes(line.layer) ||
      ![line.x1, line.y1, line.x2, line.y2, line.width].every(Number.isFinite) || line.width <= 0) {
    throw new Error('实验线路数据无效');
  }
  const p = await eda.pcb_PrimitiveLine.create(line.net, line.layer,
    line.x1, line.y1, line.x2, line.y2, line.width, false);
  if (!p) throw new Error('原生路线写回失败，已写部分保留供检查');
  created.push({id: p.getState_PrimitiveId(), sourceId: line.id, net: line.net});
}
const drc = await eda.pcb_Drc.check(true, false, true);
const saved = await eda.pcb_Document.save();
if (!saved) throw new Error('试验路线保存失败');
return {project: project.friendlyName, board: current.uuid,
  source: '原生菜单算法生成的临时预览快照', created, drc, saved,
  note: '只通过公共图元接口写回快照，没有自编算法重新布线，没有修复原生专用接口'};
