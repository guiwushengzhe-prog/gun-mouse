// 只修正这块独立测试板的覆铜范围，使用明确的闭合四角路径。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== 'eda-recovery-probe') throw new Error('只允许实验工程');
const board = project.data.find(x => x.itemType === 'Board');
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (current?.uuid !== board?.pcb?.uuid) throw new Error('活动文档不是本工程试验电路板');
const existing = (await eda.pcb_PrimitivePour.getAll()).filter(p => p.getState_PourName() === 'RECOVERY_GND_TOP');
if (existing.length !== 1) throw new Error('试验覆铜边框必须唯一');
const original = existing[0];
if (original.getState_Net() !== 'GND' || original.getState_Layer() !== 1) throw new Error('试验覆铜身份不符');
const source = [20, 20, 'L', 980, 20, 980, 780, 20, 780, 20, 20];
const polygon = eda.pcb_MathPolygon.createPolygon(source);
const pour = await eda.pcb_PrimitivePour.modify(original.getState_PrimitiveId(), {complexPolygon: polygon});
if (!pour) throw new Error('试验覆铜范围修改失败');
const errors = [];
let rebuilt;
try { rebuilt = await pour.rebuildCopperRegion(); }
catch (error) { errors.push({stage: 'rebuild', message: error?.message ?? String(error), stack: error?.stack}); }
await new Promise(resolve => setTimeout(resolve, 1500));
const read = async () => (await eda.pcb_PrimitivePoured.getAll()).map(p => ({
  id: p.getState_PrimitiveId(), pourId: p.getState_PourPrimitiveId(),
  fills: p.getState_PourFills().map(f => ({id: f.id, fill: f.fill, lineWidth: f.lineWidth, path: f.path.getSource()}))
}));
const after = await read();
const drc = await eda.pcb_Drc.check(true, false, true);
const saved = await eda.pcb_Document.save();
return {project: project.friendlyName, board: current.uuid, source,
  pourId: pour.getState_PrimitiveId(), rebuiltReturnedRegion: !!rebuilt, after,
  fillCount: after.filter(p => p.pourId === pour.getState_PrimitiveId()).reduce((s, p) => s + p.fills.length, 0),
  drc, saved, errors, note: '仅修改自有试验区域，闭合四角在板框内部；真实填充另核对磁盘和制造文件'};
