// 导出全部器件焊盘（位置、形状、层、旋转、网络），供程序布线使用；不修改设计。
const project = await eda.dmt_Project.getCurrentProjectInfo();
const board = project.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 1000));
const out = [];
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
  const pads = await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
  for (const q of pads || []) {
    out.push({ref: c.getState_Designator(), n: q.getState_PadNumber(), x: q.getState_X(), y: q.getState_Y(),
      layer: q.getState_Layer(), pad: q.getState_Pad(), rot: q.getState_Rotation(), net: q.getState_Net()});
  }
}
return out;
