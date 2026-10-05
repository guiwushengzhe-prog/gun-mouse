// 仅修改正式自动布线试验副本的独立线宽规则，不改交付工程或其它规则。
// 使用公开接口；保存并回读的通过状态不等于原生布线已遵守规则。
const PROJECT = 'gun-mouse-formal-route';
const POWER_RULE = 'FORMAL_POWER_0_3_MM';
const SIGNAL_RULE = 'FORMAL_SIGNAL_0_15_MM';
const powers = new Set(['GND', '3V3', 'VSYS', 'VBUS', 'VBAT']);
async function guard(requireUnrouted = true) {
  const project = await eda.dmt_Project.getCurrentProjectInfo();
  const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
  const board = project?.data?.find(item => item.itemType === 'Board' && item.pcb?.uuid === current?.uuid);
  if (project?.friendlyName !== PROJECT || !board ||
      (current.parentProjectUuid && current.parentProjectUuid !== project.uuid)) {
    throw new Error('只允许修改 gun-mouse-formal-route 活动电路板试验副本');
  }
  if ((await eda.pcb_PrimitiveComponent.getAll()).length !== 48) throw new Error('正式副本应有48器件');
  if (requireUnrouted) {
    const lines = (await eda.pcb_PrimitiveLine.getAll()).filter(line => [1, 2].includes(line.getState_Layer()));
    const arcs = (await eda.pcb_PrimitiveArc.getAll()).filter(arc => [1, 2].includes(arc.getState_Layer()));
    const polylines = (await eda.pcb_PrimitivePolyline.getAll()).filter(poly => [1, 2].includes(poly.getState_Layer()));
    const vias = await eda.pcb_PrimitiveVia.getAll();
    if (lines.length || arcs.length || polylines.length || vias.length) {
      throw new Error('当前试验副本已有走线或过孔，不能覆盖其布线规则');
    }
  }
  return {project: PROJECT, board: board.pcb.uuid};
}
const identity = await guard();
const configuration = await eda.pcb_Drc.getCurrentRuleConfiguration();
const original = configuration?.config;
const definitions = original?.Physics?.Track;
if (!definitions || typeof definitions !== 'object') throw new Error('公开规则配置未返回 Physics.Track');
if (definitions[POWER_RULE] || definitions[SIGNAL_RULE]) throw new Error('独立试验规则已存在，停止重复覆盖');
const originalNets = await eda.pcb_Drc.getNetRules();
if (!Array.isArray(originalNets) || !originalNets.length) throw new Error('未读取到完整原网络规则，停止写入');
const allNets = (await eda.pcb_Net.getAllNets()).map(item => item.net).filter(Boolean);
const covered = new Set();
function collectNetNames(entries) {
  for (const entry of entries) {
    if (entry.type === 'net' && typeof entry.name === 'string') covered.add(entry.name);
    if (Array.isArray(entry.sub)) collectNetNames(entry.sub);
  }
}
collectNetNames(originalNets);
if (allNets.some(net => !covered.has(net)) || [...powers].some(net => !covered.has(net))) {
  throw new Error('按网络规则未覆盖当前全部网络或五条电源网络，停止写入');
}
const base = Object.values(definitions).find(rule => rule.isSetDefault === true) || Object.values(definitions)[0];
if (!base?.form?.data || !['mm', 'mil'].includes(base.unit)) throw new Error('未知线宽规则格式或单位');
const clone = value => JSON.parse(JSON.stringify(value));
function independentRule(name, nominalMm) {
  const rule = clone(base);
  const scale = base.unit === 'mil' ? 0.0254 : 1;
  rule.editName = name;
  rule.unit = 'mm';
  rule.isSetDefault = false;
  for (const widths of Object.values(rule.form.data)) {
    for (const field of ['minValue', 'defaultValue', 'maxValue']) {
      if (Number.isFinite(widths[field])) widths[field] *= scale;
    }
    if (!Number.isFinite(widths.maxValue) || widths.maxValue < nominalMm) {
      throw new Error('原线宽规则最大值无法容纳试验目标');
    }
    widths.minValue = nominalMm;
    widths.defaultValue = nominalMm;
  }
  const firstLayer = rule.form.data['1'] || Object.values(rule.form.data)[0];
  for (const layer of ['1', '2']) {
    if (!rule.form.data[layer]) rule.form.data[layer] = clone(firstLayer);
  }
  return rule;
}
const updated = clone(original);
updated.Physics.Track[POWER_RULE] = independentRule(POWER_RULE, 0.3);
updated.Physics.Track[SIGNAL_RULE] = independentRule(SIGNAL_RULE, 0.15);
const updatedNets = clone(originalNets);
function assignNetTracks(entries) {
  for (const entry of entries) {
    if (entry.type === 'net') entry.Track = powers.has(entry.name) ? POWER_RULE : SIGNAL_RULE;
    if (Array.isArray(entry.sub)) assignNetTracks(entry.sub);
  }
}
assignNetTracks(updatedNets);
function stable(value) {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort()
    .map(key => JSON.stringify(key) + ':' + stable(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
await guard();
if (await eda.pcb_Drc.overwriteCurrentRuleConfiguration(updated) !== true) throw new Error('写入独立线宽规则失败');
await guard();
if (await eda.pcb_Drc.overwriteNetRules(updatedNets) !== true) throw new Error('写入网络线宽引用失败');
await guard();
const saved = await eda.pcb_Document.save();
if (saved !== true) throw new Error('正式自动布线试验规则保存未返回 true');
const reread = (await eda.pcb_Drc.getCurrentRuleConfiguration())?.config;
const rereadNets = await eda.pcb_Drc.getNetRules();
if (!reread?.Physics?.Track || !Array.isArray(rereadNets)) throw new Error('无法回读试验规则');
const differences = [];
for (const [name, expected] of [[POWER_RULE, 0.3], [SIGNAL_RULE, 0.15]]) {
  const rule = reread.Physics.Track[name];
  if (rule?.unit !== 'mm') differences.push({kind: '规则单位不符', name});
  for (const layer of ['1', '2']) {
    const widths = rule?.form?.data?.[layer];
    if (!widths || !Number.isFinite(widths.minValue) || !Number.isFinite(widths.defaultValue) ||
        Math.abs(widths.minValue - expected) > 0.000001 ||
        Math.abs(widths.defaultValue - expected) > 0.000001) differences.push({kind: '回读线宽不符', name, layer, widths});
  }
}
const remainingConfig = clone(reread);
delete remainingConfig.Physics.Track[POWER_RULE];
delete remainingConfig.Physics.Track[SIGNAL_RULE];
const otherRuleFieldsUnchanged = stable(remainingConfig) === stable(original);
if (!otherRuleFieldsUnchanged) differences.push({kind: '其它规则字段发生变化'});
function restoreOriginalTrackReferences(entries, originals) {
  for (let index = 0; index < entries.length; index++) {
    const entry = entries[index], prior = originals[index];
    if (!prior || entry.type !== prior.type || entry.name !== prior.name) return false;
    if (entry.type === 'net') {
      const target = powers.has(entry.name) ? POWER_RULE : SIGNAL_RULE;
      if (entry.Track !== target) differences.push({kind: '网络引用不符', net: entry.name, expected: target, actual: entry.Track});
      if (Object.prototype.hasOwnProperty.call(prior, 'Track')) entry.Track = prior.Track;
      else delete entry.Track;
    }
    if (Array.isArray(entry.sub) && !restoreOriginalTrackReferences(entry.sub, prior.sub || [])) return false;
  }
  return entries.length === originals.length;
}
const restoredNets = clone(rereadNets);
const netIdentityUnchanged = restoreOriginalTrackReferences(restoredNets, originalNets);
const otherNetFieldsUnchanged = netIdentityUnchanged && stable(restoredNets) === stable(originalNets);
if (!otherNetFieldsUnchanged) differences.push({kind: '其它网络规则字段或网络身份变化'});
return {...identity, scope: '正式自动布线独立试验副本，尚待实际布线验证线宽规则是否被采用',
  saved, readbackPassed: differences.length === 0, differences,
  otherRuleFieldsUnchanged, otherNetFieldsUnchanged, netCount: allNets.length,
  newDefinitions: {[POWER_RULE]: reread.Physics.Track[POWER_RULE], [SIGNAL_RULE]: reread.Physics.Track[SIGNAL_RULE]},
  netRules: rereadNets, preservesGlobalDefaultRule: true,
  requestedWidthsMm: {power: 0.3, signal: 0.15, powerNets: [...powers]},
  warning: '该脚本只设置并回读规则，不证明自动布线连通、工艺间距或已有天线布局已经合格'};
