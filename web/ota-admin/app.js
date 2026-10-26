'use strict';

const products = [
  { id: 'gyro', reportProduct: 'esp32s3-gyro-dev', base: '/ota-admin/firmware/esp32s3-gyro-dev/', legacyJsonBase: '/motioncontrol-ota/esp32s3-gyro-dev/', readJson: true },
  { id: 'mic', reportProduct: 'esp32s3-pcmode-wifi-mic', base: '/ota-admin/firmware/esp32s3-pcmode-wifi-mic/', readJson: false },
];

const field = (product, name) => document.querySelector('[data-product="' + product.id + '"] [data-field="' + name + '"]');
let lastDeviceStatus = null;
let deviceStatusStale = false;
let readingDeviceStatus = false;
let activeTouchDebugDevice = sessionStorage.getItem('touchDebugDevice') || null;
let readingTouchDebug = false;
const touchDebugSnapshots = new Map();
const consoleDrafts = new Map();
const consoleMessages = new Map();
const consoleLastCommands = new Map();
const sendingCommands = new Set();
const consoleCommands = [
  ['查看状态', 'status'], ['行走模式', 'mode wasd'], ['视角模式', 'mode mouse'],
  ['陀螺仪校准', 'gyro calibrate'], ['摇杆校准', 'joystick calibrate'],
  ['检查更新', 'update'], ['触摸灯开启', 'led on'], ['触摸灯关闭', 'led off'],
];

function normalizeConsoleCommand(text) {
  const value = text.trim().replace(/\s+/g, ' ').toLowerCase();
  const serialAliases = { p: 'status', c: 'gyro calibrate', n: 'joystick calibrate', u: 'update' };
  if (Object.hasOwn(serialAliases, value)) return serialAliases[value];
  const match = consoleCommands.find(([label, command]) => value === label || value === command);
  return match ? match[1] : null;
}

function consoleCommandLabel(command) {
  const match = consoleCommands.find(([, value]) => value === command);
  return match ? match[0] : String(command || '未知命令');
}

function clearRelease(product) {
  product.releaseVersion = null;
  field(product, 'download').hidden = true;
  for (const name of ['version', 'size', 'sha256']) field(product, name).textContent = '—';
}

