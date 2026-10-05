// 仅试验官方窗口入口是否支持“重建所有铺铜”，不会调用私有消息。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== 'eda-recovery-probe') throw new Error('只允许操作 eda-recovery-probe 试验工程');
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
const board = project.data?.find(item => item.itemType === 'Board' && item.pcb?.uuid === current?.uuid);
if (!board) throw new Error('当前文档必须为独立试验工程对应 PCB');
const pours = (await eda.pcb_PrimitivePour.getAll()).filter(p => p.getState_PourName() === 'RECOVERY_GND_TOP');
if (pours.length !== 1) throw new Error('必须存在唯一的 RECOVERY_GND_TOP 试验覆铜');
const pourId = pours[0].getState_PrimitiveId();
async function read() {
  const ids = await eda.pcb_PrimitivePoured.getAllPrimitiveId();
  const regions = (await eda.pcb_PrimitivePoured.getAll()).map(p => ({
    id: p.getState_PrimitiveId(), pourId: p.getState_PourPrimitiveId(),
    fills: p.getState_PourFills().map(f => ({id: f.id, fill: f.fill, lineWidth: f.lineWidth, path: f.path.getSource()}))
  }));
  return {ids, count: ids.length, regions, matchingFillCount:
    regions.filter(p => p.pourId === pourId).reduce((sum, p) => sum + p.fills.length, 0)};
}
const command = 'RebuildAllCopperArea';
const before = await read();
const started = Date.now();
let callError = null;
try { await eda.sys_Window.openUI(command); }
catch (error) { callError = {message: error?.message ?? String(error), stack: error?.stack}; }
// openUI 返回不表示菜单动作已执行或计算完成，必须另读区域数据。
let after = before;
for (let i = 0; i < 12; i++) {
  await new Promise(resolve => setTimeout(resolve, 500));
  after = await read();
  if (after.matchingFillCount > 0 || callError) break;
}
return {project: project.friendlyName, board: board.pcb.uuid, command, pourId, before, after,
  callError, elapsedMs: Date.now() - started, fillDataObserved: after.matchingFillCount > 0,
  saved: false, note: '仅验证公开窗口入口；没有返回异常不代表命令被支持。未自动保存，等待截止不取消原生任务。'};
