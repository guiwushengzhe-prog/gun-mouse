const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== '枪型飞鼠最终版') throw new Error('最终版工程不匹配');
await eda.dmt_EditorControl.openDocument('d7b364010113a027');
await eda.pcb_Document.zoomToBoardOutline();
const components = await eda.pcb_PrimitiveComponent.getAll();
const pads = await eda.pcb_PrimitivePad.getAll();
const lines = await eda.pcb_PrimitiveLine.getAll();
const vias = await eda.pcb_PrimitiveVia.getAll();
function states(primitive) {
  const names = new Set();
  for (let p=primitive; p; p=Object.getPrototypeOf(p)) {
    for (const name of Object.getOwnPropertyNames(p)) if (name.startsWith('getState_')) names.add(name);
  }
  return Object.fromEntries([...names].map(name=>[name.slice(9), primitive[name]() ]));
}
return {project, componentCount: components.length,
  components: components.map(states), pads: pads.map(states),
  lines: lines.map(states), vias: vias.map(states),
  nets: await eda.pcb_Net.getAllNetsName(),
  rules: await eda.pcb_Drc.getCurrentRuleConfiguration(),
  drc: await eda.pcb_Drc.check(true, false, true)};
