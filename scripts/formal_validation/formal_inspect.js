// 只读检查正式验证副本。调用参数：{config: <config/pcb-shell-v1.json 内容>}。
// 不打开/重开文档，不保存，不修改图元或设计规则。
const allowed = new Set(['gun-mouse-formal-baseline', 'gun-mouse-formal-roundtrip',
  'gun-mouse-formal-route', 'gun-mouse-formal-copper']);
const config = __CLI__.args?.config;
if (!Array.isArray(config?.parts)) throw new Error('必须提供已核实的器件配置 config.parts');
const project = await eda.dmt_Project.getCurrentProjectInfo();
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (!allowed.has(project?.friendlyName)) throw new Error('只允许检查正式验证工程白名单');
const board = project.data?.find(x => x.itemType === 'Board' && x.pcb?.uuid === current?.uuid);
if (!board || (current.parentProjectUuid && current.parentProjectUuid !== project.uuid)) {
  throw new Error('活动文档必须属于当前正式验证工程的电路板');
}
const MIL_MM = 0.0254;
const powerNets = new Set(['GND', '3V3', 'VSYS', 'VBUS', 'VBAT']);
const errors = [];
async function read(stage, action) {
  try { return await action(); }
  catch (error) { errors.push({stage, message: error?.message ?? String(error)}); return null; }
}
const number = value => Math.round(value * 1e6) / 1e6;
const netOf = primitive => primitive.getState_Net() || '';
const components = [];
for (const component of await eda.pcb_PrimitiveComponent.getAll()) {
  const pins = await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(component.getState_PrimitiveId());
  if (!Array.isArray(pins)) throw new Error('无法读取器件焊盘：' + component.getState_Designator());
  components.push({id: component.getState_PrimitiveId(), ref: component.getState_Designator(),
    uniqueId: component.getState_UniqueId(), component: component.getState_Component(),
    footprint: component.getState_Footprint(), layer: component.getState_Layer(),
    x: component.getState_X(), y: component.getState_Y(), rotation: component.getState_Rotation(),
    pins: pins.map(pin => ({id: pin.getState_PrimitiveId(), pin: String(pin.getState_PadNumber()),
      net: netOf(pin), layer: pin.getState_Layer(), x: pin.getState_X(), y: pin.getState_Y()}))});
}
components.sort((a, b) => a.ref.localeCompare(b.ref));
const configured = new Map(config.parts.map(part => [part.ref, part]));
const actual = new Map(components.map(part => [part.ref, part]));
const differences = [];
if (actual.size !== components.length) differences.push({kind: '重复位号'});
for (const part of config.parts) {
  const found = actual.get(part.ref);
  if (!found) { differences.push({kind: '缺少器件', ref: part.ref}); continue; }
  const pins = new Map(found.pins.map(pin => [pin.pin, pin]));
  for (const [pin, net] of Object.entries(part.nets || {})) {
    const foundPin = pins.get(String(pin));
    if (!foundPin || foundPin.net !== net) differences.push({kind: '焊盘网络不符',
      ref: part.ref, pin, expected: net, actual: foundPin?.net ?? null});
  }
  for (const pin of found.pins) {
    if (pin.net && !Object.prototype.hasOwnProperty.call(part.nets || {}, pin.pin)) {
      differences.push({kind: '未配置的已连接焊盘', ref: part.ref, pin: pin.pin, actual: pin.net});
    }
  }
}
for (const component of components) {
  if (!configured.has(component.ref)) differences.push({kind: '额外器件', ref: component.ref});
}
const configuredPinCount = config.parts.reduce((sum, part) => sum + Object.keys(part.nets || {}).length, 0);
const connectedPinCount = components.reduce((sum, part) => sum + part.pins.filter(pin => pin.net).length, 0);
const lines = (await eda.pcb_PrimitiveLine.getAll()).filter(line => [1, 2].includes(line.getState_Layer()))
  .map(line => ({id: line.getState_PrimitiveId(), kind: 'line', net: netOf(line),
    layer: line.getState_Layer(), startX: line.getState_StartX(), startY: line.getState_StartY(),
    endX: line.getState_EndX(), endY: line.getState_EndY(), width: line.getState_LineWidth()}));
