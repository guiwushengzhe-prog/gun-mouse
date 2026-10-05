// 打开当前正式设计验证副本的电路板，并确认活动工程归属。
const allowed = ['gun-mouse-formal-baseline', 'gun-mouse-formal-roundtrip',
  'gun-mouse-formal-route', 'gun-mouse-formal-copper'];
const expected = __CLI__.args?.projectName;
if (!allowed.includes(expected)) throw new Error('必须指定正式验证副本白名单名称');
let project, board;
for (let i = 0; i < 30; i++) {
  project = await eda.dmt_Project.getCurrentProjectInfo();
  if (project && project.friendlyName !== expected) throw new Error('打开了错误的验证工程');
  board = project?.data?.find(x => x.itemType === 'Board');
  if (board?.pcb?.uuid) break;
  await new Promise(resolve => setTimeout(resolve, 300));
}
if (!board?.pcb?.uuid) throw new Error('验证电路板未载入');
const tabId = await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
for (let i = 0; i < 30; i++) {
  const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
  if (current?.uuid === board.pcb.uuid && current.parentProjectUuid === project.uuid) {
    const count = (await eda.pcb_PrimitiveComponent.getAllPrimitiveId()).length;
    if (count !== 48) throw new Error('正式板应有48个器件，实际' + count);
    if (__CLI__.args?.zoom === true) await eda.pcb_Document.zoomToBoardOutline();
    return {project: expected, projectUuid: project.uuid, board: board.pcb.uuid, tabId, components: count};
  }
  await new Promise(resolve => setTimeout(resolve, 300));
}
throw new Error('活动验证文档未切换成功');
