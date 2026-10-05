// 把 PCB 器件的唯一编号改为原理图中同位号器件的唯一编号，使两边网表可以对应比较。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (!project || project.friendlyName !== 'gun-mouse-v1') throw new Error('只允许修改 gun-mouse-v1 工程');
const board = project.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
await new Promise(r => setTimeout(r, 1500));
const sch = {};
for (const c of await eda.sch_PrimitiveComponent.getAll()) sch[c.getState_Designator()] = c.getState_UniqueId();
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 1500));
let linked = 0;
const missing = [];
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
  const uid = sch[c.getState_Designator()];
  if (!uid) { missing.push(c.getState_Designator()); continue; }
  if (await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(), {uniqueId: uid})) linked++;
}
await eda.pcb_Document.save();
return {linked, missing};
