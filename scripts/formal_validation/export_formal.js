// 将正式验证副本的数据直接写入本工作树的验证输出目录。
const allowed = ['gun-mouse-formal-baseline', 'gun-mouse-formal-roundtrip',
  'gun-mouse-formal-route', 'gun-mouse-formal-copper'];
const a = __CLI__.args;
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (!allowed.includes(a.projectName) || project?.friendlyName !== a.projectName) throw new Error('只允许指定验证副本');
const board = project.data.find(x => x.itemType === 'Board');
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (current?.uuid !== board?.pcb?.uuid || current.parentProjectUuid !== project.uuid) throw new Error('活动验证板归属错误');
const target = String(a.target).replaceAll('\\', '/');
const prefixes = ['f:/项目/枪型飞鼠/.worktrees/formal-validation/outputs/formal-validation/',
  'f:/项目/枪型飞鼠/.worktrees/route-writeback-fix/outputs/formal-validation/'];
const prefix = prefixes.find(p => target.toLowerCase().startsWith(p));
if (!prefix || target.slice(prefix.length).includes('/') || target.includes('..')) {
  throw new Error('导出目标必须在当前验证输出目录');
}
const m = eda.pcb_ManufactureData;
let file;
if (a.kind === 'gerber') file = await m.getGerberFile(a.projectName);
else if (a.kind === 'netlist') file = await m.getNetlistFile(a.projectName);
else if (a.kind === 'bom') file = await m.getBomFile(a.projectName, 'csv');
else if (a.kind === 'pnp') file = await m.getPickAndPlaceFile(a.projectName, 'csv', 'mm');
else if (a.kind === 'step') file = await m.get3DFile(a.projectName, 'step', ['Component Model'], 'Parts', false);
else if (a.kind === 'stepbare') file = await m.get3DFile(a.projectName, 'step', [], 'Parts', false);
else if (a.kind === 'pdf') file = await m.getPdfFile(a.projectName);
else if (a.kind === 'sch-netlist') {
  await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
  file = await eda.sch_ManufactureData.getNetlistFile(a.projectName, 'JLCEDA');
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
} else throw new Error('未知验证导出类型');
if (!file) throw new Error('未取得导出文件');
const saved = await eda.sys_FileSystem.saveFileToFileSystem(target, file, undefined, false);
if (saved === true) return {project: a.projectName, kind: a.kind, target, bytes: file.size, name: file.name, saved: true};
// SDK 有时把路径权限错误作为对象返回，不能当作写盘成功。
// 仍使用原生生成的文件，经已有分块通道由本地 Python 存盘。
globalThis.__gm_blob = await new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(',')[1]);
  reader.onerror = () => reject(new Error('导出文件读取失败'));
  reader.readAsDataURL(file);
});
return {project: a.projectName, kind: a.kind, target, bytes: file.size, name: file.name,
  saved: false, directWriteResult: saved, transfer: 'base64-chunks', base64Length: globalThis.__gm_blob.length};
