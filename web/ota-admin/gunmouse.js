import { SERVICE, CONTROL, STATUS, DETAILS, validateStatus, mergeDetails, chargingText, touchThresholds, numberCommand, touchCommands, expectedChange, matches } from './gunmouse-core.mjs?v=20261026-2';

const byId = id => document.getElementById(id);
const bluetooth = navigator.bluetooth;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
let device = null, control = null, statusCharacteristic = null, latest = null;
let detailsCharacteristic = null;
let busy = false, timer = null, io = Promise.resolve();
let savedDevices = [];
const labels = { 'joy 1': '启用摇杆', 'joy 0': '停用摇杆', jcenter: '摇杆取中心', invx: '左右反向', invy: '上下反向', tcal: '重取未触摸基线', cal: '陀螺仪校准' };

function sequential(action) {
  const next = io.then(action);
  io = next.catch(() => {});
  return next;
}

function connected() { return Boolean(device?.gatt?.connected && statusCharacteristic && latest); }

function buttons() {
  byId('controls').disabled = busy || !connected() || latest?.ota !== 0;
  byId('connect').disabled = busy || !bluetooth || connected();
  byId('reconnect').disabled = busy || connected();
  byId('disconnect').disabled = busy || !device?.gatt?.connected;
  byId('refresh-status').disabled = busy || !connected();
}

function connectionMessage(text, error = false) {
  byId('connection-message').textContent = text;
  byId('connection-message').className = error ? 'error' : '';
}

function resultMessage(text, error = false) {
  const message = byId('operation-message');
  message.textContent = text;
  message.className = error ? 'error' : 'success';
  const entry = document.createElement('li');
  entry.textContent = `${new Date().toLocaleTimeString('zh-CN')} · ${text}`;
  byId('operation-log').prepend(entry);
  while (byId('operation-log').children.length > 8) byId('operation-log').lastChild.remove();
}

function clearStatus() {
  clearTimeout(timer);
  timer = null;
  latest = null;
  control = statusCharacteristic = detailsCharacteristic = null;
  document.querySelectorAll('[data-value]').forEach(node => { node.textContent = '—'; });
  byId('updated-at').textContent = '等待设备回报';
  byId('connection-badge').textContent = '未连接';
  byId('connection-badge').className = 'badge';
  byId('touch-press').value = byId('touch-release').value = '';
  buttons();
}

function render(value) {
  latest = value;
  const d = value.diag, thresholds = touchThresholds(d);
  const values = {
    raw: d.raw, base: Math.round(d.base), press: thresholds.press, release: thresholds.release,
    build: `${d.build ?? d.fw} · ${value.slot}`,
    touch: !d.ready ? '基线准备中' : d.touch ? '已触摸' : '未触摸，体感关闭',
    invx: d.invx ? '开启' : '关闭', invy: d.invy ? '开启' : '关闭',
    ratios: `开启 ${(d.tp * 100).toFixed(2)}% / 关闭 ${(d.tr * 100).toFixed(2)}%`,
    cross: d.cross,
    joy: Object.hasOwn(d, 'joy') ? (!d.joy ? '已停用' : d.jok === 0 ? '已启用，中心异常，暂停输出' : '已启用') : '请更新固件以读取摇杆状态',
    'joy-raw': value.details ? (d.joy ? value.details.joy.raw.join(' / ') : '停用，未采样') : '—',
    'joy-center': value.details ? value.details.joy.center.join(' / ') : '—',
    'joy-speed': Number.isFinite(d.jspeed) ? `${d.jspeed} 计数/秒` : '—',
    sensitivity: Number.isFinite(d.sens) ? `${d.sens} 计数/度` : '—',
    imu: Object.hasOwn(d, 'imu_ready') ? (d.imu_ready ? '正常' : '尚未就绪，请放稳等待校准') : '—',
    charge: chargingText(value.details?.power),
    voltage: !value.details || value.details.power.mv < 0 ? '等待采样' : `${(value.details.power.mv / 1000).toFixed(3)} 伏${value.details.power.mv > 4400 ? '（采样偏高，不能作电池实测值）' : ''}`,
  };
  for (const [name, text] of Object.entries(values)) document.querySelector(`[data-value="${name}"]`).textContent = text;
  byId('updated-at').textContent = `刚读取：${new Date().toLocaleTimeString('zh-CN')}`;
  byId('connection-badge').textContent = '蓝牙已连接';
  byId('connection-badge').className = 'badge connected';
  buttons();
}

