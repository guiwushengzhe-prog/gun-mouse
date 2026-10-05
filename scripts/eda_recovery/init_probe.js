// 独立小板：仅用于诊断嘉立创接口，不是飞鼠制造文件。
let project, board;
for (let i = 0; i < 25; i++) {
  project = await eda.dmt_Project.getCurrentProjectInfo();
  board = project?.data?.find(x => x.itemType === 'Board');
  if (board?.pcb) break;
  await new Promise(r => setTimeout(r, 800));
}
if (project?.friendlyName !== 'eda-recovery-probe' || !board?.pcb) throw new Error('试验工程尚未载入');
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 1500));
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (current?.uuid !== board.pcb.uuid || current.parentProjectUuid !== project.uuid) {
  throw new Error('活动文档不是本工程试验电路板');
}
if ((await eda.pcb_PrimitivePad.getAllPrimitiveId()).length) throw new Error('试验板已有焊盘，不重复初始化');
const polygon = eda.pcb_MathPolygon.createPolygon([0, 0, 'L', 1000, 0, 1000, 800, 0, 800, 0, 0]);
if (!await eda.pcb_PrimitivePolyline.create('', 11, polygon, 8, false)) throw new Error('板框创建失败');
const pads = [];
for (const [name, net, x, y] of [['G1', 'GND', 150, 200], ['G2', 'GND', 650, 200],
                               ['S1', 'SIGNAL', 150, 500], ['S2', 'SIGNAL', 650, 500]]) {
  const p = await eda.pcb_PrimitivePad.create(12, name, x, y, 0, ['ELLIPSE', 60, 60],
    net, ['ROUND', 35, 35], 0, 0, 0, true);
  if (!p) throw new Error('焊盘创建失败 ' + name);
  pads.push({name, net, id: p.getState_PrimitiveId()});
}
const saved = await eda.pcb_Document.save();
if (!saved) throw new Error('实验焊盘与板框保存失败');
await eda.pcb_Document.zoomToBoardOutline();
return {project: project.friendlyName, board: board.pcb.uuid, pads, saved,
  boardSizeMm: [25.4, 20.32], traceCount: (await eda.pcb_PrimitiveLine.getAll()).length};
