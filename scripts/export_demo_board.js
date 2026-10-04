// 三维交换文件直接返回给调用程序，由调用程序写入项目目录。
const file = await eda.pcb_ManufactureData.get3DFile('toolchain-demo-board', 'step', [], 'Parts', false);
if (!file || file.size === 0) throw new Error('未取得三维板文件');
const base64 = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('读取三维板文件失败'));
    reader.readAsDataURL(file);
});
return {name: file.name, size: file.size, base64};
