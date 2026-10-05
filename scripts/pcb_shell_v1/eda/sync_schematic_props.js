// 把现有 PCB 的型号、阻容值、采购描述和板层偏好补到原理图，不改变连接或器件位置。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (!project || project.friendlyName !== 'gun-mouse-v1') throw new Error('工程不符');
const board = project.data.find(x => x.itemType === 'Board');
let want = __CLI__.args?.parts;
if (!want) {
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  await new Promise(r => setTimeout(r, 1500));
  const file = await eda.pcb_ManufactureData.getNetlistFile('existing-pcb-properties');
  if (!file) throw new Error('未取得现有 PCB 属性');
  const data = JSON.parse(await file.text());
  const reserved = new Set(['Unique ID', 'Footprint', 'Device', 'Symbol', '3D Model',
    '3D Model Transform', 'Reuse Block', 'Group ID', 'Channel ID', 'Convert to PCB',
    'Add into BOM', 'FootprintName', 'DeviceName', 'Designator']);
  want = {};
  for (const c of Object.values(data.components)) {
    want[c.props.Designator] = Object.fromEntries(Object.entries(c.props).filter(([k]) => !reserved.has(k)));
  }
}
await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
await new Promise(r => setTimeout(r, 1500));
let changed = 0;
for (const c of await eda.sch_PrimitiveComponent.getAll()) {
  const props = want[c.getState_Designator()];
  if (!props) throw new Error('缺少器件属性 ' + c.getState_Designator());
  const otherProperty = {...props};
  delete otherProperty.Name;
  if (!await eda.sch_PrimitiveComponent.modify(c.getState_PrimitiveId(), {
    name: props.Name, otherProperty
  })) throw new Error('无法补齐器件属性 ' + c.getState_Designator());
  changed++;
}
await eda.sch_Document.save();
return {changed, scope: '补齐原理图的型号、阻容值、采购说明与板层偏好，保持 PCB 不变'};