async function readStatus() {
  if (!device?.gatt?.connected || !statusCharacteristic) throw new Error('飞鼠已断开，请重新连接。');
  const data = await statusCharacteristic.readValue();
  let value;
  try { value = JSON.parse(new TextDecoder().decode(data)); }
  catch { throw new Error('设备状态不完整，请重新连接后刷新。'); }
  validateStatus(value);
  if (detailsCharacteristic) {
    const details = await detailsCharacteristic.readValue();
    mergeDetails(value, JSON.parse(new TextDecoder().decode(details)));
  }
  render(value);
  return value;
}

function disconnect(message = '已断开，设备设置保留。') {
  const previous = device;
  device = null;
  clearStatus();
  if (previous?.gatt?.connected) previous.gatt.disconnect();
  connectionMessage(message);
}

function polling() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    if (!connected()) return;
    if (!busy) {
      try { await sequential(readStatus); }
      catch { disconnect('读取中断，已停止控制并清空旧读数，请重新连接。'); return; }
    }
    if (connected()) polling();
  }, 1000);
}

async function run(action) {
  if (busy) return;
  busy = true;
  buttons();
  try { await action(); }
  catch (error) {
    const messages = {
      NotFoundError: '未找到或未选择飞鼠，设置没有改变。',
      NetworkError: '蓝牙通信失败，请确认飞鼠已开机并完成 Windows 配对，再重新连接。',
      SecurityError: '浏览器没有蓝牙访问权限，请在本站的浏览器权限中允许蓝牙连接。',
      NotAllowedError: '蓝牙连接未获浏览器授权，请重新点击连接并选择飞鼠。',
      NotSupportedError: '此浏览器或蓝牙适配器暂不支持该连接，请使用 Windows 的 Edge 或 Chrome。',
    };
    resultMessage(messages[error.name] ?? error.message, true);
    if (!connected()) connectionMessage('尚未连接设备，请重新选择飞鼠。');
  }
  finally { busy = false; buttons(); }
}

async function connect(selected = null) {
  if (!bluetooth) throw new Error('此浏览器不支持蓝牙网页控制，请使用 Windows 的 Edge 或 Chrome。');
  if (device) disconnect();
  connectionMessage('请选择飞鼠，正在连接…');
  const candidate = selected ?? await bluetooth.requestDevice({ filters: [{ name: 'GunMouse SuperMini' }], optionalServices: [SERVICE] });
  device = candidate;
  candidate.addEventListener('gattserverdisconnected', () => {
    if (device === candidate) disconnect('飞鼠已离线，旧读数已清空，请重新连接。');
  }, { once: true });
  try {
    const server = await candidate.gatt.connect();
    const service = await server.getPrimaryService(SERVICE);
    control = await service.getCharacteristic(CONTROL);
    statusCharacteristic = await service.getCharacteristic(STATUS);
    try { detailsCharacteristic = await service.getCharacteristic(DETAILS); }
    catch (error) { if (error.name !== 'NotFoundError') throw error; detailsCharacteristic = null; }
    await sequential(readStatus);
    byId('touch-press').value = (latest.diag.tp * 100).toFixed(2);
    byId('touch-release').value = (latest.diag.tr * 100).toFixed(2);
    if (Number.isFinite(latest.diag.sens)) byId('sensitivity').value = latest.diag.sens;
    if (Number.isFinite(latest.diag.jspeed)) byId('joy-speed').value = latest.diag.jspeed;
    connectionMessage('已连接飞鼠，状态来自设备实时回报。');
    polling();
    await loadSavedDevices();
  } catch (error) {
    disconnect('连接未完成。请确认飞鼠已开机，并已在 Windows 中配对。');
    throw error;
  }
}

