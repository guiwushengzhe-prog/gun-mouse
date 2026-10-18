const project=await eda.dmt_Project.getCurrentProjectInfo();
if(project?.friendlyName!=='枪型飞鼠最终版') throw new Error('最终版工程不匹配');
const pcb=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(pcb?.uuid!=='d7b364010113a027') throw new Error('最终主板不匹配');
if((await eda.pcb_PrimitiveComponent.getAll()).length!==26) throw new Error('最终主板元件数量不符');
const blank=project.data.find(x=>x.uuid==='806c84cf8a4167d1');
if(blank && !await eda.dmt_Pcb.deletePcb(blank.uuid)) throw new Error('空白模板未清理');
if(!await eda.dmt_Pcb.modifyPcbName(pcb.uuid,'枪型飞鼠最终主板')) throw new Error('主板重命名失败');
await eda.pcb_Document.save();
return {project:await eda.dmt_Project.getCurrentProjectInfo(),
  drc:await eda.pcb_Drc.check(true,false,true)};