const arcsRaw = await read('读取圆弧线', () => eda.pcb_PrimitiveArc.getAll());
const arcs = (arcsRaw || []).filter(arc => [1, 2].includes(arc.getState_Layer()))
  .map(arc => ({id: arc.getState_PrimitiveId(), kind: 'arc', net: netOf(arc),
    layer: arc.getState_Layer(), startX: arc.getState_StartX(), startY: arc.getState_StartY(),
    endX: arc.getState_EndX(), endY: arc.getState_EndY(), angle: arc.getState_ArcAngle(),
    width: arc.getState_LineWidth()}));
const polylines = (await eda.pcb_PrimitivePolyline.getAll()).map(poly => ({
  id: poly.getState_PrimitiveId(), kind: 'polyline', net: netOf(poly), layer: poly.getState_Layer(),
  width: poly.getState_LineWidth(), path: poly.getState_Polygon().getSource()}));
const copperPolylines = polylines.filter(poly => [1, 2].includes(poly.layer));
const vias = (await eda.pcb_PrimitiveVia.getAll()).map(via => ({id: via.getState_PrimitiveId(),
  net: netOf(via), x: via.getState_X(), y: via.getState_Y(),
  diameter: via.getState_Diameter(), holeDiameter: via.getState_HoleDiameter()}));
const antennaCutMm = config.board?.antenna_copper_keepout_x_min;
const antennaZoneInspection = Number.isFinite(antennaCutMm) ? {
  wholeUnitXFromMm: antennaCutMm, pcbULessEqualMm: -antennaCutMm,
  configuredComponentCenters: config.parts.filter(part => Array.isArray(part.xz) && part.xz[0] >= antennaCutMm)
    .map(part => ({ref: part.ref, wholeUnitXmm: part.xz[0], wholeUnitZmm: part.xz[1]})),
  actualComponentCenters: components.filter(part => -part.x * MIL_MM >= antennaCutMm - 0.001)
    .map(part => ({ref: part.ref, wholeUnitXmm: number(-part.x * MIL_MM), wholeUnitZmm: number(part.y * MIL_MM)})),
  actualPadCenters: components.flatMap(part => part.pins.filter(pin => -pin.x * MIL_MM >= antennaCutMm - 0.001)
    .map(pin => ({ref: part.ref, pin: pin.pin, net: pin.net, layer: pin.layer,
      wholeUnitXmm: number(-pin.x * MIL_MM), wholeUnitZmm: number(pin.y * MIL_MM)}))),
  straightTracesReachingZone: lines.filter(line =>
    (-Math.min(line.startX, line.endX) + line.width / 2) * MIL_MM >= antennaCutMm - 0.001)
    .map(line => ({id: line.id, net: line.net, layer: line.layer,
      approximateMaxWholeUnitXmm: number((-Math.min(line.startX, line.endX) + line.width / 2) * MIL_MM)})),
  viasReachingZone: vias.filter(via => (-via.x + via.diameter / 2) * MIL_MM >= antennaCutMm - 0.001)
    .map(via => ({id: via.id, net: via.net, approximateMaxWholeUnitXmm: number((-via.x + via.diameter / 2) * MIL_MM)})),
  scope: '筛查已有器件原点、焊盘中心、直线导线及过孔；未完整计算焊盘边界、圆弧、填铜和所有封装金属外形。新覆铜边界合规不能证明原有铜全部合规。'
} : null;
const widthByNet = new Map();
const belowNominal = [], differentNominal = [], unnamedCopper = [];
for (const trace of [...lines, ...arcs, ...copperPolylines]) {
  if (!trace.net) { unnamedCopper.push(trace.id); continue; }
  const widthMm = number(trace.width * MIL_MM);
  const expectedMm = powerNets.has(trace.net) ? 0.3 : 0.15;
  const state = widthByNet.get(trace.net) || {net: trace.net, expectedMm, count: 0, widthsMm: new Set()};
  state.count++; state.widthsMm.add(widthMm); widthByNet.set(trace.net, state);
  const detail = {id: trace.id, kind: trace.kind, net: trace.net, layer: trace.layer, widthMm, expectedMm};
  if (widthMm < expectedMm - 0.001) belowNominal.push(detail);
  if (Math.abs(widthMm - expectedMm) > 0.001) differentNominal.push(detail);
}
function briefRules(value, path = '', result = [], depth = 0) {
  if (depth > 9 || value == null || typeof value !== 'object') return result;
  for (const [key, item] of Object.entries(value)) {
    const next = path ? path + '.' + key : key;
    if (/^(track|stroWidth|safeSpacing|copperRegion|viaSize|routingCorner|routingEffectPriority|layers|ignoreNets|unit|name|minRadius|defRadius|maxRadius|minInner|defInner|maxInner)$/.test(key)) {
      result.push({path: next, value: item});
    } else if (/^(stroMin|stroDef|stroMax)$/.test(key)) result.push({path: next, value: item});
    else if (typeof item === 'object') briefRules(item, next, result, depth + 1);
  }
  return result;
}
const ruleName = await read('读取当前规则名称', () => eda.pcb_Drc.getCurrentRuleConfigurationName());
const ruleConfiguration = await read('读取当前规则配置', () => eda.pcb_Drc.getCurrentRuleConfiguration());
const netRules = await read('读取按网络规则', () => eda.pcb_Drc.getNetRules());
const nets = await read('读取实际网络', () => eda.pcb_Net.getAllNets());
const poursRaw = await read('读取覆铜区域', () => eda.pcb_PrimitivePour.getAll());
const pouredRaw = await read('读取实际填铜', () => eda.pcb_PrimitivePoured.getAll());
const pours = (poursRaw || []).map(pour => ({id: pour.getState_PrimitiveId(),
  name: pour.getState_PourName(), net: netOf(pour), layer: pour.getState_Layer(),
  path: pour.getState_ComplexPolygon().getSource()}));
