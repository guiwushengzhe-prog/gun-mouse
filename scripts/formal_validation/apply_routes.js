// 将公开接口快照写回已清空路线的正式验证副本；所有过孔先于导线创建。
// 不删除任何已有图元。部分创建失败时立即报错，不请求显式保存；软件仍可能自动存盘。
const args = __CLI__.args;
const supplied = args?.snapshot ?? args;
const snapshot = supplied?.value ?? supplied;
const allowed = ['gun-mouse-formal-roundtrip', 'gun-mouse-formal-route'];
const sources = ['gun-mouse-formal-baseline', ...allowed];
if (!['gun-mouse-routes-v1', 'gun-mouse-routes-v2'].includes(snapshot?.schema) || snapshot.units !== 'mil' ||
    snapshot.copperLayers !== 2 || !sources.includes(snapshot.project?.friendlyName)) {
  throw new Error('路线快照格式、单位、铜层数或来源工程不符');
}
for (const key of ['components', 'pads', 'lines', 'vias', 'arcs', 'polylines']) {
  if (!Array.isArray(snapshot[key])) throw new Error('快照缺少数组：' + key);
}
if (snapshot.arcs.length) throw new Error('不支持铜层圆弧，拒绝写回');
if (snapshot.polylines.length && snapshot.schema !== 'gun-mouse-routes-v2') throw new Error('折线快照必须使用v2格式');
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
// 本机4.1.66会清除小于0.1密耳的独立导线；以同端点单段折线保留铜几何。
// 折线路径及原生存盘按0.0001密耳取整；刷新也可把邻线端点对齐到量化后的折线。
// 几何和线宽容许半个量化单位，网络、层、锁定等属性仍严格比较。
const SHORT_LINE_LIMIT_MIL = 0.1;
const POLYLINE_COORDINATE_TOLERANCE_MIL = 0.000051;
for (const p of snapshot.polylines) {
  const s = p.polygon;
  if (!Array.isArray(s) || s.length !== 5 || s[2] !== 'L') throw new Error('不支持多段或曲线折线');
  const line = snapshot.lines.find(q => q.id === p.id);
  if (!line) throw new Error('折线缺少展开线段');
  compare(line, {id: p.id, net: p.net, layer: p.layer, x1: s[0], y1: s[1], x2: s[3], y2: s[4],
    width: p.width, lock: p.lock}, 'sourcePolyline.' + p.id);
}
unique(snapshot.polylines, 'snapshot.polylines');
if (snapshot.schema === 'gun-mouse-routes-v2' &&
    (snapshot.counts.polylines !== snapshot.polylines.length ||
     snapshot.counts.directLines !== snapshot.lines.length - snapshot.polylines.length)) {
  throw new Error('v2快照的实际图元与展开线段数量不符');
}
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
  const isPolyline = Math.hypot(p.x2 - p.x1, p.y2 - p.y1) < SHORT_LINE_LIMIT_MIL;
  const q = isPolyline ? await eda.pcb_PrimitivePolyline.create(p.net, p.layer,
    eda.pcb_MathPolygon.createPolygon([p.x1, p.y1, 'L', p.x2, p.y2]), p.width, p.lock) :
    await eda.pcb_PrimitiveLine.create(p.net, p.layer, p.x1, p.y1, p.x2, p.y2, p.width, p.lock);
  if (!q) throw new Error(`创建导线失败：${p.id}；已创建${created.vias.length}过孔、${created.lines.length}线，未请求显式保存`);
  const s = isPolyline ? q.getState_Polygon().getSource() : null;
  if (isPolyline && (!Array.isArray(s) || s.length !== 5 || s[2] !== 'L')) throw new Error('创建后的折线形状不符');
  const immediate = {id: p.id, net: q.getState_Net(), layer: q.getState_Layer(),
    x1: isPolyline ? s[0] : q.getState_StartX(), y1: isPolyline ? s[1] : q.getState_StartY(),
    x2: isPolyline ? s[3] : q.getState_EndX(), y2: isPolyline ? s[4] : q.getState_EndY(),
    width: q.getState_LineWidth(), lock: q.getState_PrimitiveLock()};
  compare({id:p.id,net:p.net,layer:p.layer,width:p.width,lock:p.lock},
    {id:immediate.id,net:immediate.net,layer:immediate.layer,width:immediate.width,lock:immediate.lock}, 'createdProperties.'+p.id);
  compare({x1:p.x1,y1:p.y1,x2:p.x2,y2:p.y2},
    {x1:immediate.x1,y1:immediate.y1,x2:immediate.x2,y2:immediate.y2}, 'createdCoordinates.'+p.id,
    isPolyline ? POLYLINE_COORDINATE_TOLERANCE_MIL : 1e-6);
  created.lines.push({sourceId: p.id, id: q.getState_PrimitiveId(), kind: isPolyline ? 'polyline' : 'line'});
}
const afterLines = (await eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 1)).length +
  (await eda.pcb_PrimitiveLine.getAllPrimitiveId(undefined, 2)).length;
