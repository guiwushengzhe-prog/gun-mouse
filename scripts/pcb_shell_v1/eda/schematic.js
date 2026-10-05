// 按配置网表生成原理图：放置全部器件（位号与 PCB 相同），每个有网络的引脚引出一段带网络名的短导线。
// 用于阅读与网表核对；后台会话里"从原理图导入"不可用，PCB 网络由 build_pcb.py 直接写入。
const a = __CLI__.args;
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (!project || project.friendlyName !== 'gun-mouse-v1') throw new Error('只允许修改 gun-mouse-v1 工程');
const board = project.data.find(x => x.itemType === 'Board');
await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
await new Promise(r => setTimeout(r, 1500));
const oldW = await eda.sch_PrimitiveWire.getAllPrimitiveId();
if (oldW.length) await eda.sch_PrimitiveWire.delete(oldW);
const oldC = await eda.sch_PrimitiveComponent.getAllPrimitiveId();
if (oldC.length) await eda.sch_PrimitiveComponent.delete(oldC);

const cache = {};
const out = [];
for (const p of a.parts) {
  if (!cache[p.lcsc]) cache[p.lcsc] = (await eda.lib_Device.getByLcscIds([p.lcsc]))[0];
  const c = await eda.sch_PrimitiveComponent.create(cache[p.lcsc], p.x, p.y);
  if (!c) throw new Error('原理图器件创建失败 ' + p.ref);
  const id = c.getState_PrimitiveId();
  await eda.sch_PrimitiveComponent.modify(id, {designator: p.ref});
  const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
  let wired = 0;
  for (const q of pins) {
    const net = p.nets[q.getState_PinNumber()];
    if (!net) continue;
    const x = q.getState_X(), y = q.getState_Y(), rot = q.getState_Rotation();
    // API返回的是装配后引脚朝外方向；与库文件中原始PIN的朝向语义不同。
    // 例如R12右侧pin2=(1320,0), rotation=0，应向右引出，不能跨过电阻两端。
    const d = {0: [1, 0], 90: [0, 1], 180: [-1, 0], 270: [0, -1]}[((rot % 360) + 360) % 360];
    if (!d) throw new Error('未知引脚朝向 ' + p.ref + '.' + q.getState_PinNumber() + ': ' + rot);
    const w = await eda.sch_PrimitiveWire.create([x, y, x + d[0] * 20, y + d[1] * 20], net);
    if (!w) throw new Error('导线创建失败 ' + p.ref + '.' + q.getState_PinNumber());
    wired++;
  }
  out.push([p.ref, wired]);
}
await eda.sch_Document.save();
return {parts: out.length, wired: out.reduce((s, x) => s + x[1], 0)};