async function readRelease(product) {
  clearRelease(product);
  const response = await fetch(product.base + 'latest.txt', { cache: 'no-store', credentials: 'same-origin' });
  if (response.status === 404) {
    field(product, 'state').textContent = '待发布：服务器暂未提供此设备的固件。';
    return;
  }
  if (response.status === 401) throw new Error('主站登录已失效，请返回首页重新登录');
  if (!response.ok) throw new Error('读取发布信息失败');
  const parts = (await response.text()).trim().split(/\r?\n/).map(value => value.trim());
  const [version, digest, rawSize] = parts;
  if (parts.length !== 3 || !/^\d+$/.test(version || '') || !/^[a-fA-F0-9]{64}$/.test(digest || '') || !/^\d+$/.test(rawSize || '')) {
    throw new Error('发布信息格式不完整');
  }
  const size = Number(rawSize);
  if (!Number.isSafeInteger(size) || size < 1 || !Number.isSafeInteger(Number(version)) || Number(version) < 1) {
    throw new Error('发布信息数值异常');
  }
  const firmwareUrl = product.base + 'firmware-' + version + '.bin';
  const fileResponse = await fetch(firmwareUrl, { method: 'HEAD', cache: 'no-store', credentials: 'same-origin' });
  if (!fileResponse.ok) throw new Error('已发布固件文件暂时无法访问');
  const fileSize = fileResponse.headers.get('content-length');
  if (fileSize !== null && Number(fileSize) !== size) throw new Error('固件大小与发布信息不符');
  field(product, 'version').textContent = '第 ' + version + ' 版';
  field(product, 'size').textContent = (size / 1024 / 1024).toFixed(2) + ' MB（' + size.toLocaleString('zh-CN') + ' 字节）';
  field(product, 'sha256').textContent = digest;
  product.releaseVersion = Number(version);
  field(product, 'state').textContent = '服务器已发布第 ' + version + ' 版固件；设备安装情况见下方汇报。';
  field(product, 'download').href = firmwareUrl;
  field(product, 'download').hidden = false;
  if (lastDeviceStatus) renderDeviceStatus(lastDeviceStatus, deviceStatusStale);
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function timestamp(seconds) {
  return Number.isSafeInteger(seconds) && seconds > 0
    ? new Date(seconds * 1000).toLocaleString('zh-CN', { hour12: false })
    : '—';
}

function upgradeResult(record, confirmed = false) {
  if (!record) return confirmed ? '尚无升级记录，当前版本已由设备启动确认。' : '尚无升级记录，等待设备启动确认。';
  switch (record.state) {
    case 'success': return '第 ' + record.target_version + ' 版升级成功（重启后已确认）';
    case 'pending': return '第 ' + record.target_version + ' 版安装中，等待重启后确认';
    case 'unconfirmed': return '第 ' + record.target_version + ' 版未收到确认';
    case 'failed': {
      const reasons = {
        partition_unavailable: '无可用升级分区或容量不足',
        firmware_metadata_unavailable: '无法取得固件信息',
        firmware_size_mismatch: '固件大小不匹配',
        hash_mismatch: '文件校验不通过',
        invalid_firmware: '固件格式或闪存配置不匹配',
        download_or_write_failed: '下载或写入失败',
        firmware_open_failed: '无法开始固件下载',
      };
      return '第 ' + record.target_version + ' 版安装失败，保留原版本'
        + (Object.hasOwn(reasons, record.error_code) ? '（' + reasons[record.error_code] + '）' : '');
    }
    default: return '升级结果暂时无法读取';
  }
}

function devicePhase(device) {
  switch (device.phase) {
    case 'started': return '程序已启动，等待外设就绪';
    case 'ready': return '启动完成，设备已就绪';
    case 'heartbeat': return '运行状态已汇报';
    case 'waiting': return '等待设备空闲' + (Number.isSafeInteger(device.target_version) ? '，准备升级到第 ' + device.target_version + ' 版' : '');
    case 'installing': return '开始安装新版';
    case 'failed': return '安装失败，继续运行原版本';
    default: return '已收到设备汇报';
  }
}

function resetReason(code) {
  if (code === undefined) return '固件尚未提供';
  const reasons = ['未知', '上电启动', '外部复位', '程序主动重启', '程序异常',
    '中断监控触发重启', '任务监控触发重启', '其他运行监控触发重启', '深度休眠唤醒',
    '供电电压过低', '外设复位', '有线接口复位', '调试接口复位', '芯片熔丝异常',
    '供电瞬时异常', '处理器锁死'];
  return (reasons[code] || '未知') + '（代码 ' + code + '）';
}

function wifiDisconnectReason(count, code) {
  if (count === 0) return '本次运行未记录断开';
  if (count === undefined && code === undefined) return '固件尚未提供';
  const reasons = { 200: '热点信号等待超时', 201: '未找到热点', 202: '热点认证失败',
    203: '热点关联失败', 204: '连接握手超时', 205: '连接失败' };
  const reason = code === undefined ? '未提供原因' : (reasons[code] || '未识别的断开原因') + '（代码 ' + code + '）';
  return (count === undefined ? '' : '本次运行 ' + count + ' 次；最近：') + reason;
}

function validateDeviceStatus(data) {
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  if (!data || !integer(data.server_time) || !Array.isArray(data.devices)) throw new Error('设备汇报格式异常');
  for (const device of data.devices.filter(item => item && products.some(product => item.product === product.reportProduct))) {
    if (!/^[a-f\d]{12}$/i.test(device.device_id || '') || !integer(device.version) || !integer(device.last_seen)
      || typeof device.online !== 'boolean' || typeof device.phase !== 'string' || !Array.isArray(device.history)
      || (device.current_version_confirmed !== undefined && typeof device.current_version_confirmed !== 'boolean')) {
      throw new Error('设备汇报格式异常');
    }
    for (const [name, limit] of [['reset_reason', 32], ['wifi_disconnects', 0xFFFFFFFF], ['wifi_reason', 255]]) {
      if (device[name] !== undefined && (!integer(device[name]) || device[name] > limit)) throw new Error('设备运行状态格式异常');
    }
    if (device.ble_connected !== undefined && typeof device.ble_connected !== 'boolean') throw new Error('设备运行状态格式异常');
    for (const record of device.history.slice(0, 10)) {
      if (!record || !['pending', 'success', 'failed', 'unconfirmed'].includes(record.state)
        || !integer(record.from_version) || !integer(record.target_version) || !integer(record.started_at)
        || (record.completed_at !== undefined && !integer(record.completed_at))) throw new Error('升级记录格式异常');
    }
  }
  return data;
}

function renderDeviceStatus(data, stale) {
  for (const product of products) renderProductDevices(product, data, stale);
}

function renderProductDevices(product, data, stale) {
  const container = field(product, 'devices');
  const expandedDevices = new Set(Array.from(container.querySelectorAll('details[open]')).map(node => node.dataset.deviceId));
  const devices = data.devices.filter(device => device && device.product === product.reportProduct);
  container.replaceChildren();
  for (const device of devices) {
    const card = element('article', undefined, 'device-card');
    card.append(element('h4', '设备 ' + device.device_id.toUpperCase()));
    const values = element('dl');
    let version = '第 ' + device.version + ' 版（设备汇报）';
    if (device.version === product.releaseVersion) version += '，与发布版本一致';
    if (device.current_version_confirmed !== true) version += '，尚未收到启动确认';
    for (const [label, value] of [
      ['当前固件', version],
      ['在线状态', stale ? '状态未刷新，请等待重新读取' : device.online ? '在线（最近 5 分钟内有汇报）' : '离线（超过 5 分钟未汇报）'],
      ['最近汇报', timestamp(device.last_seen)],
      ['汇报阶段', devicePhase(device)],
      ...(product.id === 'gyro' ? [
        ['本次启动原因', resetReason(device.reset_reason)],
        ['无线网络断开', wifiDisconnectReason(device.wifi_disconnects, device.wifi_reason)],
        ['最近汇报时蓝牙', device.ble_connected === undefined ? '固件尚未提供' : device.ble_connected ? '已连接' : '未连接'],
      ] : []),
      ['升级结果', upgradeResult(device.history[0], device.current_version_confirmed === true)],
    ]) {
      const row = element('div');
      row.append(element('dt', label), element('dd', value));
      values.append(row);
    }
    card.append(values);
    if (product.id === 'gyro') {
      const debug = element('section', undefined, 'touch-debug');
      debug.dataset.touchDebugDevice = device.device_id;
      debug.append(element('h5', '无线控制台'));
      const button = element('button', activeTouchDebugDevice === device.device_id ? '停止诊断' : '开启5分钟诊断', 'button secondary');
      button.type = 'button';
      button.addEventListener('click', () => setTouchDebug(device.device_id, activeTouchDebugDevice !== device.device_id));
      const state = element('p', activeTouchDebugDevice === device.device_id ? '正在读取诊断状态…' : '未开启', 'touch-debug-state');
      const output = element('div', undefined, 'touch-debug-output');
      debug.append(button, state, output);
      debug.append(createWirelessConsole(device, stale));
      card.append(debug);
      const snapshot = touchDebugSnapshots.get(device.device_id);
      if (snapshot) renderTouchDebug(debug, snapshot);
    }
    if (device.history.length) {
      const details = element('details');
      details.dataset.deviceId = device.device_id;
      details.open = expandedDevices.has(device.device_id);
      details.append(element('summary', '最近升级记录（最多 10 次）'));
      const scroll = element('div', undefined, 'history-scroll');
      const table = element('table', undefined, 'upgrade-history');
      table.append(element('caption', '设备 ' + device.device_id.toUpperCase() + ' 的升级记录'));
      const head = element('thead');
      const headings = element('tr');
      for (const name of ['升级版本', '结果', '开始时间', '结果时间']) {
        const cell = element('th', name);
        cell.scope = 'col';
        headings.append(cell);
      }
      head.append(headings);
      const body = element('tbody');
      for (const record of device.history.slice(0, 10)) {
        const row = element('tr');
        row.className = 'upgrade-' + record.state;
        for (const value of ['第 ' + record.from_version + ' 版 → 第 ' + record.target_version + ' 版', upgradeResult(record), timestamp(record.started_at), timestamp(record.completed_at)]) {
          row.append(element('td', value));
        }
        body.append(row);
      }
      table.append(head, body);
      scroll.append(table);
      details.append(scroll);
      card.append(details);
    }
    container.append(card);
  }
  if (!stale) field(product, 'feedback-state').textContent = devices.length
    ? '每 15 秒自动刷新。最近读取：' + timestamp(data.server_time) + '。离线不会改变已确认的历史升级结果。'
    : '尚未收到设备汇报。设备升级到支持反馈的固件并联网后，会自动在这里显示。';
}

function createWirelessConsole(device, stale) {
  const consolePanel = element('section', undefined, 'wireless-console');
  const supported = device.version >= 19;
  const note = element('p', supported
    ? '输入下方命令可读取状态、切换模式或校准。点击快捷命令填入，再点发送。'
    : '当前设备汇报第 ' + device.version + ' 版；第19版起支持命令，旧版可继续读取诊断数据。', 'note');
  const form = element('form', undefined, 'console-form');
  const label = element('label', '命令');
  const input = element('input');
  input.type = 'text';
  input.id = 'console-command-' + device.device_id;
  label.htmlFor = input.id;
  input.placeholder = '例如：行走模式 或 mode wasd';
  input.autocomplete = 'off';
  input.maxLength = 64;
  input.value = consoleDrafts.get(device.device_id) || '';
  input.disabled = !supported;
  input.addEventListener('input', () => consoleDrafts.set(device.device_id, input.value));
  const send = element('button', sendingCommands.has(device.device_id) ? '发送中…' : '发送命令', 'button');
  send.type = 'submit';
  send.disabled = !supported || sendingCommands.has(device.device_id);
  form.append(label, input, send);
  form.addEventListener('submit', event => {
    event.preventDefault();
    sendConsoleCommand(device.device_id, input.value);
  });
  const shortcuts = element('div', undefined, 'console-shortcuts');
  for (const [name, command] of consoleCommands) {
    const shortcut = element('button', name, 'button secondary');
    shortcut.type = 'button';
    shortcut.disabled = !supported;
    shortcut.title = command;
    shortcut.addEventListener('click', () => {
      input.value = name;
      consoleDrafts.set(device.device_id, name);
      input.focus();
    });
    shortcuts.append(shortcut);
  }
  const message = element('p', consoleMessages.get(device.device_id) || (supported && !stale && !device.online
    ? '设备最近汇报显示离线。命令发送后会等待设备联网，过期未执行会明确显示。' : ''), 'console-state');
  message.setAttribute('role', 'status');
  const results = element('div', undefined, 'console-results');
  consolePanel.append(note, form, shortcuts,
    element('p', '校准时请将设备放稳、松开摇杆。也可输入原串口指令：p 查看状态、c 陀螺仪校准、n 摇杆校准、u 检查更新。仅支持列出的设备命令。排队成功表示网站已接收，只有开发板回复后才显示执行结果。', 'note'), message, results);
  return consolePanel;
}

function renderConsoleResults(panel, data) {
  const output = panel.querySelector('.console-results');
  if (!output) return;
  output.replaceChildren();
  const pending = Array.isArray(data.pending) ? data.pending : [];
  const results = Array.isArray(data.results) ? data.results : [];
  if (!pending.length && !results.length) return;
  output.append(element('h5', '命令记录（仅保留本次网站服务期间的最近结果）'));
  const list = element('ul', undefined, 'console-log');
  for (const item of pending) {
    const remaining = Number.isSafeInteger(item.expires_at) && Number.isSafeInteger(data.server_time)
      ? Math.max(0, item.expires_at - data.server_time) : null;
    list.append(element('li', consoleCommandLabel(item.command) + '：已排队，等待开发板执行'
      + (data.online === false ? '（设备离线，等待联网）' : '')
      + (remaining === null ? '' : '，' + remaining + ' 秒后过期') + ' · ' + timestamp(item.created_at), 'console-pending'));
  }
  for (const item of results.slice(-20).reverse()) {
    const state = item.state === 'expired' ? '已过期，未收到执行确认'
      : item.state === 'device_changed' ? '设备已重启或版本已变化，未收到执行确认'
        : item.ok === true ? '执行成功' : '执行失败';
    list.append(element('li', consoleCommandLabel(item.command) + '：' + state
      + (item.message ? '（' + item.message + '）' : '') + ' · ' + timestamp(item.completed_at || item.server_time),
    item.ok === true && item.state === 'completed' ? 'console-completed' : 'console-failed'));
    if (item.id === consoleLastCommands.get(panel.dataset.touchDebugDevice)) {
      const message = consoleCommandLabel(item.command) + '：' + state + (item.message ? '（' + item.message + '）' : '');
      consoleMessages.set(panel.dataset.touchDebugDevice, message);
      panel.querySelector('.console-state').textContent = message;
    }
  }
  output.append(list);
}

async function sendConsoleCommand(deviceId, text) {
  if (sendingCommands.has(deviceId)) return;
  const panel = document.querySelector('[data-touch-debug-device="' + deviceId + '"]');
  const state = panel && panel.querySelector('.console-state');
  const command = normalizeConsoleCommand(text);
  if (!command) {
    const message = '请选择下方快捷命令，或输入其对应命令。暂不支持其他指令。';
    consoleMessages.set(deviceId, message);
    if (state) state.textContent = message;
    return;
  }
  sendingCommands.add(deviceId);
  const send = panel && panel.querySelector('.console-form button');
  if (send) { send.disabled = true; send.textContent = '发送中…'; }
  try {
    const response = await fetch('/ota-admin/api/touch-debug/command', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId, command }),
    });
    if (response.status === 401) throw new Error('主站登录已失效，请重新登录');
    const data = await response.json();
    if (!response.ok || data.queued !== true) {
      const reasons = {
        firmware_too_old: '设备需升级到第19版后才能执行命令',
        unknown_device: '网站尚未收到这台设备的汇报',
        command_queue_full: '等待执行的命令过多，请等现有命令完成后再发送',
        invalid_command: '命令不支持，请使用下方快捷命令',
      };
      throw new Error(reasons[data.error] || '命令未排队，请稍后重试');
    }
    consoleMessages.set(deviceId, (data.duplicate ? '相同命令已在队列中' : '命令已排队')
      + (data.online === false ? '，等待设备恢复联网。' : '，等待开发板回复。') + '诊断已开启5分钟。');
    if (data.command && data.command.id) consoleLastCommands.set(deviceId, data.command.id);
    activeTouchDebugDevice = deviceId;
    sessionStorage.setItem('touchDebugDevice', deviceId);
    await readTouchDebug();
  } catch (error) {
    consoleMessages.set(deviceId, error.message);
  } finally {
    sendingCommands.delete(deviceId);
    const updatedPanel = document.querySelector('[data-touch-debug-device="' + deviceId + '"]');
    if (updatedPanel) {
      updatedPanel.querySelector('.console-state').textContent = consoleMessages.get(deviceId) || '';
      const button = updatedPanel.querySelector('.console-form button');
      button.disabled = false;
      button.textContent = '发送命令';
    }
  }
}

