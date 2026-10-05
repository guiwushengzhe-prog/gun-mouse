// 将公开接口快照写回已清空路线的正式验证副本；所有过孔先于导线创建。
// 不删除任何已有图元。部分创建失败时立即报错，不请求显式保存；软件仍可能自动存盘。
const args = __CLI__.args;
const supplied = args?.snapshot ?? args;
const snapshot = supplied?.value ?? supplied;
const allowed = ['gun-mouse-formal-roundtrip', 'gun-mouse-formal-route'];
const sources = ['gun-mouse-formal-baseline', ...allowed];
if (snapshot?.schema !== 'gun-mouse-routes-v1' || snapshot.units !== 'mil' ||
    snapshot.copperLayers !== 2 || !sources.includes(snapshot.project?.friendlyName)) {
  throw new Error('路线快照格式、单位、铜层数或来源工程不符');
}
for (const key of ['components', 'pads', 'lines', 'vias', 'arcs', 'polylines']) {
  if (!Array.isArray(snapshot[key])) throw new Error('快照缺少数组：' + key);
}
if (snapshot.arcs.length || snapshot.polylines.length) throw new Error('不支持铜层圆弧／折线，拒绝写回');
const project = await eda.dmt_Project.getCurrentProjectInfo();
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (!allowed.includes(project?.friendlyName)) throw new Error('只允许正式路线验证副本');
const board = project.data.find(x => x.itemType === 'Board' && x.pcb?.uuid === current?.uuid);
if (current?.documentType !== 3 || current.parentProjectUuid !== project.uuid ||
    board?.pcb?.parentProjectUuid !== project.uuid) throw new Error('活动PCB与工程归属不符');
