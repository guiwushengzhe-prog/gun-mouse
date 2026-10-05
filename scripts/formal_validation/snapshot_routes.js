// 只读记录正式验证副本的铜层直线、过孔及元件／焊盘基准；不打开或保存文档。
const allowed = ['gun-mouse-formal-baseline', 'gun-mouse-formal-roundtrip', 'gun-mouse-formal-route'];
const project = await eda.dmt_Project.getCurrentProjectInfo();
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (!allowed.includes(project?.friendlyName)) throw new Error('只允许正式路线验证副本');
const board = project.data.find(x => x.itemType === 'Board' && x.pcb?.uuid === current?.uuid);
if (current?.documentType !== 3 || current.parentProjectUuid !== project.uuid ||
    board?.pcb?.parentProjectUuid !== project.uuid) throw new Error('活动PCB与工程归属不符');
const copperLayers = await eda.pcb_Layer.getTheNumberOfCopperLayers();
if (copperLayers !== 2) throw new Error('此脚本仅支持正式板现有的两层铜箔');

const plain = value => JSON.parse(JSON.stringify(value));
const byId = (a, b) => a.id.localeCompare(b.id);
const padKey = p => JSON.stringify([p.parentId, p.id]);
const byPad = (a, b) => padKey(a).localeCompare(padKey(b));
function unique(list, category, key = p => p.id) {
  const seen = new Set(), duplicates = [];
  for (const p of list) {
    const id = key(p);
    if (seen.has(id)) duplicates.push(id);
    seen.add(id);
  }
  if (duplicates.length) throw new Error('重复图元编号：' + JSON.stringify({category, ids: [...new Set(duplicates)].slice(0, 20)}));
}
const padState = (p, parentId = null) => plain({
  id: p.getState_PrimitiveId(), parentId, layer: p.getState_Layer(),
  number: p.getState_PadNumber(), x: p.getState_X(), y: p.getState_Y(),
  rotation: p.getState_Rotation(), pad: p.getState_Pad(), net: p.getState_Net(),
  hole: p.getState_Hole(), holeOffsetX: p.getState_HoleOffsetX(),
  holeOffsetY: p.getState_HoleOffsetY(), holeRotation: p.getState_HoleRotation(),
  metallization: p.getState_Metallization(), padType: p.getState_PadType(),
  specialPad: p.getState_SpecialPad(), mask: p.getState_SolderMaskAndPasteMaskExpansion(),
  heatWelding: p.getState_HeatWelding(), lock: p.getState_PrimitiveLock()
});
const componentState = c => plain({
  id: c.getState_PrimitiveId(), component: c.getState_Component(), footprint: c.getState_Footprint(),
  layer: c.getState_Layer(), x: c.getState_X(), y: c.getState_Y(), rotation: c.getState_Rotation(),
  lock: c.getState_PrimitiveLock(), addIntoBom: c.getState_AddIntoBom(), model3D: c.getState_Model3D(),
  designator: c.getState_Designator(), name: c.getState_Name(), uniqueId: c.getState_UniqueId(),
  manufacturer: c.getState_Manufacturer(), manufacturerId: c.getState_ManufacturerId(),
  supplier: c.getState_Supplier(), supplierId: c.getState_SupplierId(), other: c.getState_OtherProperty()
});
const lines = [], arcs = [], polylines = [];
// 本机折线getAll按图层过滤后路径索引错配；先无参数读取，再本地筛层。
const allLines = await eda.pcb_PrimitiveLine.getAll();
const allPolylines = await eda.pcb_PrimitivePolyline.getAll();
for (const layer of [1, 2]) {
  for (const p of allLines.filter(p => p.getState_Layer() === layer)) {
    lines.push({id: p.getState_PrimitiveId(), net: p.getState_Net(), layer: p.getState_Layer(),
      x1: p.getState_StartX(), y1: p.getState_StartY(), x2: p.getState_EndX(), y2: p.getState_EndY(),
      width: p.getState_LineWidth(), lock: p.getState_PrimitiveLock()});
  }
  arcs.push(...await eda.pcb_PrimitiveArc.getAllPrimitiveId(undefined, layer));
  for (const p of allPolylines.filter(p => p.getState_Layer() === layer)) {
    const polygon = p.getState_Polygon().getSource();
    // 仅展开单段直折线；圆弧、闭合区域、多段路径必须明确拒绝，不能漏读。
    if (!Array.isArray(polygon) || polygon.length !== 5 || polygon[2] !== 'L' ||
        [polygon[0], polygon[1], polygon[3], polygon[4]].some(v => !Number.isFinite(v))) {
      throw new Error('存在未支持的铜层折线：' + p.getState_PrimitiveId());
    }
    const common = {id: p.getState_PrimitiveId(), net: p.getState_Net(), layer: p.getState_Layer(),
      width: p.getState_LineWidth(), lock: p.getState_PrimitiveLock()};
    polylines.push({...common, polygon});
    lines.push({...common, x1: polygon[0], y1: polygon[1], x2: polygon[3], y2: polygon[4]});
  }
}
if (arcs.length) {
  throw new Error(`存在未支持的铜层圆弧，拒绝不完整快照：圆弧${arcs.length}`);
}
const vias = (await eda.pcb_PrimitiveVia.getAll()).map(p => ({
  id: p.getState_PrimitiveId(), net: p.getState_Net(), x: p.getState_X(), y: p.getState_Y(),
  holeDiameter: p.getState_HoleDiameter(), diameter: p.getState_Diameter(),
  viaType: p.getState_ViaType(), blindRuleName: p.getState_DesignRuleBlindViaName(),
  mask: p.getState_SolderMaskExpansion(), lock: p.getState_PrimitiveLock()
}));
const components = [], pads = [];
let deduplicatedPads = 0;
const padMap = new Map();
function addPad(p, origin) {
  const key = padKey(p), previous = padMap.get(key);
  if (previous) {
    // 只合并明确归属于同一元件的重复读取，不按局部编号猜测归属。
    if (origin !== 'standalone' || p.parentId === null || JSON.stringify(previous) !== JSON.stringify(p)) {
      throw new Error('重复焊盘编号或属性冲突：' + JSON.stringify({category: 'pads', parentId: p.parentId, id: p.id, origin}));
    }
    deduplicatedPads++;
    return;
  }
  padMap.set(key, p); pads.push(p);
}
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
  components.push(componentState(c));
  const pins = await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
  if (!Array.isArray(pins)) throw new Error('无法读取器件焊盘：' + c.getState_Designator());
  for (const p of pins) {
    const parentId = c.getState_PrimitiveId();
    if (typeof p.getState_ParentComponentPrimitiveId === 'function' &&
        p.getState_ParentComponentPrimitiveId() !== parentId) throw new Error('器件焊盘归属不符：' + parentId);
    addPad(padState(p, parentId), 'component');
  }
}
for (const p of await eda.pcb_PrimitivePad.getAll()) {
  const parentId = typeof p.getState_ParentComponentPrimitiveId === 'function' ?
    (p.getState_ParentComponentPrimitiveId() ?? null) : null;
  if (parentId !== null && !components.some(c => c.id === parentId)) throw new Error('焊盘所属元件不存在：' + parentId);
  addPad(padState(p, parentId), 'standalone');
}
for (const [category, list] of Object.entries({components, lines, vias})) {
  list.sort(byId);
  unique(list, category);
}
pads.sort(byPad); unique(pads, 'pads', padKey);
unique([...lines, ...vias], 'routes');
const localPadIds = new Map();
for (const p of pads) {
  if (!localPadIds.has(p.id)) localPadIds.set(p.id, []);
  localPadIds.get(p.id).push(p.parentId);
}
const sharedLocalIds = [...localPadIds].filter(([, parents]) => parents.length > 1);
const padDiagnostics = {identity: '(parentId,id)', deduplicatedPads,
  componentPads: pads.filter(p => p.parentId !== null).length,
  standalonePads: pads.filter(p => p.parentId === null).length,
  sharedLocalIdCount: sharedLocalIds.length,
  sharedLocalIdExamples: sharedLocalIds.slice(0, 10).map(([id, parents]) => ({id, parents}))};
const expected = __CLI__.args?.expectedCounts;
const counts = {components: components.length, pads: pads.length, lines: lines.length,
  vias: vias.length, arcs: 0, polylines: polylines.length, directLines: lines.length - polylines.length};
if (expected) for (const [key, value] of Object.entries(expected)) {
  if (counts[key] !== value) throw new Error(`快照数量不符：${key}期望${value}，实际${counts[key]}`);
}
return plain({schema: polylines.length ? 'gun-mouse-routes-v2' : 'gun-mouse-routes-v1',
  capturedAt: new Date().toISOString(), units: 'mil', copperLayers,
  project: {uuid: project.uuid, friendlyName: project.friendlyName},
  board: {uuid: board.pcb.uuid, name: board.pcb.name}, counts,
  components, pads, padDiagnostics, lines, vias, arcs: [], polylines});
