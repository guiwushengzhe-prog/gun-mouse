// 仅在正式无走线验证副本启动本机4.1.66原生算法，不改安装程序。
const project = await eda.dmt_Project.getCurrentProjectInfo();
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
const board = project?.data?.find(x => x.itemType === 'Board' && x.pcb?.uuid === current?.uuid);
if (project?.friendlyName !== 'gun-mouse-formal-route' || !board || current.parentProjectUuid !== project.uuid) {
  throw new Error('只能启动正式自动布线验证副本');
}
if ((await eda.pcb_PrimitiveComponent.getAll()).length !== 48 ||
    (await eda.pcb_PrimitiveLine.getAll()).some(p => [1,2].includes(p.getState_Layer())) ||
    (await eda.pcb_PrimitiveVia.getAll()).length) throw new Error('试验板必须保持48器件且尚无路线');
let status = 'pending', error;
const called = eda.sys_Window.openUI('autoRouting(ALL_NETS)').then(() => status = 'returned',
  e => { status = 'error'; error = String(e?.stack || e); });
let timer;
await Promise.race([called, new Promise(resolve => timer = setTimeout(resolve,12000))]);
clearTimeout(timer);
return {project: project.friendlyName, status, error, command: 'autoRouting(ALL_NETS)',
  caveat: '菜单启动只表示兼容入口响应，算法完成与实际保存另行检查'};
