// 导出隔离测试板的铜层制造数据，返回缓存大小；由调用方分块获取。
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.friendlyName !== 'eda-recovery-probe') throw new Error('只允许实验工程');
const board = project.data.find(x => x.itemType === 'Board');
const current = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (current?.uuid !== board?.pcb?.uuid) throw new Error('当前文档不是实验电路板');
const file = await eda.pcb_ManufactureData.getGerberFile('eda-recovery-test-only');
if (!file) throw new Error('未取得铜层制造数据');
const base64 = await new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(',')[1]);
  reader.onerror = () => reject(new Error('文件缓存读取失败'));
  reader.readAsDataURL(file);
});
globalThis.__gm_blob = base64;
return {name: file.name, size: file.size, b64len: base64.length};
