const args = __CLI__.args;
const project = await eda.dmt_Project.getCurrentProjectInfo();
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (project?.friendlyName !== 'gun-mouse-formal-route' || project.uuid !== args.projectUuid ||
    current?.uuid !== args.boardUuid || current.parentProjectUuid !== project.uuid) {
  throw new Error('仅允许本次独立短线试验');
}
if ((await eda.pcb_PrimitiveLine.getAll()).some(p => [1, 2].includes(p.getState_Layer())) ||
    (await eda.pcb_PrimitiveVia.getAll()).length) throw new Error('试验开始前应无铜层走线');
const state = p => p ? {id: p.getState_PrimitiveId(), net: p.getState_Net(), layer: p.getState_Layer(),
  x1: p.getState_StartX(), y1: p.getState_StartY(), x2: p.getState_EndX(), y2: p.getState_EndY(),
  width: p.getState_LineWidth(), lock: p.getState_PrimitiveLock()} : null;
const results = [];
for (let i = 0; i < args.lines.length; i++) {
  const p = args.lines[i];
  const q = await eda.pcb_PrimitiveLine.create(p.net, p.layer, p.x1, p.y1, p.x2, p.y2, p.width, p.lock);
  const id = q?.getState_PrimitiveId();
  results.push({method: 'direct', source: p, immediate: state(q), reread: id ? state(await eda.pcb_PrimitiveLine.get(id)) : null});
  const dy = 100 * (i + 1);
  const longer = await eda.pcb_PrimitiveLine.create(p.net, p.layer, p.x1, p.y1 + dy, p.x1 + 10, p.y1 + dy, p.width, p.lock);
  const longerId = longer?.getState_PrimitiveId();
  const modified = longerId ? await eda.pcb_PrimitiveLine.modify(longerId, {endX: p.x2, endY: p.y2 + dy}) : null;
  results.push({method: 'long-then-modify', source: {...p, y1: p.y1 + dy, y2: p.y2 + dy}, immediate: state(modified),
    reread: longerId ? state(await eda.pcb_PrimitiveLine.get(longerId)) : null});
}
await new Promise(resolve => setTimeout(resolve, 1000));
const after = (await eda.pcb_PrimitiveLine.getAll()).filter(p => [1, 2].includes(p.getState_Layer())).map(state);
return {projectUuid: project.uuid, results, after, saved: await eda.pcb_Document.save()};
