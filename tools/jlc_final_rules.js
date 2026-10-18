const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== '枪型飞鼠最终版') throw new Error('最终版工程不匹配');
const rules = await eda.pcb_Drc.getCurrentRuleConfiguration();
const config = rules.config;
const spacing = config.Spacing['Safe Spacing'].copperThickness1oz;
for (const table of Object.values(spacing.tables)) {
  for (let row=0; row<table.content.length; row++) {
    for (let col=0; col<table.content[row].length; col++) {
      if (row<=7 && col<=7) table.content[row][col]=.25;
      if (row===11 && col<=7) table.content[row][col]=.5;
      if (row===12 && col<=7) table.content[row][col]=.25;
    }
  }
}
config.Spacing['Other Spacing'].otherClearance.form.hole2Hole=.25;
config.Physics.Track.copperThickness1oz.form.data['1'].minValue=.25;
config.Physics.Track.copperThickness1oz.form.data['1'].defaultValue=.3;
Object.assign(config.Physics['Via Size'].viaSize.form, {
  viaOuterdiameterMin:.6, viaOuterdiameterDefault:.7,
  viaInnerdiameterMin:.25, viaInnerdiameterDefault:.3
});
const savedRules=await eda.pcb_Drc.overwriteCurrentRuleConfiguration(config);
if (!savedRules) throw new Error('规则同步失败');
const afterRules=await eda.pcb_Drc.getCurrentRuleConfiguration();
const rebuild=[];
for (const pour of await eda.pcb_PrimitivePour.getAll()) {
  let error=null, rebuilt;
  try {rebuilt=await pour.rebuildCopperRegion();} catch(e) {error=String(e);}
  rebuild.push({id:pour.getState_PrimitiveId(), name:pour.getState_PourName(),
    returned:!!rebuilt,error});
}
await eda.pcb_Document.save();
return {rules:afterRules,rebuild};
