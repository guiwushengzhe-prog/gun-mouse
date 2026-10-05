// 仅给正式覆铜对照副本新建主板双面 GND；不改原板框、器件、导线、过孔、规则。
// 参数：{config: <器件配置>, layout: <已核实 source-layout.json>, observationWaitMs?: 3000}。
// 主板范围严格沿用 layout.py 的 pour_uv；小板和桥不另加铜。镂空由既有板框裁切。
const PROJECT = 'gun-mouse-formal-copper';
const NAMES = ['FORMAL_MAIN_GND_TOP', 'FORMAL_MAIN_GND_BOTTOM'];
const args = __CLI__.args || {};
const config = args.config, layout = args.layout;
const MIL_MM = 0.0254;
const epsMm = 0.0001;
if (!Array.isArray(config?.parts) || config.parts.length !== 48 ||
    config.parts.reduce((sum, part) => sum + Object.keys(part.nets || {}).length, 0) !== 160) {
  throw new Error('必须提供正式板48器件、160已连接焊盘配置');
}
function ring(points) {
  if (!Array.isArray(points) || points.length < 3 || points.some(point =>
    !Array.isArray(point) || point.length !== 2 || point.some(value => !Number.isFinite(value)))) {
    throw new Error('覆铜/板框轮廓必须是有限数值二维点列');
  }
  const mmToMil = value => Math.round(value / MIL_MM * 1000) / 1000;
  const source = [mmToMil(points[0][0]), mmToMil(points[0][1]), 'L'];
  for (const point of points.slice(1)) source.push(mmToMil(point[0]), mmToMil(point[1]));
  source.push(source[0], source[1]);
  return source;
}
const source = ring(layout?.pour_uv);
const antennaCut = config.board?.antenna_copper_keepout_x_min;
if (antennaCut !== 52 || layout.pour_uv.some(point => point[0] < -antennaCut - epsMm)) {
  throw new Error('主板覆铜必须保留原 ESP32 天线区域：PCB U <= -52 mm 不得铺铜');
}
const expectedOutlinePaths = [ring(layout.outline_uv), ...(layout.cutouts || []).map(cutout => ring(cutout.uv))];
function sameSource(actual, expected) {
  // 软件存盘会反转板框绕向，起点也可能循环平移；只接受完全相同的 L 顶点。
  // 不删共线点、不改坐标、不用包围盒代替轮廓，仍按 0.003 密耳逐点核对。
  function pointsOf(path) {
    if (!Array.isArray(path) || path.length < 6 || path[2] !== 'L') return null;
    const numbers = [];
    for (const value of path) {
      if (value === 'L') {
        if (numbers.length < 2 || numbers.length % 2) return null;
      } else if (Number.isFinite(value)) numbers.push(value);
      else return null;
    }
    if (numbers.length % 2) return null;
    const points = [];
    for (let index = 0; index < numbers.length; index += 2) points.push(numbers.slice(index, index + 2));
    if (points.length > 1 && samePoint(points[0], points[points.length - 1])) points.pop();
    return points;
  }
  function samePoint(a, b) { return Math.abs(a[0] - b[0]) < 0.003 && Math.abs(a[1] - b[1]) < 0.003; }
  const a = pointsOf(actual), e = pointsOf(expected);
  if (!a || !e || a.length !== e.length) return false;
  for (let offset = 0; offset < a.length; offset++) {
    if (!samePoint(a[offset], e[0])) continue;
    for (const direction of [1, -1]) {
      if (e.every((point, index) => samePoint(point, a[(offset + direction * index + a.length) % a.length]))) return true;
    }
  }
  return false;
}
async function guard() {
  const project = await eda.dmt_Project.getCurrentProjectInfo();
  const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
  const board = project?.data?.find(item => item.itemType === 'Board' && item.pcb?.uuid === current?.uuid);
  if (project?.friendlyName !== PROJECT || !board ||
      (current.parentProjectUuid && current.parentProjectUuid !== project.uuid)) {
    throw new Error('只能修改 gun-mouse-formal-copper 活动电路板对照副本');
  }
  return {project: project.friendlyName, board: board.pcb.uuid};
}
const identity = await guard();
const existing = await eda.pcb_PrimitivePour.getAll();
if (existing.length) throw new Error('该覆铜对照副本已有覆铜；拒绝覆盖、删除或重复添加，请只读复查');
const actualOutline = (await eda.pcb_PrimitivePolyline.getAll()).filter(poly => poly.getState_Layer() === 11)
  .map(poly => poly.getState_Polygon().getSource());
