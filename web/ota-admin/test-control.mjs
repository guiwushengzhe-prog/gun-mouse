import assert from 'node:assert/strict';
import { validateStatus, touchThresholds, numberCommand, touchCommands, expectedChange, matches } from './gunmouse-core.mjs';

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
console.log('控制逻辑检查通过：设备身份、噪声门限、参数范围、逐条保存顺序和回读边界。');
