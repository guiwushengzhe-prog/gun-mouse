async page => {
  const checks=[],writes=[],errors=[];
  const check=(value,name)=>{if(!value)throw new Error(name);checks.push(name);};
  const state={config:{enabled:true,address:'12:34:56:78:90:AB',strength_mg:1650,cooldown_ms:500},
    state:'ready',connected:true,received:10,executed:0,last_strength_mg:2100,heartbeat_age_ms:150};
  let revision=1,offline=false,pending=false;
  const persistence=()=>({instance:'test-instance',state:pending?'pending':'ready',components:[
    {instance:'general',saved_revision:pending?1:2}]});
  await page.route('**/portal.css',route=>route.fulfill({contentType:'text/css',body:''}));
  await page.route('http://127.0.0.1:8766/api/gunmouse/**',async route=>{
    if(offline)return route.abort('connectionrefused');
    const path=new URL(route.request().url()).pathname;
    const headers={'Access-Control-Allow-Origin':'http://127.0.0.1:18764',
      'Access-Control-Allow-Methods':'GET, POST','Access-Control-Allow-Headers':'Content-Type'};
    if(route.request().method()==='OPTIONS')return route.fulfill({status:204,headers,body:''});
    let data;
    if(path.endsWith('/devices'))data={ok:true,devices:[{address:state.config.address,name:'GunMouse SuperMini'}]};
    else {
      if(route.request().method()==='POST'){const body=route.request().postDataJSON();writes.push(body);state.config=body;revision++;}
      data={ok:!pending,gunmouse:state,config_revision:revision,settings_persistence:persistence()};
      if(pending&&route.request().method()==='POST')Object.assign(data,{applied:true,error:'文件暂被占用',
        settings_write:{instance:'test-instance',targets:[{instance:'general',revision:2}]}});
      else data.ok=true;
    }
    await route.fulfill({status:pending&&route.request().method()==='POST'?503:200,headers,contentType:'application/json',body:JSON.stringify(data)});
  });
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto('http://127.0.0.1:18764/ota-admin/gunmouse.html');
  check(await page.locator('#punch-controls').evaluate(node=>node.disabled),'未连软件不能改甩拳设置');
  await page.locator('#punch-connect').click();
  await page.waitForFunction(()=>!document.getElementById('punch-controls').disabled);
  check(await page.locator('#punch-strength').inputValue()==='1650','显示软件已有强度，没有覆盖成默认值');
  check(await page.locator('#punch-count').textContent()==='0','本轮从连接时累计开始');
  await page.locator('#punch-strength').fill('1950');await page.locator('#punch-strength').dispatchEvent('input');
  await page.locator('#punch-cooldown').fill('750');await page.locator('#punch-cooldown').dispatchEvent('input');
  await page.waitForTimeout(1100);
  check(await page.locator('#punch-strength').inputValue()==='1950','状态刷新保留正在编辑的值');
  await page.locator('#punch-save').click();
  await page.waitForFunction(()=>document.getElementById('punch-message').textContent.includes('已保存'));
  check(writes[0].strength_mg===1950&&writes[0].cooldown_ms===750,'网站保存到软件共用参数');
  state.state='disconnected';state.connected=false;
  state.error='飞鼠连接未完成: Characteristic a38b0004-62da-4c13-9f07-908d8b921571 was not found!';
  await page.locator('#punch-save').click();
  await page.waitForFunction(()=>document.getElementById('punch-message').textContent.includes('等待飞鼠'));
  check((await page.locator('#punch-message').textContent()).includes('已保存'),'配置保存和设备就绪分别确认');
  check(!(await page.locator('#punch-state').textContent()).includes('Characteristic'),'状态卡不用底层异常撑大');
  check((await page.locator('#punch-link-status').textContent()).includes('不会计数'),'未就绪时明确说明不接收动作');
  state.state='ready';state.connected=true;state.error='';
  await page.waitForFunction(()=>document.getElementById('punch-message').textContent.includes('飞鼠已就绪'));
  check((await page.locator('#punch-link-status').textContent()).includes('心跳'),'恢复后自动显示真实设备确认和心跳');
  state.received+=2;
  await page.waitForFunction(()=>document.getElementById('punch-count').textContent==='2');
  await page.locator('#punch-reset-count').click();
  check(state.received===12&&await page.locator('#punch-count').textContent()==='0','归零只改变本轮显示，不改累计');
  pending=true;
  await page.locator('#punch-strength').fill('2000');await page.locator('#punch-strength').dispatchEvent('input');
  await page.locator('#punch-save').click();
  await page.waitForFunction(()=>document.getElementById('punch-message').textContent.includes('尚未保存'));
  pending=false;
  await page.waitForFunction(()=>document.getElementById('punch-message').textContent.includes('已保存'));
  check(true,'写盘失败如实显示，软件补存后才显示已保存');
  for(const width of [390,1280]){await page.setViewportSize({width,height:900});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${width}宽度不横向溢出`);}
  offline=true;
  await page.waitForFunction(()=>document.getElementById('punch-controls').disabled);
  check(await page.locator('#punch-total').textContent()==='—','断线后禁用控件并清空旧计数');
  check(errors.length===0,'页面没有脚本异常');
  return {evidence:'模拟本机软件，只检查网页交互，不连接蓝牙或发送游戏按键',passed:checks};
}
