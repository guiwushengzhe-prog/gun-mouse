// 仅修改经济型副本的参考原理图和采购属性；不改变主板铜线或引脚。
const p = await eda.dmt_Project.getCurrentProjectInfo();
if (p.friendlyName !== 'gun-mouse-economy-v2') throw new Error('目标不是经济型副本');
const board = p.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
await new Promise(r => setTimeout(r, 1000));
for (const c of await eda.sch_PrimitiveComponent.getAll()) {
  if (['SW4', 'J6'].includes(c.getState_Designator())) await eda.sch_PrimitiveComponent.delete(c.getState_PrimitiveId());
}
await eda.sch_PrimitiveWire.delete(['87a5a065ca68eb7a','6a99c9557c5801c2','b953d46d24f4d721','7a04f32e0a814da3']);
const saved = await eda.sch_Document.save();
return {saved, schematicComponents:(await eda.sch_PrimitiveComponent.getAll()).length};