if (actualOutline.length !== expectedOutlinePaths.length || expectedOutlinePaths.some(expected =>
    !actualOutline.some(actual => sameSource(actual, expected)))) {
  throw new Error('当前板框及镂空与已验证布局不一致；停止新建覆铜');
}
async function originalSnapshot() {
  const components = (await eda.pcb_PrimitiveComponent.getAll()).map(component => ({
    id: component.getState_PrimitiveId(), ref: component.getState_Designator(),
    x: component.getState_X(), y: component.getState_Y(), rotation: component.getState_Rotation(),
    layer: component.getState_Layer(), footprint: component.getState_Footprint(),
    pads: component.getState_Pads()}));
  const lines = (await eda.pcb_PrimitiveLine.getAll()).map(line => ({id: line.getState_PrimitiveId(),
    net: line.getState_Net(), layer: line.getState_Layer(), sx: line.getState_StartX(), sy: line.getState_StartY(),
    ex: line.getState_EndX(), ey: line.getState_EndY(), width: line.getState_LineWidth()}));
  const arcs = (await eda.pcb_PrimitiveArc.getAll()).map(arc => ({id: arc.getState_PrimitiveId(),
    net: arc.getState_Net(), layer: arc.getState_Layer(), sx: arc.getState_StartX(), sy: arc.getState_StartY(),
    ex: arc.getState_EndX(), ey: arc.getState_EndY(), angle: arc.getState_ArcAngle(), width: arc.getState_LineWidth()}));
  const vias = (await eda.pcb_PrimitiveVia.getAll()).map(via => ({id: via.getState_PrimitiveId(),
    net: via.getState_Net(), x: via.getState_X(), y: via.getState_Y(),
    hole: via.getState_HoleDiameter(), diameter: via.getState_Diameter()}));
  const polylines = (await eda.pcb_PrimitivePolyline.getAll()).map(poly => ({id: poly.getState_PrimitiveId(),
    net: poly.getState_Net(), layer: poly.getState_Layer(), width: poly.getState_LineWidth(),
    path: poly.getState_Polygon().getSource()}));
  for (const entries of [components, lines, arcs, vias, polylines]) entries.sort((a, b) => a.id.localeCompare(b.id));
  return {components, lines, arcs, vias, polylines};
}
const before = await originalSnapshot();
if (before.components.length !== 48) throw new Error('当前副本器件数不是48，停止新建覆铜');
const configuredRefs = new Set(config.parts.map(part => part.ref));
if (before.components.some(part => !configuredRefs.has(part.ref)) ||
    !before.components.some(part => part.pads?.some(pad => pad.net === 'GND'))) {
  throw new Error('当前器件身份或地网络不符合正式配置');
}
const errors = [];
async function attempt(stage, action) {
  try { return {ok: true, value: await action()}; }
  catch (error) { const detail = {stage, message: error?.message ?? String(error)};
    errors.push(detail); return {ok: false, error: detail}; }
}
const created = [];
for (const [index, layer] of [1, 2].entries()) {
  await guard();
  const result = await attempt('新建' + NAMES[index], () => eda.pcb_PrimitivePour.create(
    'GND', layer, eda.pcb_MathPolygon.createPolygon(source), 'solid', false, NAMES[index], 1, 8, false));
  if (!result.value) { errors.push({stage: '新建' + NAMES[index], message: '接口未返回覆铜对象'}); break; }
  const pour = result.value;
  const rebuilt = await attempt('重建' + NAMES[index], () => pour.rebuildCopperRegion());
  created.push({id: pour.getState_PrimitiveId(), name: NAMES[index], net: 'GND', layer,
    rebuiltWithoutException: rebuilt.ok, immediateRegionReturned: !!rebuilt.value});
}
const waitMs = Math.min(10000, Math.max(0, Number.isFinite(args.observationWaitMs) ? args.observationWaitMs : 3000));
await new Promise(resolve => setTimeout(resolve, waitMs));
const poured = await attempt('读取真实填充路径', () => eda.pcb_PrimitivePoured.getAll());
const regions = (poured.value || []).map(region => ({id: region.getState_PrimitiveId(),
  pourId: region.getState_PourPrimitiveId(), fills: region.getState_PourFills().map(fill => ({
    id: fill.id, fill: fill.fill, lineWidth: fill.lineWidth, path: fill.path.getSource()}))}));
for (const pour of created) pour.fillCount = regions.filter(region => region.pourId === pour.id)
  .reduce((sum, region) => sum + region.fills.length, 0);
await guard();
const after = await originalSnapshot();
const originalGeometryUnchanged = JSON.stringify(before) === JSON.stringify(after);
if (!originalGeometryUnchanged) errors.push({stage: '原设计复核', message: '原有器件/线路/过孔/板框出现变化，需要人工核对'});
const save = await attempt('保存对照副本', () => eda.pcb_Document.save());
const drc = await attempt('覆铜后的设计规则检查', () => eda.pcb_Drc.check(true, false, true));
return {...identity, scope: '原布局定义的主板双面 GND 原生覆铜对照；不替换交付工程',
  units: {layout: 'mm', polygonInput: 'mil', returnedFillPaths: '接口原始填充路径，不能据此臆定单位'},
  newPourBoundaryOnly: {wholeUnitXFromMm: antennaCut, pcbULessEqualMm: -antennaCut},
  sourcePolygonMm: layout.pour_uv, sourcePolygonMil: source,
  physicalCutoutsPreserved: layout.cutouts || [],
  scopeNotes: ['小板与连接桥不另新增地铜，保留原 pour_uv 范围',
    '天线限制这里只约束新建铜面；原有 C5/C6、其他焊盘与线路是否进入天线区需要独立检查，不能声称整板已避开天线',
    '原生填充需按既有板框/非金属化孔/过线槽裁切；须核对导出的铜层未覆盖镂空和天线区',
    '填充路径非空与规则通过只证明软件检查，尚不代表实物或制造验收'],
  created, observationWaitMs: waitMs, actualFillRegions: regions,
  hasBothLayersFilled: created.length === 2 && created.every(pour => pour.fillCount > 0),
  originalGeometryUnchanged, originalCounts: {components: before.components.length,
    lines: before.lines.length, arcs: before.arcs.length, vias: before.vias.length, polylines: before.polylines.length},
  saved: save.ok && save.value === true,
  drc: {passed: drc.ok && Array.isArray(drc.value) && drc.value.length === 0,
    count: Array.isArray(drc.value) ? drc.value.length : null, items: drc.value ?? null}, errors};