function renderTouchDebug(panel, data) {
  const state = panel.querySelector('.touch-debug-state');
  const output = panel.querySelector('.touch-debug-output');
  const button = panel.querySelector('button');
  renderConsoleResults(panel, data);
  button.textContent = data.enabled ? '停止诊断' : '开启5分钟诊断';
  if (!data.enabled && !data.samples.length) {
    state.textContent = '诊断未开启或已结束。';
    output.replaceChildren();
    return;
  }
  if (data.enabled) {
    const remaining = Math.max(0, data.expires_at - data.server_time);
    state.textContent = '采集中：每秒1条，约 ' + Math.ceil(remaining / 60) + ' 分钟后自动停止。';
  } else {
    state.textContent = '诊断已停止，下面保留最近收到的读数。';
  }
  output.replaceChildren();
  const samples = data.samples.slice(-20).reverse();
  if (!samples.length) {
    output.append(element('p', '等待开发板发来第一条读数…', 'note'));
    return;
  }
  const latest = samples[0];
  if (latest.input) {
    const input = latest.input;
    const value = (name, unit = '') => input[name] === undefined ? '—' : String(input[name]) + unit;
    const flag = (name, yes, no) => input[name] === undefined ? '—' : input[name] ? yes : no;
    const statusNames = ['确认发送成功', '通知已提交', '确认未启用', '通知未启用',
      '属性通信错误', '没有客户端', '客户端未订阅', '确认超时', '确认失败', '尚无有效反馈', '尚无有效反馈'];
    const keys = input.keys === undefined ? '—' : [
      [1, 'W'], [2, 'A'], [4, 'S'], [8, 'D'],
    ].filter(([mask]) => input.keys & mask).map(([, name]) => name).join(' + ') || '无';
    const saved = input.mode_attempts === 0 ? '尚未请求切换' : flag('mode_saved', '最近保存成功', '最近保存未成功');
    const gyro = input.gyro_initialized === undefined ? '—' : !input.gyro_initialized
      ? '传感器未就绪' : flag('gyro_ready', '陀螺仪已就绪', '陀螺仪校准中');
    const gyroReasons = ['采集中／已就绪', '重力值偏离静止范围', '角速率过高', '加速度变化',
      '噪声过大', '采样间隔过长', '传感器读数断流', '传感器初始化失败'];
    const authentication = input.ble_auth_status === undefined || input.ble_auth_status === -1
      ? '尚未反馈' : input.ble_auth_status === 0 ? '认证成功' : '认证失败（代码 ' + input.ble_auth_status + '）';
    output.append(element('h5', '最新输入快照 · ' + timestamp(latest.server_time)));
    const details = element('dl');
    for (const [label, text] of [
      ['摇杆模式', flag('wasd', '行走方向键（W、A、S、D）', '视角鼠标') + ' · ' + flag('available', '摇杆已启用', '摇杆未启用')],
      ['原始与中心', 'X：' + value('raw_x') + ' / ' + value('center_x') + '；Y：' + value('raw_y') + ' / ' + value('center_y')],
      ['实际偏移', 'X：' + value('x_percent', '%') + '；Y：' + value('y_percent', '%') + '；方向触发门槛：绝对偏移大于 30%'],
      ['摇杆按下', flag('button', '已按下', '已松开') + '；本次持续：' + value('hold_ms', ' 毫秒') + '；过去最长：' + value('longest_hold_ms', ' 毫秒')],
      ['模式切换', '尝试：' + value('mode_attempts') + ' 次；' + saved],
      ['生成方向键', keys + (input.keys === undefined ? '' : '（掩码 ' + input.keys + '）')],
      ['键盘发送', '尝试：' + value('keyboard_attempts') + '；成功：' + value('keyboard_sent') + '；反馈：' + (statusNames[input.keyboard_status] || '—')],
      ...(input.mouse_buttons === undefined ? [] : [
        ['鼠标按键', [[1, '左键'], [2, '右键'], [4, '中键']].filter(([mask]) => input.mouse_buttons & mask).map(([, name]) => name).join(' + ') || '无'],
        ['鼠标发送', '尝试：' + value('mouse_attempts') + '；成功：' + value('mouse_sent') + '；反馈：' + (statusNames[input.mouse_status] || '—')],
        ['蓝牙输入订阅', '鼠标：' + flag('mouse_subscribed', '已订阅', '未订阅') + '；键盘：' + flag('keyboard_subscribed', '已订阅', '未订阅')],
        ['输入与铜箔触摸离合', flag('input_paused', '输入已暂停', '输入正常运行') + '；' + flag('clutch', '已激活，允许陀螺仪鼠标', '未激活')],
        ['蓝牙连接间隔', value('ble_interval_us', ' 微秒')],
        ['剩余内存', '当前：' + value('heap_free', ' 字节') + '；运行最低：' + value('heap_min', ' 字节')],
      ]),
      ...(input.reset_reason === undefined ? [] : [['本次启动原因', resetReason(input.reset_reason)]]),
      ...(input.wifi_disconnects === undefined ? [] : [['无线网络断开', wifiDisconnectReason(input.wifi_disconnects, input.wifi_reason)]]),
      ['连接与陀螺仪', flag('connected', '蓝牙已连接', '蓝牙未连接') + '；' + gyro],
      ...(input.ble_auth_status === undefined && input.ble_encrypted === undefined ? [] : [
        ['蓝牙认证与加密', authentication + '；' + flag('ble_encrypted', '加密已启用', '加密未启用')],
      ]),
      ...(input.gyro_samples === undefined ? [] : [
        ['校准进度与原因', '有效样本：' + value('gyro_samples') + '；重置：' + value('gyro_resets')
          + ' 次；最近原因：' + (gyroReasons[input.gyro_reset_reason] || '—')],
        ['陀螺仪测量', '重力值：' + value('gyro_accel_mg', ' 毫重力（1/1000 重力）')
          + '；角速率：' + value('gyro_rate_mdps', ' 毫度/秒') + '；采样间隔：' + value('gyro_gap_us', ' 微秒')],
      ]),
    ]) {
      const row = element('div');
      row.append(element('dt', label), element('dd', text));
      details.append(row);
    }
    output.append(details, element('p', '通知已提交表示蓝牙发送流程已接受，不代表游戏已经收到。快照每秒更新一次，最长按住时间可查看两次采样之间的短操作。', 'note'));
  } else {
    output.append(element('p', '这条样本只提供触摸读数；升级到支持输入诊断的固件后，可查看摇杆偏移、模式和发送状态。', 'note'));
  }
  const table = element('table', undefined, 'touch-debug-values');
  const head = element('thead');
  const headings = element('tr');
  for (const name of ['时间', '原始值', '滤波值', '基线', '噪声', '触发增量', '状态']) {
    const cell = element('th', name);
    cell.scope = 'col';
    headings.append(cell);
  }
  head.append(headings);
  const body = element('tbody');
  for (const sample of samples) {
    const row = element('tr');
    const values = [
      new Date(sample.server_time * 1000).toLocaleTimeString('zh-CN', { hour12: false }),
      sample.raw, sample.filtered, sample.baseline, sample.noise, sample.press_threshold,
      sample.touched ? '触碰' : sample.ready ? '未触碰' : '基线采集中',
    ];
    values.forEach((value, index) => {
      const cell = element('td', String(value));
      if (index === 6 && sample.touched) cell.className = 'touch-state-on';
      row.append(cell);
    });
    body.append(row);
  }
  table.append(head, body);
  output.append(table);
}

