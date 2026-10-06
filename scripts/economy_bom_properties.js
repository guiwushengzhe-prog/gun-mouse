// 经济型副本的采购属性与实际下单清单一致；保留所有器件坐标和电气连接。
const project = await eda.dmt_Project.getCurrentProjectInfo();
const intended = __CLI__.args.projectName || 'gun-mouse-economy-v2';
if (!['gun-mouse-economy-v2','gun-mouse-economy-factory-v3','gun-mouse-economy-single-v4'].includes(intended) || project.friendlyName !== intended) throw new Error('只允许修改指定经济型副本');
const board = project.data.find(x => x.itemType === 'Board');
const parts = __CLI__.args.parts;
const changed = [];
for (const [document, api, save] of [
  [board.pcb.uuid, eda.pcb_PrimitiveComponent, () => eda.pcb_Document.save()],
  [board.schematic.page[0].uuid, eda.sch_PrimitiveComponent, () => eda.sch_Document.save()]
]) {
  await eda.dmt_EditorControl.openDocument(document);
  await new Promise(r => setTimeout(r, 1200));
  for (const c of await api.getAll()) {
    const ref = c.getState_Designator();
    if (!parts[ref]) continue;
    const {Name:name, 'Supplier':supplier, 'Supplier Part':supplierId, ...otherProperty} = parts[ref];
    // 采购料号是原生独立字段，放入其他属性会在电路板中被清空。
    // 原理图接口则仍由其他属性保存采购字段，两个文档接口不能混用。
    const change = document === board.pcb.uuid
      ? {name, supplier, supplierId, otherProperty}
      : {name, otherProperty:{...otherProperty, 'Supplier':supplier, 'Supplier Part':supplierId}};
    if (!await api.modify(c.getState_PrimitiveId(), change)) throw new Error('修改属性失败 ' + ref);
    // 编辑器在同次修改其他属性时会覆盖电路板采购字段，必须随后单独写入。
    if (document === board.pcb.uuid && !await api.modify(c.getState_PrimitiveId(), {supplier, supplierId})) throw new Error('采购料号保存失败 ' + ref);
    changed.push([document, ref]);
  }
  if (!await save()) throw new Error('保存采购属性失败');
}
return {changed};
