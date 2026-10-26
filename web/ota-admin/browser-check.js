async (page) => {
  const results = [];
  const check = (condition, label) => { if (!condition) throw new Error(label); results.push(label); };
  await page.route('**/portal.css', route => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('**/favicon.ico', route => route.fulfill({ status: 204 }));
  await page.addInitScript(() => {
    const state = {
      value: { project: 'gunmouse', slot: 'app0', ota: 0, diag: { build: '3.2', raw: 32719, base: 32739.2, noise: 851, tp: .08, tr: .05, touch: 0, ready: 1, invx: 0, invy: 0, cross: -.13558 } },
      writes: [], ignoreWrites: false,
    };
    const target = new EventTarget();
    target.name = 'GunMouse SuperMini';
    target.id = 'simulated-device';
    const status = { readValue: async () => new DataView(new TextEncoder().encode(JSON.stringify(state.value)).buffer) };
    const control = { writeValueWithResponse: async bytes => {
      const text = new TextDecoder().decode(bytes);
      state.writes.push(text);
      if (state.ignoreWrites) return;
      const [name, value] = text.slice(4).split(' ');
      const d = state.value.diag;
      if (name === 'invx' || name === 'invy') d[name] ^= 1;
      if (name === 'tp' || name === 'tr') {
        d[name] = Number(value) / 100;
        if (d.tr >= d.tp) d.tr = d.tp * .6;
      }
    } };
    target.gatt = {
      connected: false,
      connect: async () => { target.gatt.connected = true; return target.gatt; },
      getPrimaryService: async uuid => {
        if (uuid !== 'a38b0001-62da-4c13-9f07-908d8b921571') throw new Error('服务标识不匹配');
        return { getCharacteristic: async id => id.includes('0002-') ? control : status };
      },
      disconnect: () => { target.gatt.connected = false; target.dispatchEvent(new Event('gattserverdisconnected')); },
    };
    state.device = target;
    window.mockGunMouse = state;
    Object.defineProperty(navigator, 'bluetooth', { configurable: true, value: {
      getDevices: async () => [],
      requestDevice: async options => {
        if (options.filters[0].name !== target.name || options.optionalServices.length !== 1) throw new Error('设备过滤不匹配');
        return target;
      },
    } });
  });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:18764/ota-admin/gunmouse.html');
  check(await page.locator('#controls').evaluate(node => node.disabled), '未连接时全部设置禁用');
  await page.getByRole('button', { name: '选择并连接飞鼠' }).click();
  await page.waitForFunction(() => !document.getElementById('controls').disabled);
  check(await page.locator('[data-value="press"]').textContent() === '39547', '实际开启门限包含噪声保护');
  check((await page.locator('[data-value="joy"]').textContent()).includes('未回报'), '3.2摇杆未知状态没有伪装成已启用');
  await page.getByRole('button', { name: '停用摇杆', exact: true }).click();
  await page.waitForFunction(() => document.getElementById('operation-message').textContent.includes('请实际试用确认'));
  check(await page.evaluate(() => window.mockGunMouse.writes.at(-1)) === 'CMD joy 0', '摇杆命令通过真实网页发送路径编码');
  await page.getByRole('button', { name: '切换左右反向' }).click();
  await page.waitForFunction(() => document.getElementById('operation-message').textContent.includes('设备回报确认'));
  check(await page.locator('[data-value="invx"]').textContent() === '开启', '方向切换须与设备回读一致');
  await page.locator('#touch-press').fill('4');
  await page.locator('#touch-release').fill('2');
  await page.getByRole('button', { name: '保存触摸门限' }).click();
  await page.waitForFunction(() => document.getElementById('operation-message').textContent.includes('开启 4.00%'));
  check(await page.evaluate(() => JSON.stringify(window.mockGunMouse.writes.slice(-2))) === '["CMD tr 2.00","CMD tp 4.00"]', '降低门限时保存顺序正确');
  await page.locator('#touch-press').fill('3');
  await page.locator('#touch-release').fill('4');
  const count = await page.evaluate(() => window.mockGunMouse.writes.length);
  await page.getByRole('button', { name: '保存触摸门限' }).click();
  await page.waitForFunction(() => document.getElementById('operation-message').classList.contains('error'));
  check(await page.evaluate(() => window.mockGunMouse.writes.length) === count, '不合法门限在发送前拒绝');
  await page.evaluate(() => { window.mockGunMouse.ignoreWrites = true; });
  await page.getByRole('button', { name: '切换上下反向' }).click();
  await page.waitForFunction(() => document.getElementById('operation-message').textContent.includes('未符合预期'));
  check(await page.locator('[data-value="invy"]').textContent() === '关闭', '未执行的切换没有显示成功且未自动重发');
  await page.setViewportSize({ width: 390, height: 844 });
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), '手机宽度下页面无横向溢出');
  await page.evaluate(() => window.mockGunMouse.device.gatt.disconnect());
  check(await page.locator('#controls').evaluate(node => node.disabled) && await page.locator('[data-value="raw"]').textContent() === '—', '断线立即禁用操作并清空旧读数');
  await page.evaluate(() => { window.mockGunMouse.value.project = 'other-device'; });
  await page.getByRole('button', { name: '选择并连接飞鼠' }).click();
  await page.waitForFunction(() => document.getElementById('operation-message').textContent.includes('有效的飞鼠状态'));
  check(await page.locator('#controls').evaluate(node => node.disabled), '错误设备身份不能进入控制');
  check(errors.length === 0, '浏览器脚本没有未处理异常');
  return { evidence: '浏览器内模拟蓝牙，用于核对页面交互；未连接真实硬件。', passed: results };
}