async function setTouchDebug(deviceId, enabled) {
  const panel = document.querySelector('[data-touch-debug-device="' + deviceId + '"]');
  const button = panel.querySelector('button');
  const state = panel.querySelector('.touch-debug-state');
  button.disabled = true;
  try {
    if (enabled && activeTouchDebugDevice && activeTouchDebugDevice !== deviceId) {
      const previous = await fetch('/ota-admin/api/touch-debug/session', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: activeTouchDebugDevice, enabled: false }),
      });
      if (!previous.ok) throw new Error('无法停止上一台设备的诊断');
      touchDebugSnapshots.set(activeTouchDebugDevice, await previous.json());
    }
    const response = await fetch('/ota-admin/api/touch-debug/session', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId, enabled }),
    });
    if (response.status === 401) throw new Error('主站登录已失效，请重新登录');
    if (!response.ok) throw new Error('网站暂时无法开启触摸诊断');
    const session = await response.json();
    activeTouchDebugDevice = session.enabled ? deviceId : null;
    if (activeTouchDebugDevice) sessionStorage.setItem('touchDebugDevice', deviceId);
    else sessionStorage.removeItem('touchDebugDevice');
    touchDebugSnapshots.set(deviceId, session);
    renderDeviceStatus(lastDeviceStatus, deviceStatusStale);
    if (session.enabled) await readTouchDebug();
  } catch (error) {
    state.textContent = error.message;
  } finally {
    const updatedPanel = document.querySelector('[data-touch-debug-device="' + deviceId + '"]');
    if (updatedPanel) updatedPanel.querySelector('button').disabled = false;
  }
}

