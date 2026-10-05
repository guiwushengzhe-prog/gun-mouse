// 读取隔离小板实际走线、填充及设计规则检查结果；仅可选保存实验板。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== 'eda-recovery-probe') throw new Error('只允许实验工程');
const board = project.data.find(x => x.itemType === 'Board');
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (current?.uuid !== board?.pcb?.uuid) throw new Error('当前文档不是实验电路板');
const pads = (await eda.pcb_PrimitivePad.getAll()).map(p => ({
  id: p.getState_PrimitiveId(), name: p.getState_PadNumber(), net: p.getState_Net(),
  x: p.getState_X(), y: p.getState_Y(), layer: p.getState_Layer()
}));
const traces = [];
for (const layer of [1, 2]) {
  for (const p of await eda.pcb_PrimitiveLine.getAll(undefined, layer)) {
    traces.push({id: p.getState_PrimitiveId(), net: p.getState_Net(), layer,
      x1: p.getState_StartX(), y1: p.getState_StartY(),
      x2: p.getState_EndX(), y2: p.getState_EndY(), width: p.getState_LineWidth()});
  }
}
// 本小板预期是两条直线连接两组同网通孔，不作为任意复杂板子的验证器。
const connectionChecks = ['GND', 'SIGNAL'].map(net => {
  const nodes = pads.filter(p => p.net === net);
  const lines = traces.filter(p => p.net === net);
  // 原生算法往返换算产生约 0.002 mil 的端点舍入；容许 0.01 mil（0.000254 mm）。
  const same = (x, y, p) => Math.hypot(x - p.x, y - p.y) < 0.01;
  const directConnected = nodes.length === 2 && lines.some(l =>
    (same(l.x1, l.y1, nodes[0]) && same(l.x2, l.y2, nodes[1])) ||
    (same(l.x1, l.y1, nodes[1]) && same(l.x2, l.y2, nodes[0])));
  return {net, padCount: nodes.length, traceCount: lines.length, directConnected};
});
const pours = [];
for (const p of await eda.pcb_PrimitivePoured.getAll()) {
  pours.push({id: p.getState_PrimitiveId(), pourId: p.getState_PourPrimitiveId(),
    fills: p.getState_PourFills().map(f => ({id: f.id, fill: f.fill,
      lineWidth: f.lineWidth, path: f.path.getSource()}))});
}
const drc = await eda.pcb_Drc.check(true, false, true);
const save = __CLI__.args?.save === true ? await eda.pcb_Document.save() : null;
return {project: project.friendlyName, board: board.pcb.uuid, units: 'mil', pads, traces,
  viaCount: (await eda.pcb_PrimitiveVia.getAllPrimitiveId()).length,
  connectionChecks, allDirectConnectionsPresent: connectionChecks.every(x => x.directConnected),
  pours, fillCount: pours.reduce((s, p) => s + p.fills.length, 0), drc, save};
