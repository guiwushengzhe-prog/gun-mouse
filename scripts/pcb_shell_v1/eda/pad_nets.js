// 读取所有器件焊盘的网络，用于核对磁盘写入是否已被编辑器载入。
const project = await eda.dmt_Project.getCurrentProjectInfo();
const board = project.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 1000));
const out = {};
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
  out[c.getState_Designator()] = Object.fromEntries((c.getState_Pads() || []).map(p => [p.padNumber, p.net]));
}
return out;