async function readTouchDebug() {
  if (readingTouchDebug || !activeTouchDebugDevice) return;
  readingTouchDebug = true;
  const deviceId = activeTouchDebugDevice;
  try {
    const response = await fetch('/ota-admin/api/touch-debug/samples?device_id=' + encodeURIComponent(deviceId), {
      cache: 'no-store', credentials: 'same-origin',
    });
    if (response.status === 401) throw new Error('主站登录已失效，请重新登录');
    if (!response.ok) throw new Error('暂时无法读取触摸诊断');
    const data = await response.json();
    touchDebugSnapshots.set(deviceId, data);
    if (!data.enabled) {
      activeTouchDebugDevice = null;
      sessionStorage.removeItem('touchDebugDevice');
    }
    const panel = document.querySelector('[data-touch-debug-device="' + deviceId + '"]');
    if (panel) renderTouchDebug(panel, data);
  } catch (error) {
    const panel = document.querySelector('[data-touch-debug-device="' + deviceId + '"]');
    const state = panel && panel.querySelector('.touch-debug-state');
    if (state) state.textContent = error.message;
  } finally {
    readingTouchDebug = false;
  }
}

async function readDeviceStatus() {
  if (readingDeviceStatus) return;
  readingDeviceStatus = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch('/ota-admin/api/status', { cache: 'no-store', credentials: 'same-origin', signal: controller.signal });
    if (response.status === 401) throw new Error('主站登录已失效，请返回首页重新登录');
    if (!response.ok) throw new Error('暂时无法读取设备汇报');
    const status = validateDeviceStatus(await response.json());
    lastDeviceStatus = status;
    deviceStatusStale = false;
    renderDeviceStatus(status, false);
  } catch (error) {
    deviceStatusStale = true;
    if (lastDeviceStatus) renderDeviceStatus(lastDeviceStatus, true);
    for (const product of products) {
      field(product, 'feedback-state').textContent = (error.message === '主站登录已失效，请返回首页重新登录'
        ? error.message : '暂时无法读取设备汇报，将自动重试')
        + (lastDeviceStatus ? '。以下保留上次读取的数据（' + timestamp(lastDeviceStatus.server_time) + '），当前在线状态未确认。' : '。当前设备状态尚未确认。');
    }
  } finally {
    clearTimeout(timeout);
    readingDeviceStatus = false;
  }
}

