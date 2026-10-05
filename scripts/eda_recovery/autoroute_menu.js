// 本机 4.1.66 的原生菜单兼容入口；不修改安装程序，不使用鼠标拖拽。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== 'eda-recovery-probe') throw new Error('只允许实验工程');
const board = project.data.find(x => x.itemType === 'Board');
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (current?.uuid !== board?.pcb?.uuid) throw new Error('当前文档不是实验电路板');
const count = async () => ({
  traces: (await eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 1)).length +
    (await eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 2)).length,
  vias: (await eda.pcb_PrimitiveVia.getAllPrimitiveId()).length
});
const before = await count();
const started = Date.now();
let status = 'pending', returned, error;
const called = eda.sys_Window.openUI('autoRouting(ALL_NETS)').then(v => {
  status = 'returned'; returned = v;
}, e => {status = 'error'; error = String(e?.stack || e);});
let timer;
await Promise.race([called, new Promise(r => {timer = setTimeout(r, 12000);})]);
clearTimeout(timer);
await new Promise(r => setTimeout(r, 1500));
const after = await count();
return {status, returned, error, waitedMs: Date.now() - started, before, after,
  command: 'autoRouting(ALL_NETS)', caveat: '菜单启动不等于布线完成；命令名称只适用于已核对的本机版本'};
