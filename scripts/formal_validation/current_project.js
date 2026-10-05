// 只读取会话所属工程名称和编号；不切换任何文档，不保存。
const project = await eda.dmt_Project.getCurrentProjectInfo();
return project ? {name: project.friendlyName, uuid: project.uuid} : null;
