// 只打开当前自有试验工程的电路板，并轮询确认活动文档。
let project, board;
for (let i = 0; i < 30; i++) {
  project = await eda.dmt_Project.getCurrentProjectInfo();
  if (project && project.friendlyName !== 'eda-recovery-probe') throw new Error('不是实验工程');
  board = project?.data?.find(x => x.itemType === 'Board');
  if (board?.pcb?.uuid) break;
  await new Promise(resolve => setTimeout(resolve, 300));
}
if (!board?.pcb?.uuid) throw new Error('实验板尚未载入');
const tab = await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
for (let i = 0; i < 30; i++) {
  const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
  if (current?.uuid === board.pcb.uuid && current.parentProjectUuid === project.uuid) {
    await eda.pcb_PrimitivePad.getAllPrimitiveId();
    if (__CLI__.args?.zoom === true) await eda.pcb_Document.zoomToBoardOutline();
    return {project: project.friendlyName, board: board.pcb.uuid, tab, current};
  }
  await new Promise(resolve => setTimeout(resolve, 300));
}
throw new Error('未能确认活动实验电路板');
