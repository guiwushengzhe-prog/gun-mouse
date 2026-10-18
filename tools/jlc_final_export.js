const project=await eda.dmt_Project.getCurrentProjectInfo();
if(project?.friendlyName!=='枪型飞鼠最终版') throw new Error('最终版工程不匹配');
const boards=project.data.filter(x=>x.itemType==='PCB');
if(boards.length!==1) throw new Error('最终版工程应只有一块主板');
await eda.dmt_EditorControl.openDocument(boards[0].uuid);
const drc=await eda.pcb_Drc.check(true,false,true);
if(!Array.isArray(drc)||drc.length) throw new Error('原生规则检查未通过，拒绝导出');
if(!await eda.pcb_Document.save()) throw new Error('主板保存失败');
const files=[];
async function save(name, blob) {
  const bytes=new Uint8Array(await blob.arrayBuffer());
  let binary='';
  for(let i=0;i<bytes.length;i+=32768) binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
  files.push({name,bytes:bytes.length,base64:btoa(binary)});
}
const gerber=await eda.pcb_ManufactureData.getGerberFile('枪型飞鼠_嘉立创最终版',false,'mm',
  {integerNumber:4,decimalNumber:6},
  {metallicDrillingInformation:true,nonMetallicDrillingInformation:true,
   drillTable:false,flyingProbeTestingFile:false},
  [1,2,3,4,5,6,11].map(layerId=>({layerId,isMirror:false})));
if(!gerber) throw new Error('未生成原生制板文件');
await save('嘉立创原始制板文件.zip',gerber);
const archive=await eda.sys_FileManager.getProjectFile('枪型飞鼠_嘉立创原生工程',undefined,'epro2');
if(!archive) throw new Error('未生成原生工程备份');
await save('枪型飞鼠_嘉立创原生工程.epro2',archive);
await eda.pcb_Document.zoomToBoardOutline();
const picture=await eda.dmt_EditorControl.getCurrentRenderedAreaImage();
if(picture) await save('嘉立创主板预览.png',picture);
return {project,pcb:boards[0].uuid,drc,gerberBytes:gerber.size,
  projectArchiveBytes:archive.size,previewBytes:picture?.size,
  components:(await eda.pcb_PrimitiveComponent.getAll()).length,
  pads:(await eda.pcb_PrimitivePad.getAll()).length,
  vias:(await eda.pcb_PrimitiveVia.getAll()).length,
  nets:await eda.pcb_Net.getAllNetsName(),files};
