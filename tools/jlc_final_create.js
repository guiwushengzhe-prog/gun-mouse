if (await eda.dmt_Project.getCurrentProjectInfo()) throw new Error('当前会话已有工程');
const uuid = await eda.dmt_Project.createProject('枪型飞鼠最终版', 'gunmouse-final-jlc-20261018',
  undefined, undefined, '与2026-10-18最终打印件配套；后续在嘉立创专业版维护。', undefined, 'eprj3');
if (!uuid) throw new Error('创建原生工程失败');
await eda.dmt_Project.openProject(uuid);
const pcb = await eda.dmt_Pcb.createPcb();
if (!pcb) throw new Error('创建主板失败');
await eda.dmt_Pcb.modifyPcbName(pcb, '枪型飞鼠最终主板');
await eda.dmt_EditorControl.openDocument(pcb);
await eda.pcb_Document.save();
return {uuid, pcb, project: await eda.dmt_Project.getCurrentProjectInfo(),
  paths: await eda.sys_FileSystem.getProjectsPaths()};
