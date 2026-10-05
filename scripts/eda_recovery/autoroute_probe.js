// 仅在独立小测试工程调用公开自动布线接口；不打开或关闭会话、不清除既有图元。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (!project || project.friendlyName !== 'eda-recovery-probe') {
  throw new Error('仅允许在友好名称为 eda-recovery-probe 的独立测试工程运行');
}
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
const board = (project.data || []).find(item => item.itemType === 'Board' && item.pcb?.uuid === current?.uuid);
if (!board) throw new Error('请由主代理先打开测试工程对应的 PCB 文档');

async function countPrimitives() {
  const [top, bottom, vias] = await Promise.all([
    eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 1),
    eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 2),
    eda.pcb_PrimitiveVia.getAllPrimitiveId(),
  ]);
  return { traces: top.length + bottom.length, topTraces: top.length, bottomTraces: bottom.length, vias: vias.length };
}

const input = {
  // 本机公开类型与运行实现都读取 RoutingNets，而不是旧示例中的 nets。
  RoutingNets: ['GND'],
  existingPrimitiveMode: 'keep',
  optimization: 0, // 速度优先。
  cornerStyle: 0, // 45 度。
  layers: [1, 2],
  ignoreNets: [],
};
const before = await countPrimitives();
const started = Date.now();
const state = {
  projectName: project.friendlyName,
  pcbUuid: board.pcb.uuid,
  version: eda.sys_Environment.getEditorCurrentVersion(),
  input,
  waitLimitMs: 12000,
  status: 'pending',
  before,
  startedAt: new Date(started).toISOString(),
  events: [{ event: 'before-autRouting', elapsedMs: 0 }],
};
globalThis.__edaRecoveryAutorouteProbe = state;
let timer;
const pending = Promise.resolve().then(() => eda.pcb_Document.autoRouting(input)).then(
  result => {
    state.status = 'returned';
    state.result = result;
    state.events.push({ event: 'autoRouting-returned', elapsedMs: Date.now() - started });
    return state.status;
  },
  error => {
    state.status = 'rejected';
    state.error = String(error?.stack || error);
    state.events.push({ event: 'autoRouting-rejected', elapsedMs: Date.now() - started });
    return state.status;
  },
);
const outcome = await Promise.race([
  pending,
  new Promise(resolve => {
    timer = setTimeout(() => resolve('wait-expired'), 12000);
  }),
]);
clearTimeout(timer);
const waitedMs = Date.now() - started;
// 等待边界只约束此次布线 Promise；Promise.race 并不取消软件内部任务。
state.events.push({ event: outcome, elapsedMs: waitedMs });
let after;
try {
  after = await countPrimitives();
} catch (error) {
  after = { error: String(error?.stack || error) };
}
state.after = after;
return {
  ...state,
  outcome,
  waitedMs,
  finishedAt: new Date().toISOString(),
  routingStillPending: state.status === 'pending',
  delta: typeof after.traces === 'number' ? { traces: after.traces - before.traces, vias: after.vias - before.vias } : null,
  cancelled: false,
  note: '超时只停止脚本等待，不取消原生任务；仅在此独立测试工程继续观察。未自动保存。',
};