async function readJsonState(product) {
  if (!product.readJson) return;
  try {
    const response = await fetch(product.legacyJsonBase + 'latest.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('扩展发布信息暂时无法读取');
    const metadata = await response.json();
    field(product, 'json-state').textContent = metadata.enabled === true
      ? '旧版扩展发布信息已启用，版本：' + String(metadata.version || metadata.versionCode || '未标注') + '。'
      : '旧版扩展发布信息尚未启用；新版使用上方的登录保护更新入口。';
  } catch {
    field(product, 'json-state').textContent = '本次未能读取扩展发布信息；文本发布信息与固件下载仍单独提供。';
  }
}

async function refresh() {
  const button = document.getElementById('refresh');
  button.disabled = true;
  try {
    await Promise.all([readDeviceStatus(), ...products.map(async product => {
      field(product, 'state').textContent = '正在核对已发布固件…';
      await Promise.all([
        readRelease(product).catch(error => {
          clearRelease(product);
          field(product, 'state').textContent = error.message + '，请稍后刷新。';
        }),
        readJsonState(product),
      ]);
    })]);
  } finally { button.disabled = false; }
}

document.getElementById('refresh').addEventListener('click', refresh);
refresh();
setInterval(readDeviceStatus, 15000);
setInterval(readTouchDebug, 1000);
