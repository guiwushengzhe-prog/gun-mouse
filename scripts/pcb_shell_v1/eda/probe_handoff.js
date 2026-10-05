let p;
for(let i=0;i<25;i++){
 p = await eda.dmt_Project.getCurrentProjectInfo();
 if(p && p.data) break;
 await new Promise(r => setTimeout(r,1000));
}
if(!p || !p.data) throw new Error('副本工程尚未载入');
const b = p.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(b.schematic.page[0].uuid);
await new Promise(r => setTimeout(r,1500));
const result = [];
for(const c of await eda.sch_PrimitiveComponent.getAll()){
 if(!['R12','C1','Q1','D1'].includes(c.getState_Designator())) continue;
 const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
 result.push({ref:c.getState_Designator(),x:c.getState_X(),y:c.getState_Y(),rotation:c.getState_Rotation(),pins:pins.map(q=>({pin:q.getState_PinNumber(),x:q.getState_X(),y:q.getState_Y(),rotation:q.getState_Rotation()}))});
}
let paths;try{paths=await eda.sys_FileSystem.getProjectsPaths();}catch(e){paths=String(e);}
return {project:p.friendlyName,paths,result};
