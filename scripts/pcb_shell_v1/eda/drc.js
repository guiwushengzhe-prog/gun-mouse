// 运行设计规则检查，返回详细结果；不修改设计。
const project = await eda.dmt_Project.getCurrentProjectInfo();
const board = project.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
await new Promise(r => setTimeout(r, 1500));
const verbose = await eda.pcb_Drc.check(true, false, true);
return {count: Array.isArray(verbose) ? verbose.length : null, items: verbose};