const fillRegions = (pouredRaw || []).map(poured => ({id: poured.getState_PrimitiveId(),
  pourId: poured.getState_PourPrimitiveId(), fillCount: poured.getState_PourFills().length}));
const drcItems = await read('运行设计规则检查', () => eda.pcb_Drc.check(true, false, true));
return {project: project.friendlyName, board: board.pcb.uuid, currentDocument: current,
  scope: '正式验证副本只读检查；文件与软件规则通过不代表实物验收',
  units: {primitiveGeometry: 'mil', reportedWidth: 'mm', ruleContext: '保留接口原始单位与数值'},
  counts: {componentCount: components.length, configuredComponentCount: config.parts.length,
    connectedPinCount, configuredPinCount, lineCount: lines.length, arcCount: arcs.length,
    copperPolylineCount: copperPolylines.length, viaCount: vias.length, originalViaCount: 95,
    matchesOriginalViaCount: vias.length === 95, pourCount: pours.length,
    actualFillCount: fillRegions.reduce((sum, region) => sum + region.fillCount, 0)},
  pinComparison: {passed: differences.length === 0 && config.parts.length === 48 && configuredPinCount === 160,
    differences}, components, lines, arcs, copperPolylines, vias,
  boardOutlinePolylines: polylines.filter(poly => poly.layer === 11), nets,
  widthChecks: {minimumPassed: belowNominal.length === 0, exactNominalPassed: differentNominal.length === 0,
    toleranceMm: 0.001, byNet: [...widthByNet.values()].map(state => ({...state,
      widthsMm: [...state.widthsMm].sort((a, b) => a - b)})).sort((a, b) => a.net.localeCompare(b.net)),
    belowNominal, differentNominal, unnamedCopper},
  rules: {name: ruleName, summary: briefRules(ruleConfiguration),
    trackDefinitions: ruleConfiguration?.config?.Physics?.Track ?? null, netRules}, antennaZoneInspection, pours, fillRegions,
  drc: {passed: Array.isArray(drcItems) && drcItems.length === 0,
    count: Array.isArray(drcItems) ? drcItems.length : null, items: drcItems}, errors};
