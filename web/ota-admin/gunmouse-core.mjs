export const SERVICE = 'a38b0001-62da-4c13-9f07-908d8b921571';
export const CONTROL = 'a38b0002-62da-4c13-9f07-908d8b921571';
export const STATUS = 'a38b0004-62da-4c13-9f07-908d8b921571';
export const DETAILS = 'a38b0005-62da-4c13-9f07-908d8b921571';

export function mergeDetails(value, details) {
  const j = details?.joy;
  if (details?.project !== 'gunmouse' || details.schema !== 1 || !j || !details.power
      || ![j.enabled, j.ready, j.speed, j.rev, j.middle, details.sens, details.imu_ready,
        details.seq, details.power.mv, details.power.charge].every(Number.isFinite)
      || !Array.isArray(j.raw) || !Array.isArray(j.center)
      || j.raw.length !== 2 || j.center.length !== 2 || ![...j.raw, ...j.center].every(Number.isFinite)) {
    throw new Error('设备的摇杆或供电回报不完整，请重新连接后核对。');
  }
  value.details = details;
  Object.assign(value.diag, { joy: j.enabled, jok: j.ready, jspeed: j.speed, jrev: j.rev,
    sens: details.sens, seq: details.seq, imu_ready: details.imu_ready });
  return value;
}

export function chargingText(power) {
  if (!power) return '旧固件未提供供电回报';
  return ({ '-1': '未知（硬件未接入充电反馈）', 0: '未充电', 1: '正在充电', 2: '已充满' })[power.charge] ?? '未知';
}

export function validateStatus(value) {
  if (value?.project !== 'gunmouse' || !value.diag || !Number.isFinite(value.diag.base)
      || !Number.isFinite(value.diag.raw) || !Number.isFinite(value.diag.tp)
      || !Number.isFinite(value.diag.tr) || !Number.isFinite(value.diag.noise)
      || value.diag.tp <= 0 || value.diag.tr <= 0 || value.diag.tr >= value.diag.tp) {
    throw new Error('设备未返回有效的飞鼠状态，请确认选择了正确设备并已完成系统配对。');
  }
  return value;
}

export function touchThresholds(diag) {
  const offset = Math.max(diag.base * diag.tp, diag.noise * 8);
  return { press: Math.round(diag.base + offset), release: Math.round(diag.base + offset * diag.tr / diag.tp) };
}

export function numberCommand(name, value) {
  const ranges = { sens: [0, 1000], jspeed: [0, 20000] };
  const range = ranges[name];
  if (!range || !Number.isFinite(value) || value <= range[0] || value >= range[1]) {
    throw new Error('数值超出飞鼠支持的范围。');
  }
  return `${name} ${value}`;
}

export function touchCommands(press, release, current) {
  if (!Number.isFinite(press) || !Number.isFinite(release) || press <= .1 || press >= 50
      || release <= .05 || release >= press) {
    throw new Error('开启比例应大于关闭比例，两者均须在输入框标明的范围内。');
  }
  const p = `tp ${press.toFixed(2)}`, r = `tr ${release.toFixed(2)}`;
  // 固件每条命令后都会修正不合法门限；降到旧关闭门限以下时先降低关闭值。
  return press <= current.tr * 100 ? [r, p] : [p, r];
}

export function expectedChange(command, before) {
  const acknowledged = values => Object.hasOwn(before.diag, 'seq') ? { ...values, seq: (before.diag.seq + 1) >>> 0 } : values;
  if (command === 'invx' || command === 'invy') return acknowledged({ [command]: before.diag[command] ? 0 : 1 });
  if (command.startsWith('joy ') && Object.hasOwn(before.diag, 'joy')) return acknowledged({ joy: Number(command.slice(4)) });
  for (const [name, key] of [['sens', 'sens'], ['jspeed', 'jspeed']]) {
    if (command.startsWith(name + ' ') && Object.hasOwn(before.diag, key)) return acknowledged({ [key]: Number(command.slice(name.length + 1)) });
  }
  if (command === 'jcenter' && Object.hasOwn(before.diag, 'jrev')) {
    if (!before.diag.joy) throw new Error('摇杆目前停用，请核对接线并启用后再取中心。');
    return acknowledged({ jrev: (before.diag.jrev + 1) >>> 0 });
  }
  if (command === 'cal' && Object.hasOwn(before.diag, 'seq')) return { seq: (before.diag.seq + 1) >>> 0 };
  return null;
}

export function matches(diag, expected) {
  return Object.entries(expected).every(([key, value]) => Number.isFinite(diag[key]) && Math.abs(diag[key] - value) < .00001);
}