const afterPolylines = (await eda.pcb_PrimitivePolyline.getAllPrimitiveId(undefined, 1)).length +
  (await eda.pcb_PrimitivePolyline.getAllPrimitiveId(undefined, 2)).length;
const afterVias = (await eda.pcb_PrimitiveVia.getAllPrimitiveId()).length;
if (afterLines + afterPolylines !== snapshot.lines.length || afterVias !== snapshot.vias.length) {
  throw new Error(`写回数量不符：源${snapshot.lines.length}线/${snapshot.vias.length}过孔，实际${afterLines}直线+${afterPolylines}单段折线/${afterVias}过孔；副本可能已自动存盘`);
}
async function verifyGeometry() {
  let maximumPolylineCoordinateDeviationMil = 0;
  const actualSegments = [];
  const allLines = await eda.pcb_PrimitiveLine.getAll();
  const allPolylines = await eda.pcb_PrimitivePolyline.getAll();
  for (const layer of [1,2]) {
    for (const q of allLines.filter(q => q.getState_Layer() === layer)) {
      actualSegments.push({id:q.getState_PrimitiveId(),kind:'line',net:q.getState_Net(),layer:q.getState_Layer(),
        x1:q.getState_StartX(),y1:q.getState_StartY(),x2:q.getState_EndX(),y2:q.getState_EndY(),
        width:q.getState_LineWidth(),lock:q.getState_PrimitiveLock()});
    }
    // 厂商按层过滤后会错配折线路径；无参数读全部再筛层，保留正确元数据和路径。
    for (const q of allPolylines.filter(q => q.getState_Layer() === layer)) {
      const s = q.getState_Polygon().getSource();
      if (!Array.isArray(s) || s.length !== 5 || s[2] !== 'L') throw new Error('折线路径改变：'+JSON.stringify({id:q.getState_PrimitiveId(),layer:q.getState_Layer(),path:s}));
      actualSegments.push({id:q.getState_PrimitiveId(),kind:'polyline',net:q.getState_Net(),layer:q.getState_Layer(),
        x1:s[0],y1:s[1],x2:s[3],y2:s[4],width:q.getState_LineWidth(),lock:q.getState_PrimitiveLock()});
    }
  }
  if (actualSegments.length !== snapshot.lines.length) throw new Error('刷新后线段数量改变');
  const usedIds = new Set(), reassignedIds = [];
  for (const mapping of created.lines) {
    const p = snapshot.lines.find(line => line.id === mapping.sourceId);
    const isPolyline = mapping.kind === 'polyline';
    const tolerance = POLYLINE_COORDINATE_TOLERANCE_MIL;
    const candidates = actualSegments.filter(q => !usedIds.has(q.id) && q.kind === mapping.kind &&
      q.net === p.net && q.layer === p.layer && q.lock === p.lock && Math.abs(q.width-p.width) <= tolerance &&
      (Math.max(Math.abs(p.x1-q.x1),Math.abs(p.y1-q.y1),Math.abs(p.x2-q.x2),Math.abs(p.y2-q.y2)) <= tolerance ||
       Math.max(Math.abs(p.x1-q.x2),Math.abs(p.y1-q.y2),Math.abs(p.x2-q.x1),Math.abs(p.y2-q.y1)) <= tolerance));
    if (candidates.length !== 1) throw new Error('路线几何缺失或不唯一：' + JSON.stringify({source:p,
      candidateCount:candidates.length,nearest:actualSegments.filter(q=>q.net===p.net&&q.layer===p.layer).map(q=>({q,
        distance:Math.min(Math.max(Math.abs(p.x1-q.x1),Math.abs(p.y1-q.y1),Math.abs(p.x2-q.x2),Math.abs(p.y2-q.y2)),
          Math.max(Math.abs(p.x1-q.x2),Math.abs(p.y1-q.y2),Math.abs(p.x2-q.x1),Math.abs(p.y2-q.y1)))}))
        .sort((a,b)=>a.distance-b.distance).slice(0,2)}));
    const matched = candidates[0];
    usedIds.add(matched.id);
    // 连接刷新可能重编图元编号；必须先逐段证明几何、网络及属性相同，才能更新编号映射。
    if (mapping.id !== matched.id) {
      reassignedIds.push({sourceId:p.id,before:mapping.id,after:matched.id});
      mapping.id = matched.id;
    }
    const actual = {...matched,id:p.id};
    // 软件可交换直线起终点；只容许整段反向，不合并、挪动或补长。
    const reverseDeviation = Math.max(Math.abs(p.x1-actual.x2), Math.abs(p.y1-actual.y2),
      Math.abs(p.x2-actual.x1), Math.abs(p.y2-actual.y1));
    const forwardDeviation = Math.max(...['x1','y1','x2','y2'].map(key => Math.abs(p[key]-actual[key])));
    if (reverseDeviation < forwardDeviation) {
      [actual.x1, actual.x2] = [actual.x2, actual.x1];
      [actual.y1, actual.y2] = [actual.y2, actual.y1];
    }
    compare({id:p.id,net:p.net,layer:p.layer,width:p.width,lock:p.lock},
      {id:actual.id,net:actual.net,layer:actual.layer,width:actual.width,lock:actual.lock}, 'writtenProperties.'+p.id,tolerance);
    compare({x1:p.x1,y1:p.y1,x2:p.x2,y2:p.y2},
      {x1:actual.x1,y1:actual.y1,x2:actual.x2,y2:actual.y2}, 'writtenCoordinates.'+p.id, tolerance);
    if (isPolyline) maximumPolylineCoordinateDeviationMil = Math.max(maximumPolylineCoordinateDeviationMil,
      Math.min(forwardDeviation, reverseDeviation));
  }
  for (const mapping of created.vias) {
    const p = snapshot.vias.find(via => via.id === mapping.sourceId);
    const q = await eda.pcb_PrimitiveVia.get(mapping.id);
    if (!q) throw new Error('过孔刷新后丢失：' + mapping.sourceId);
    compare(p, {id:p.id,net:q.getState_Net(),x:q.getState_X(),y:q.getState_Y(),
      holeDiameter:q.getState_HoleDiameter(),diameter:q.getState_Diameter(),viaType:q.getState_ViaType(),
      blindRuleName:q.getState_DesignRuleBlindViaName(),mask:q.getState_SolderMaskExpansion(),
      lock:q.getState_PrimitiveLock()}, 'writtenVia.'+p.id);
  }
  return {passed:true, verifiedSegments:created.lines.length, verifiedVias:created.vias.length,
    shortSegmentsAsPolylines:afterPolylines, maximumPolylineCoordinateDeviationMil,
    polylineCoordinateToleranceMil:POLYLINE_COORDINATE_TOLERANCE_MIL,reassignedIds};
}
const beforeSave = await verifyGeometry();
const saved = await eda.pcb_Document.save();
if (saved !== true) throw new Error('路线已创建但保存失败；不能据此声称已持久化');
const drc = await eda.pcb_Drc.check(true, false, true);
const afterSave = await verifyGeometry();
return {project: {uuid: project.uuid, friendlyName: project.friendlyName}, board: board.pcb.uuid,
  source: snapshot.project, units: 'mil', counts: {components: components.length, pads: pads.length,
    lines: afterLines + afterPolylines, directLines:afterLines, polylines:afterPolylines, vias: afterVias},
  mappedLibraryFieldCount: mappedLibraryFields.length, mappedLibraryFields, created, saved, drc,
  geometryChecks:{beforeSave,afterSave}, caveat:'写回核对不代表布线或电气设计合格，需重开及独立制造文件验证'};