async function loadSavedDevices() {
  if (!bluetooth?.getDevices) return;
  try {
    savedDevices = (await bluetooth.getDevices()).filter(item => item.name === 'GunMouse SuperMini');
    byId('saved-device').replaceChildren();
    savedDevices.forEach((item, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      option.textContent = savedDevices.length === 1 ? '已授权飞鼠' : `已授权飞鼠 ${index + 1}`;
      byId('saved-device').append(option);
    });
    byId('saved-devices').hidden = savedDevices.length === 0;
  } catch { byId('saved-devices').hidden = true; }
}

async function send(command) {
  if (!device?.gatt?.connected || !control) throw new Error('请先连接飞鼠。');
  await control.writeValueWithResponse(new TextEncoder().encode(`CMD ${command}`));
  await pause(150);
  const value = await readStatus();
  if (value.ota !== 0) throw new Error('设备未接受设置，请检查是否正在升级或是否发生通信错误。');
  return value;
}

async function confirm(expected) {
  for (let attempt = 0; attempt < 8; ++attempt) {
    if (matches(latest.diag, expected)) return;
    await pause(150);
    await readStatus();
  }
  throw new Error('命令已送达，但设备回报未符合预期，请刷新核对；未自动重发命令。');
}

async function commandAction(command) {
  await sequential(async () => {
    const before = await readStatus();
    if (before.ota !== 0) throw new Error('设备正在升级或报告通信错误，暂不发送设置。');
    const expected = expectedChange(command, before);
    await send(command);
    if (expected) {
      await confirm(expected);
      const label = labels[command] ?? command.replace('sens ', '体感灵敏度 ').replace('jspeed ', '摇杆速度 ');
      if (command === 'cal') resultMessage('校准命令已由设备确认，请放稳约 3 秒；完成情况见陀螺仪状态。');
      else if (command === 'joy 1' && latest.diag.jok === 0) resultMessage('启用设置已保存，但中心偏离正常范围，摇杆暂不输出，请检查接线后重新取中心。', true);
      else resultMessage(`${label}：已由设备回报确认。`);
    } else if (command === 'tcal') {
      resultMessage('基线重取命令已送达，请保持未触摸约半秒，再查看基线和触摸状态。');
    } else if (command === 'cal') {
      resultMessage('校准命令已送达，请放稳约 3 秒；当前蓝牙状态未回报陀螺仪校准完成标志。');
    } else {
      resultMessage(`${labels[command] ?? command.replace('sens ', '体感灵敏度 ').replace('jspeed ', '摇杆速度 ')}：命令已送达，旧固件尚不能核对结果，请更新状态回报固件。`);
    }
  });
}

byId('connect').addEventListener('click', () => run(() => connect()));
byId('reconnect').addEventListener('click', () => run(() => {
  const selected = savedDevices[Number(byId('saved-device').value)];
  if (!selected) throw new Error('未找到已授权飞鼠，请重新选择设备。');
  return connect(selected);
}));
byId('disconnect').addEventListener('click', () => disconnect());
byId('refresh-status').addEventListener('click', () => run(() => sequential(readStatus)));
document.querySelectorAll('[data-command]').forEach(button => button.addEventListener('click', () => run(() => commandAction(button.dataset.command))));
byId('speed-form').addEventListener('submit', event => {
  event.preventDefault();
  run(() => commandAction(numberCommand('jspeed', byId('joy-speed').valueAsNumber)));
});
byId('sensitivity-form').addEventListener('submit', event => {
  event.preventDefault();
  run(() => commandAction(numberCommand('sens', byId('sensitivity').valueAsNumber)));
});
byId('touch-form').addEventListener('submit', event => {
  event.preventDefault();
  run(() => sequential(async () => {
    const before = await readStatus();
    if (before.ota !== 0) throw new Error('设备正在升级或报告通信错误，暂不发送设置。');
    const press = byId('touch-press').valueAsNumber, release = byId('touch-release').valueAsNumber;
    const commands = touchCommands(press, release, before.diag);
    for (const command of commands) await send(command);
    await confirm({ tp: press / 100, tr: release / 100 });
    resultMessage(`触摸门限已由设备回报确认：开启 ${press.toFixed(2)}%，关闭 ${release.toFixed(2)}%。`);
  }));
});
window.addEventListener('pagehide', () => disconnect());
if (!bluetooth) connectionMessage('此浏览器不支持蓝牙网页控制，请使用 Windows 的 Edge 或 Chrome。', true);
loadSavedDevices();
buttons();
