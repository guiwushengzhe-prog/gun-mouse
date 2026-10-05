// 仅诊断独立试验板的原生覆铜；不修改飞鼠工程或删除、修改已有图元。
const PROJECT = 'eda-recovery-probe';
const NAME = 'RECOVERY_GND_TOP';
const inspectOnly = __CLI__.args?.inspectOnly === true;
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== PROJECT) throw new Error('只允许诊断 eda-recovery-probe 工程');
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
const board = project.data?.find(x => x.itemType === 'Board' && x.pcb?.uuid === current?.uuid);
if (!board) throw new Error('当前活动文档必须为独立试验工程对应 PCB，请由根代理先确认');

const errors = [];
async function attempt(stage, action) {
  try { return {ok: true, value: await action()}; }
  catch (error) {
    const detail = {stage, name: error?.name, message: error?.message ?? String(error), stack: error?.stack};
    errors.push(detail);
    return {ok: false, error: detail};
  }
}
function describePoured(poured) {
  if (!poured) return null;
  return {
    id: poured.getState_PrimitiveId(),
    pourId: poured.getState_PourPrimitiveId(),
    fills: poured.getState_PourFills().map(fill => ({
      id: fill.id, fill: fill.fill, lineWidth: fill.lineWidth, path: fill.path.getSource()
    }))
  };
}
async function snapshot(stage) {
  const ids = await attempt(stage + '.getAllPrimitiveId', () => eda.pcb_PrimitivePoured.getAllPrimitiveId());
  const data = await attempt(stage + '.getAll', async () => (await eda.pcb_PrimitivePoured.getAll()).map(describePoured));
  return {
    ids: ids.ok ? ids.value : null,
    countByIds: ids.ok ? ids.value.length : null,
    countByObjects: data.ok ? data.value.length : null,
    regions: data.ok ? data.value : null,
    readsSucceeded: ids.ok && data.ok
  };
}

const existing = (await eda.pcb_PrimitivePour.getAll()).filter(p => p.getState_PourName() === NAME);
if (existing.length > 1) throw new Error('试验覆铜名称重复，请另建独立试验工程');
if (!inspectOnly && existing.length) throw new Error('试验覆铜已存在；用 inspectOnly=true 只读复查，不重复创建');
if (inspectOnly && !existing.length) throw new Error('尚不存在 RECOVERY_GND_TOP，无法只读复查');

const before = await snapshot('before');
const result = {project: PROJECT, board: board.pcb.uuid, inspectOnly, units: 'mil',
  currentDocument: current, name: NAME, net: 'GND', layer: 1, rectangle: [20, 20, 980, 780], before};
let pour = existing[0];
if (!inspectOnly) {
  // 显式闭合四角，避免 R 模式以左上点向负 Y 延伸的方向歧义。
  const polygon = eda.pcb_MathPolygon.createPolygon([20, 20, 'L', 980, 20, 980, 780, 20, 780, 20, 20]);
  const created = await attempt('create', () => eda.pcb_PrimitivePour.create(
    'GND', 1, polygon, 'solid', false, NAME, 1, 8, false));
  pour = created.value;
  result.created = !!pour;
  if (pour) {
    result.pourId = pour.getState_PrimitiveId();
    const rebuilt = await attempt('rebuildCopperRegion', async () => describePoured(await pour.rebuildCopperRegion()));
    result.rebuild = {ok: rebuilt.ok, returnedRegion: rebuilt.ok ? rebuilt.value : null};
    // 区分接口即刻返回为空与后台计算延迟；只在这块新实验板等待 3 秒。
    await new Promise(resolve => setTimeout(resolve, 3000));
    result.observationWaitMs = 3000;
  }
}
if (pour) {
  result.pourId = pour.getState_PrimitiveId();
  result.pourSource = pour.getState_ComplexPolygon().getSource();
  const read = await attempt('getCopperRegion', async () => describePoured(await pour.getCopperRegion()));
  result.getCopperRegion = {ok: read.ok, returnedRegion: read.ok ? read.value : null};
}
result.after = await snapshot('after');
result.matchingRegions = (result.after.regions ?? []).filter(region => region.pourId === result.pourId);
result.fillCount = result.matchingRegions.reduce((sum, region) => sum + region.fills.length, 0);
result.hasFillData = result.fillCount > 0;
if (!inspectOnly) result.save = await attempt('save', () => eda.pcb_Document.save());
result.errors = errors;
return result;
