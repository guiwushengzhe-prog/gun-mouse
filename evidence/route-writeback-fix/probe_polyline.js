const args = __CLI__.args;
const project = await eda.dmt_Project.getCurrentProjectInfo();
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (project?.friendlyName !== 'gun-mouse-formal-route' || project.uuid !== args.projectUuid ||
    current?.uuid !== args.boardUuid || current.parentProjectUuid !== project.uuid) throw new Error('仅允许独立短线试验');
const state = p => p ? {id: p.getState_PrimitiveId(), net: p.getState_Net(), layer: p.getState_Layer(),
  polygon: p.getState_Polygon().getSource(), width: p.getState_LineWidth(), lock: p.getState_PrimitiveLock()} : null;
const results = [];
for (const p of args.lines) {
  const polygon = eda.pcb_MathPolygon.createPolygon([p.x1, p.y1, 'L', p.x2, p.y2]);
  const q = await eda.pcb_PrimitivePolyline.create(p.net, p.layer, polygon, p.width, p.lock);
  const id = q?.getState_PrimitiveId();
  results.push({source: p, immediate: state(q), reread: id ? state(await eda.pcb_PrimitivePolyline.get(id)) : null});
}
await new Promise(resolve => setTimeout(resolve, 1000));
return {projectUuid: project.uuid, results, after: (await eda.pcb_PrimitivePolyline.getAll()).filter(p =>
  [1, 2].includes(p.getState_Layer())).map(state), saved: await eda.pcb_Document.save()};
