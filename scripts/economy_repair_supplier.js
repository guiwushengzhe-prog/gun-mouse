// 只修复经济型副本的两个电阻采购料号，不移动器件。
const p = await eda.dmt_Project.getCurrentProjectInfo();
if (p.friendlyName !== 'gun-mouse-economy-v2') throw new Error('只允许修改经济型副本');
const board = p.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 1000));
const parts = {R3:'C25917', R5:'C25744'};
const changed = [];
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
  const ref = c.getState_Designator();
  if (!parts[ref]) continue;
  if (!await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(), {supplier:'LCSC', supplierId:parts[ref]})) throw new Error('修复失败 '+ref);
  changed.push(ref);
}
if (!await eda.pcb_Document.save()) throw new Error('保存失败');
return {changed};
