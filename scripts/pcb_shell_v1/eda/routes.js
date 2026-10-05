// 按程序布线结果创建导线与过孔（单位密耳），可选先清除旧导线、过孔与覆铜。
const a = __CLI__.args;
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (!project || project.friendlyName !== 'gun-mouse-v1') throw new Error('只允许修改 gun-mouse-v1 工程');
const board = project.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 1000));
if (a.clear) {
  for (const api of [eda.pcb_PrimitiveLine, eda.pcb_PrimitiveVia, eda.pcb_PrimitivePour]) {
    const ids = await api.getAllPrimitiveId();
    if (ids.length) await api.delete(ids);
  }
}
let lines = 0, vias = 0, failed = [];
// 必须先建过孔再建导线：导线在创建时才与端点处已有的过孔/焊盘建立连接
for (const v of a.vias) {
  const p = await eda.pcb_PrimitiveVia.create(v[0], v[1], v[2], a.via_hole, a.via_d);
  if (p) vias++; else failed.push(['via', v]);
}
for (const s of a.lines) {
  const l = await eda.pcb_PrimitiveLine.create(s[0], s[1], s[2], s[3], s[4], s[5], s[6], false);
  if (l) lines++; else failed.push(['line', s]);
}
const ring = pts => {
  const flat = [pts[0][0], pts[0][1], 'L'];
  for (let i = 1; i < pts.length; i++) flat.push(pts[i][0], pts[i][1]);
  flat.push(pts[0][0], pts[0][1]);
  return eda.pcb_MathPolygon.createPolygon(flat);
};
const pours = [];
if (a.pour) {
  for (const layer of [1, 2]) {
    const pour = await eda.pcb_PrimitivePour.create('GND', layer, ring(a.pour), 'solid', false, 'GND_' + layer, 1, 8, false);
    // 覆铜创建后需重建填充，否则铜皮为空
    const filled = pour ? await pour.rebuildCopperRegion() : undefined;
    pours.push(!!filled);
  }
}
await eda.pcb_Document.save();
return {lines, vias, pours, failed: failed.slice(0, 20), failedCount: failed.length};
