// 只读获取当前试验工程的标签信息，用于区分正式 PCB 与迭代预览。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== 'eda-recovery-probe') throw new Error('只允许实验工程');
return {project: project.friendlyName, projectUuid: project.uuid,
  current: await eda.dmt_SelectControl.getCurrentDocumentInfo(),
  splitScreen: await eda.dmt_EditorControl.getSplitScreenTree()};
