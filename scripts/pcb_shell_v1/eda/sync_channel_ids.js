// 使用官方接口补齐通道关联属性；不传位置、旋转、板层、封装或网络。
const project = await eda.dmt_Project.getCurrentProjectInfo();
const intended = __CLI__.args?.projectName || 'gun-mouse-v1';
if (!['gun-mouse-v1', 'gun-mouse-economy-factory-v3', 'gun-mouse-economy-single-v4'].includes(intended)
    || !project || project.friendlyName !== intended) throw new Error('工程不符');
const board = project.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
await new Promise(r => setTimeout(r, 1500));
const file = await eda.sch_ManufactureData.getNetlistFile('channel-association', 'JLCEDA');
if (!file) throw new Error('未取得编译原理图网表');
const netlist = JSON.parse(await file.text());
const sch = {};
for (const [uid, c] of Object.entries(netlist.components)) sch[c.props.Designator] = {uid, channel: c.props['Channel ID']};
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 1500));
const selected = __CLI__.args?.refs;
const physical = c => JSON.stringify({x: c.getState_X(), y: c.getState_Y(),
  rotation: c.getState_Rotation(), layer: c.getState_Layer(), footprint: c.getState_Footprint()});
let changed = 0, checked = 0;
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
  const ref = c.getState_Designator();
  if (selected && !selected.includes(ref)) continue;
  const match = sch[ref];
  if (!match || match.uid !== c.getState_UniqueId() || typeof match.channel !== 'string') {
    throw new Error('器件编号或通道关联不完整 ' + ref);
  }
  checked++;
  if (c.getState_OtherProperty()?.['Channel ID'] === match.channel) continue;
  const before = physical(c);
  const id = c.getState_PrimitiveId();
  const supplier = c.getState_Supplier(), supplierId = c.getState_SupplierId();
  const otherProperty = {...c.getState_OtherProperty(), 'Channel ID': match.channel};
  if (!await eda.pcb_PrimitiveComponent.modify(id, {otherProperty})) {
    throw new Error('无法更新通道关联 ' + ref);
  }
  // 4.1.66 在修改其他属性时会清空独立采购字段，随后单独恢复。
  if (!await eda.pcb_PrimitiveComponent.modify(id, {supplier, supplierId})) {
    throw new Error('无法恢复采购字段 ' + ref);
  }
  const updated = await eda.pcb_PrimitiveComponent.get(id);
  if (physical(updated) !== before || updated.getState_UniqueId() !== match.uid
      || updated.getState_OtherProperty()?.['Channel ID'] !== match.channel
      || updated.getState_Supplier() !== supplier || updated.getState_SupplierId() !== supplierId) {
    throw new Error('通道属性未正确更新，或器件实体属性出现变化 ' + ref);
  }
  changed++;
}
if (selected && checked !== selected.length) throw new Error('指定器件未全部找到');
if (changed) await eda.pcb_Document.save();
return {checked, changed, physicalPropertiesUnchanged: true};
