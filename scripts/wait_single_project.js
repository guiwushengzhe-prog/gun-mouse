// 等待自建会话载入单板副本工程；只读，不切换或保存文档。
const expected = __CLI__.args?.projectName;
if (expected !== 'gun-mouse-economy-single-v4') throw new Error('只允许等待单板副本');
for (let i = 0; i < 100; i++) {
  const project = await eda.dmt_Project.getCurrentProjectInfo();
  if (project && project.friendlyName !== expected) throw new Error('会话载入了其他工程 ' + project.friendlyName);
  const board = project?.data?.find(x => x.itemType === 'Board');
  if (board?.pcb?.uuid && board?.schematic?.page?.[0]?.uuid) {
    return {name: project.friendlyName, uuid: project.uuid, pcb: board.pcb.uuid, waitedMs: i * 300};
  }
  await new Promise(resolve => setTimeout(resolve, 300));
}
throw new Error('单板副本未在30秒内载入');