const target = args?.target ?? {projectUuid: snapshot.project.uuid, boardUuid: snapshot.board.uuid};
if (target.projectUuid !== project.uuid || target.boardUuid !== board.pcb.uuid) {
  throw new Error('目标工程／PCB编号不符；跨独立副本须显式指定target');
}
if (await eda.pcb_Layer.getTheNumberOfCopperLayers() !== 2) throw new Error('目标不是两层铜箔');

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
// 对坐标等数字容许1e-6密耳的接口换算误差；字符串、布尔和结构必须一致。
function compare(expected, actual, path, tolerance = 1e-6) {
  if (typeof expected === 'number' && typeof actual === 'number' &&
      Number.isFinite(expected) && Number.isFinite(actual) && Math.abs(expected - actual) <= tolerance) return;
  if (expected === actual) return;
  if (expected === null || actual === null || typeof expected !== 'object' || typeof actual !== 'object') {
    throw new Error('快照与目标不一致：' + path);
  }
  if (Array.isArray(expected) !== Array.isArray(actual)) throw new Error('快照结构不一致：' + path);
  const keys = Object.keys(expected).sort(), actualKeys = Object.keys(actual).sort();
  if (keys.join('\0') !== actualKeys.join('\0')) throw new Error('快照字段不一致：' + path);
  for (const key of keys) compare(expected[key], actual[key], path + '.' + key, tolerance);
}
const components = [], pads = [];
const padMap = new Map();
function addPad(p, origin) {
  const key = padKey(p), previous = padMap.get(key);
  if (previous) {
    if (origin !== 'standalone' || p.parentId === null) {
      throw new Error('重复焊盘编号：' + JSON.stringify({category: 'pads', parentId: p.parentId, id: p.id, origin}));
    }
    compare(previous, p, 'duplicatePad.' + key);
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
components.sort(byId); pads.sort(byPad);
unique(components, 'components'); unique(pads, 'pads', padKey);
unique(snapshot.components, 'snapshot.components'); unique(snapshot.pads, 'snapshot.pads', padKey);
// 独立工程副本会给内置库重新分配所属工程编号；只映射这三个公开资源引用。
// 必须显式绑定目标、源libraryUuid等于源工程UUID、目标libraryUuid等于目标工程UUID，
// 而资源uuid本身相同。第三方库、资源uuid、名称和其它字段均继续严格比较。
const expectedComponents = plain(snapshot.components);
const actualComponents = new Map(components.map(c => [c.id, c]));
const mappedLibraryFields = [];
if (snapshot.project.uuid !== project.uuid) {
  if (!args?.target || typeof snapshot.project.uuid !== 'string' || !snapshot.project.uuid) {
    throw new Error('跨工程内置资源映射缺少明确来源／目标编号');
  }
  for (const c of expectedComponents) {
    for (const field of ['component', 'footprint', 'model3D']) {
      const resource = c[field];
      if (resource?.libraryUuid !== snapshot.project.uuid) continue;
      const actual = actualComponents.get(c.id)?.[field];
      // 真实4.1.66元件身份为{name,source,uuid}对象，封装／模型身份为字符串。
      // 不能按照类型注释把对象当字符串，也不能仅比较对象中的uuid而丢弃name/source。
      const identity = resource.uuid;
      const validIdentity = (typeof identity === 'string' && identity.length > 0) ||
        (identity !== null && typeof identity === 'object' && !Array.isArray(identity) && Object.keys(identity).length > 0);
      if (!validIdentity || !actual) {
        throw new Error('内置库资源身份无效：components.' + c.id + '.' + field + '.uuid');
      }
      compare(identity, actual.uuid, 'resourceIdentity.' + c.id + '.' + field + '.uuid', 0);
      if (actual.libraryUuid !== project.uuid) {
        throw new Error('内置库目标归属不符：components.' + c.id + '.' + field + '.libraryUuid');
      }
      mappedLibraryFields.push({componentId: c.id, field: field + '.libraryUuid', resourceUuid: resource.uuid,
        sourceLibraryUuid: resource.libraryUuid, targetLibraryUuid: actual.libraryUuid});
      resource.libraryUuid = actual.libraryUuid;
    }
  }
}
compare(expectedComponents.sort(byId), components, 'components');
compare([...snapshot.pads].sort(byPad), pads, 'pads');
for (const layer of [1, 2]) {
  for (const api of [eda.pcb_PrimitiveLine, eda.pcb_PrimitiveArc, eda.pcb_PrimitivePolyline]) {
    if ((await api.getAllPrimitiveId(undefined, layer)).length) throw new Error('目标铜层已有路线，拒绝追加');
  }
}
if ((await eda.pcb_PrimitiveVia.getAllPrimitiveId()).length) throw new Error('目标已有过孔，拒绝追加');

function finite(p, keys) {
  for (const key of keys) if (!Number.isFinite(p[key])) throw new Error('路线数字无效：' + p.id + '.' + key);
}
const sourceIds = new Set();
unique(snapshot.vias, 'snapshot.vias'); unique(snapshot.lines, 'snapshot.lines');
unique([...snapshot.vias, ...snapshot.lines], 'snapshot.routes');
for (const p of [...snapshot.vias, ...snapshot.lines]) {
  if (typeof p.id !== 'string' || !p.id || sourceIds.has(p.id) || typeof p.net !== 'string' ||
      typeof p.lock !== 'boolean') throw new Error('路线编号／网络／锁定属性无效');
  sourceIds.add(p.id);
}
for (const p of snapshot.vias) {
  finite(p, ['x', 'y', 'holeDiameter', 'diameter', 'viaType']);
  if (!(p.holeDiameter > 0 && p.diameter > p.holeDiameter) || ![0, 1, 2].includes(p.viaType) ||
      !(p.blindRuleName === null || typeof p.blindRuleName === 'string') ||
      !(p.mask === null || (p.mask && typeof p.mask === 'object' && !Array.isArray(p.mask)))) {
    throw new Error('过孔尺寸／类型／盲埋孔规则／阻焊属性无效：' + p.id);
  }
  if (p.viaType === 1 && !p.blindRuleName) throw new Error('盲埋孔缺少规则：' + p.id);
  if (p.mask) for (const v of Object.values(p.mask)) if (!Number.isFinite(v)) throw new Error('过孔阻焊扩展无效');
}
for (const p of snapshot.lines) {
  finite(p, ['layer', 'x1', 'y1', 'x2', 'y2', 'width']);
  if (![1, 2].includes(p.layer) || p.width <= 0 || (p.x1 === p.x2 && p.y1 === p.y2)) {
    throw new Error('导线层／宽度／长度无效：' + p.id);
  }
}
if (snapshot.counts?.lines !== snapshot.lines.length || snapshot.counts?.vias !== snapshot.vias.length ||
    snapshot.counts?.components !== components.length || snapshot.counts?.pads !== pads.length) {
  throw new Error('快照数量与内容不一致');
}

const created = {vias: [], lines: []};
for (const p of snapshot.vias) {
  const q = await eda.pcb_PrimitiveVia.create(p.net, p.x, p.y, p.holeDiameter, p.diameter,
    p.viaType, p.blindRuleName, p.mask, p.lock);
  if (!q) throw new Error(`创建过孔失败：${p.id}；已创建${created.vias.length}过孔、${created.lines.length}线，未请求显式保存`);
  compare(p, {id: p.id, net: q.getState_Net(), x: q.getState_X(), y: q.getState_Y(),
    holeDiameter: q.getState_HoleDiameter(), diameter: q.getState_Diameter(),
    viaType: q.getState_ViaType(), blindRuleName: q.getState_DesignRuleBlindViaName(),
    mask: q.getState_SolderMaskExpansion(), lock: q.getState_PrimitiveLock()}, 'createdVia.' + p.id);
  created.vias.push({sourceId: p.id, id: q.getState_PrimitiveId()});
}
for (const p of snapshot.lines) {
  const q = await eda.pcb_PrimitiveLine.create(p.net, p.layer, p.x1, p.y1, p.x2, p.y2, p.width, p.lock);
  if (!q) throw new Error(`创建导线失败：${p.id}；已创建${created.vias.length}过孔、${created.lines.length}线，未请求显式保存`);
  compare(p, {id: p.id, net: q.getState_Net(), layer: q.getState_Layer(),
    x1: q.getState_StartX(), y1: q.getState_StartY(), x2: q.getState_EndX(), y2: q.getState_EndY(),
    width: q.getState_LineWidth(), lock: q.getState_PrimitiveLock()}, 'createdLine.' + p.id);
  created.lines.push({sourceId: p.id, id: q.getState_PrimitiveId()});
}
const afterLines = (await eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 1)).length +
  (await eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 2)).length;
const afterVias = (await eda.pcb_PrimitiveVia.getAllPrimitiveId()).length;
if (afterLines !== snapshot.lines.length || afterVias !== snapshot.vias.length) {
  throw new Error(`写回数量不符：源${snapshot.lines.length}线/${snapshot.vias.length}过孔，实际${afterLines}线/${afterVias}过孔；未请求显式保存，副本可能已自动存盘`);
}
const saved = await eda.pcb_Document.save();
if (saved !== true) throw new Error('路线已创建但保存失败；不能据此声称已持久化');
const drc = await eda.pcb_Drc.check(true, false, true);
return {project: {uuid: project.uuid, friendlyName: project.friendlyName}, board: board.pcb.uuid,
  source: snapshot.project, units: 'mil', counts: {components: components.length, pads: pads.length,
    lines: afterLines, vias: afterVias}, mappedLibraryFieldCount: mappedLibraryFields.length,
  mappedLibraryFields, created, saved, drc};
