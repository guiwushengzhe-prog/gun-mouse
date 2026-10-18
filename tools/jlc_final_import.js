const source = await eda.sys_FileSystem.readFileFromFileSystem(__CLI__.args.path);
if (!source) throw new Error('最终版板文件不可读');
const current = await eda.dmt_Project.getCurrentProjectInfo();
if (current?.friendlyName !== '枪型飞鼠最终版') throw new Error('仅允许本次新建的最终版工程');
const result = await eda.sys_FileManager.importProjectByProjectFile(source, 'KiCad',
  {importOption: 'ImportDocument', associateFootprint: false, associate3DModel: false},
  {operation: 'Existing Project', existingProjectUuid: current.uuid});
if (!result) throw new Error('软件未返回迁移工程，不能视为完成');
return {result, project: await eda.dmt_Project.getCurrentProjectInfo()};
