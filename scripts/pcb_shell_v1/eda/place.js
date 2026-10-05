// PCB-Shell-V1：清空本工程电路板后，按 layout 放置器件、板框、开槽、安装孔、邮票孔和丝印。
// 只允许在名为 gun-mouse-v1 的工程中执行。坐标单位：密耳，Y 轴向上。
const a = __CLI__.args;
let project, board;
for (let i = 0; i < 40; i++) {  // 冷启动时等待工程载入
  project = await eda.dmt_Project.getCurrentProjectInfo();
  board = project?.data?.find(x => x.itemType === 'Board');
  if (project && board?.pcb) break;
  await new Promise(r => setTimeout(r, 500));
}
if (!project || project.friendlyName !== 'gun-mouse-v1') throw new Error('只允许修改 gun-mouse-v1 工程');
if (!board || !board.pcb) throw new Error('工程没有电路板');
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 2000));

// 清空旧图元，保证可重复生成
const clear = async (api, ids) => { if (ids && ids.length) await api.delete(ids); };
await clear(eda.pcb_PrimitiveComponent, await eda.pcb_PrimitiveComponent.getAllPrimitiveId());
await clear(eda.pcb_PrimitiveLine, await eda.pcb_PrimitiveLine.getAllPrimitiveId());
await clear(eda.pcb_PrimitiveVia, await eda.pcb_PrimitiveVia.getAllPrimitiveId());
await clear(eda.pcb_PrimitivePour, await eda.pcb_PrimitivePour.getAllPrimitiveId());
await clear(eda.pcb_PrimitivePolyline, await eda.pcb_PrimitivePolyline.getAllPrimitiveId());
await clear(eda.pcb_PrimitivePad, await eda.pcb_PrimitivePad.getAllPrimitiveId());
await clear(eda.pcb_PrimitiveString, await eda.pcb_PrimitiveString.getAllPrimitiveId());
await clear(eda.pcb_PrimitiveRegion, await eda.pcb_PrimitiveRegion.getAllPrimitiveId());
await eda.pcb_Document.setCanvasOrigin(0, 0);

const ring = pts => {
  const flat = [pts[0][0], pts[0][1], 'L'];
  for (let i = 1; i < pts.length; i++) flat.push(pts[i][0], pts[i][1]);
  flat.push(pts[0][0], pts[0][1]);
  return eda.pcb_MathPolygon.createPolygon(flat);
};
const outline = await eda.pcb_PrimitivePolyline.create('', 11, ring(a.outline), 8, false);
if (!outline) throw new Error('板框创建失败');
for (const c of a.cutouts) {
  if (!await eda.pcb_PrimitivePolyline.create('', 11, ring(c), 8, false)) throw new Error('开槽创建失败');
}
for (const h of a.holes) {
  const pad = await eda.pcb_PrimitivePad.create(12, h.id, h.x, h.y, 0, ['ELLIPSE', h.d, h.d], '', ['ROUND', h.d, h.d], 0, 0, 0, false);
  if (!pad) throw new Error('孔创建失败 ' + h.id);
}

const cache = {};
const placed = {};
for (const p of a.parts) {
  if (!cache[p.lcsc]) {
    const found = (await eda.lib_Device.getByLcscIds([p.lcsc]))[0];
    if (!found) throw new Error('库中找不到 ' + p.lcsc);
    cache[p.lcsc] = found;
  }
  const c = await eda.pcb_PrimitiveComponent.create(cache[p.lcsc], 1, p.x, p.y, p.rot, false);
  if (!c) throw new Error('器件创建失败 ' + p.ref);
  await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(), {designator: p.ref});
  placed[p.ref] = c.getState_PrimitiveId();
}

for (const t of a.texts) {
  const s = await eda.pcb_PrimitiveString.create(t.layer, t.x, t.y, t.text, 'default', t.size, t.stroke, 5, t.rot, false, 0, false, false);
  if (!s) throw new Error('丝印创建失败 ' + t.text);
}
await eda.pcb_Document.save();
return {placed, components: (await eda.pcb_PrimitiveComponent.getAllPrimitiveId()).length};
