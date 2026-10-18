const project=await eda.dmt_Project.getCurrentProjectInfo();
if(project?.friendlyName!=='枪型飞鼠最终版') throw new Error('最终版工程不匹配');
const main='d7b364010113a027';
const blank=await eda.dmt_Pcb.createPcb();
if(!blank) throw new Error('无法读取软件默认层叠模板');
try {
  await eda.dmt_EditorControl.openDocument(blank);
  return {stack:await eda.pcb_Layer.getCurrentPhysicalStackingConfiguration(),
    defaults:await eda.pcb_Layer.getAllPhysicalStackingConfigurations(),
    source:await eda.sys_FileManager.getDocumentSource()};
} finally {
  await eda.dmt_EditorControl.openDocument(main);
  if(!await eda.dmt_Pcb.deletePcb(blank)) throw new Error('临时层叠模板未清理');
}
