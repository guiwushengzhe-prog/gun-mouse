export const SERVICE = 'a38b0001-62da-4c13-9f07-908d8b921571';
export const CONTROL = 'a38b0002-62da-4c13-9f07-908d8b921571';
export const STATUS = 'a38b0004-62da-4c13-9f07-908d8b921571';

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
  if (command === 'invx' || command === 'invy') return { [command]: before.diag[command] ? 0 : 1 };
  if (command.startsWith('joy ') && Object.hasOwn(before.diag, 'joy')) return { joy: Number(command.slice(4)) };
  return null;
}

export function matches(diag, expected) {
  return Object.entries(expected).every(([key, value]) => Number.isFinite(diag[key]) && Math.abs(diag[key] - value) < .00001);
}
