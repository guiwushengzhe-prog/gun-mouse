// 只读检查实验会话，不输出用户名、账号编号或其它个人信息。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== 'eda-recovery-probe') throw new Error('只允许检查实验工程');
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (!project.data?.some(item => item.itemType === 'Board' && item.pcb?.uuid === current?.uuid)) {
  throw new Error('当前文档不是本工程实验电路板');
}
const user = eda.sys_Environment.getUserInfo();
let shortcuts;
try {
  shortcuts = (await eda.sys_ShortcutKey.getShortcutKeys(true)).filter(x => /布线|铺铜|覆铜|Routing|Copper|Pour/i.test(x.title));
} catch (error) { shortcuts = {error: String(error)}; }
return {version: eda.sys_Environment.getEditorCurrentVersion(),
  accountPresent: Boolean(user?.uuid), usernamePresent: Boolean(user?.username), shortcuts,
  traces: (await eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 1)).length +
    (await eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 2)).length,
  pours: await eda.pcb_PrimitivePour.getAllPrimitiveId(),
  poured: await eda.pcb_PrimitivePoured.getAllPrimitiveId(),
  autorouteProbe: globalThis.__edaRecoveryAutorouteProbe || null};
