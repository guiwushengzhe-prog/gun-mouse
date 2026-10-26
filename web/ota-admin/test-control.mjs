import assert from 'node:assert/strict';
import { validateStatus, mergeDetails, chargingText, touchThresholds, numberCommand, touchCommands, expectedChange, matches } from './gunmouse-core.mjs';

const status = { project: 'gunmouse', ota: 0, diag: { base: 32739.2, raw: 32719, tp: .08, tr: .05, noise: 851, invx: 0, invy: 1 } };
assert.equal(validateStatus(status), status);
assert.throws(() => validateStatus({ ...status, project: 'esp32s3-gyro-dev' }));
assert.throws(() => validateStatus({ ...status, diag: { ...status.diag, tp: null } }));
assert.deepEqual(touchThresholds(status.diag), { press: 39547, release: 36994 });
assert.deepEqual(touchThresholds({ ...status.diag, noise: 15 }), { press: 35358, release: 34376 });
assert.equal(numberCommand('sens', 64), 'sens 64');
assert.equal(numberCommand('jspeed', 1200), 'jspeed 1200');
for (const [name, value] of [['reset', 1], ['sens', NaN], ['sens', 1000], ['jspeed', 20000], ['sens', 0]]) {
  assert.throws(() => numberCommand(name, value));
}
// 模拟固件逐条保存时的门限夹紧，确认跨越旧门限也能保存目标值。
for (const [press, release] of [[8, 5], [4, 2], [12, 9]]) {
  const current = { ...status.diag };
  for (const command of touchCommands(press, release, current)) {
    const [key, value] = command.split(' ');
    current[key] = Number(value) / 100;
    if (current.tr >= current.tp) current.tr = current.tp * .6;
  }
  assert.equal(current.tp, press / 100);
  assert.equal(current.tr, release / 100);
}
assert.throws(() => touchCommands(5, 5, status.diag));
assert.throws(() => touchCommands(50, 5, status.diag));
assert.equal(expectedChange('joy 1', status), null); // 3.2不回报开关，不能伪装确认。
assert.deepEqual(expectedChange('joy 0', { ...status, diag: { ...status.diag, joy: 1 } }), { joy: 0 });
assert.deepEqual(expectedChange('invx', status), { invx: 1 });
assert.deepEqual(expectedChange('invy', status), { invy: 0 });
assert.ok(matches(status.diag, { tp: .08, tr: .05 }));
assert.ok(!matches(status.diag, { joy: 1 }));
const expanded = mergeDetails(structuredClone(status), {
  project: 'gunmouse', schema: 1,
  joy: { enabled: 1, ready: 1, raw: [2048, 2091], center: [2048, 2048], speed: 1200, rev: 1, middle: 0 },
  power: { mv: 5070, charge: -1 }, sens: 64, imu_ready: 1, seq: 8, cmd: 'joy',
});
assert.deepEqual(expectedChange('joy 0', expanded), { joy: 0, seq: 9 });
assert.deepEqual(expectedChange('jspeed 1600', expanded), { jspeed: 1600, seq: 9 });
assert.deepEqual(expectedChange('sens 96', expanded), { sens: 96, seq: 9 });
assert.deepEqual(expectedChange('jcenter', expanded), { jrev: 2, seq: 9 });
assert.ok(!matches(expanded.diag, expectedChange('jspeed 1200', expanded))); // 同值也须有新的执行序号。
assert.deepEqual(expectedChange('jcenter', { diag: { ...expanded.diag, jrev: 4294967295, seq: 4294967295 } }), { jrev: 0, seq: 0 });
assert.throws(() => expectedChange('jcenter', { diag: { ...expanded.diag, joy: 0 } }));
assert.throws(() => mergeDetails(structuredClone(status), { project: 'other-device', schema: 1 }));
assert.equal(chargingText(expanded.details.power), '未知（硬件未接入充电反馈）');
assert.ok(!chargingText({ mv: 4100, charge: -1 }).includes('正在充电'));
console.log('控制逻辑检查通过：设备身份、噪声门限、参数范围、逐条保存顺序和回读边界。');
