// 保留 PCB 已有唯一编号，为重新生成的原理图补齐对应编号，再核对关联。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (!project || project.friendlyName !== 'gun-mouse-v1') throw new Error('只允许修改 gun-mouse-v1 工程');
const board = project.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 1500));
const pcbIds = {};
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
  pcbIds[c.getState_Designator()] = c.getState_UniqueId();
}
await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
await new Promise(r => setTimeout(r, 1500));
const sch = {};
let assignedSchematicIds = 0;
for (const c of await eda.sch_PrimitiveComponent.getAll()) {
  const ref = c.getState_Designator();
  const uid = c.getState_UniqueId() || pcbIds[ref];
  if (!uid) throw new Error(`器件 ${ref} 缺少可关联的唯一编号`);
  if (!c.getState_UniqueId()) {
    if (!await eda.sch_PrimitiveComponent.modify(c.getState_PrimitiveId(), {uniqueId: uid})) {
      throw new Error(`无法设置原理图器件 ${ref} 的唯一编号`);
    }
    assignedSchematicIds++;
  }
  sch[ref] = uid;
}
if (assignedSchematicIds) await eda.sch_Document.save();
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 1500));
let linked = 0;
let changedPcbIds = 0;
const missing = [];
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
  const uid = sch[c.getState_Designator()];
  if (!uid) { missing.push(c.getState_Designator()); continue; }
  if (c.getState_UniqueId() === uid) { linked++; continue; }
  if (!await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(), {uniqueId: uid})) {
    throw new Error(`无法关联电路板器件 ${c.getState_Designator()}`);
  }
  changedPcbIds++;
  linked++;
}
if (missing.length || linked !== Object.keys(sch).length) throw new Error(`器件关联不完整：${JSON.stringify({linked, missing})}`);
if (changedPcbIds) await eda.pcb_Document.save();
return {linked, assignedSchematicIds, changedPcbIds, missing};
