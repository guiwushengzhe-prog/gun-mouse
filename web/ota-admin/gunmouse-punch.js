// 与本机软件共用设置和事件，不建立第二条蓝牙管理连接。
const $ = id => document.getElementById(id);
const ROOT = 'http://127.0.0.1:8766';
const states = {off:'已关闭',select_device:'等待选设备',connecting:'连接中',waiting:'等待设备',calibrating:'请放稳',
  applying:'应用参数中',ready:'已就绪',disconnected:'设备断开',firmware_required:'需更新固件',unavailable:'组件未准备'};
let linked=false,busy=false,dirty=false,baseline=null,lastTotal=0,timer=null,pendingReceipt=null,savedNotice=false;
let revision=-1,instance=null;

function message(text){$('punch-message').textContent=text;}
function controls(){ $('punch-controls').disabled=!linked||busy;$('punch-connect').disabled=busy||linked; }
function labels(){
  $('punch-strength-value').textContent=`${(Number($('punch-strength').value)/1000).toFixed(2)} 倍重力`;
  $('punch-cooldown-value').textContent=`${$('punch-cooldown').value} 毫秒`;
}
function ready(g){return g.connected===true&&g.state==='ready';}
function savedMessage(g){
  if(!g.config?.enabled)return '甩拳设置已保存，拳击模式已关闭。';
  return ready(g)?'甩拳设置已保存，飞鼠已就绪。':'甩拳设置已保存；正在等待飞鼠连接并确认参数。';
}
function connectionDetail(g){
  // 兼容尚未更新的本机软件；底层异常不能代替设备状态。
  if(g.error){
    if(/Characteristic|not found|GATT|HRESULT/i.test(g.error))return '飞鼠蓝牙接口尚未完整就绪，软件正在重新连接。请保持飞鼠开机；此时甩动不会计数。';
    return g.error;
  }
  if(ready(g))return `飞鼠已确认参数，正在接收心跳${g.heartbeat_age_ms!=null?`（${(g.heartbeat_age_ms/1000).toFixed(1)}秒前）`:''}。现在可观察甩动计数。`;
  if(g.state==='off')return '拳击模式已关闭，甩动不会计数。';
  if(g.state==='select_device')return '请选择已配对的飞鼠并保存。';
  if(g.state==='calibrating')return '已接收设备回报，请先放稳飞鼠，等待设备就绪。';
  return '尚未收到飞鼠的有效确认，软件会自动重试。请保持设备开机并在电脑附近；此时甩动不会计数。';
}
function deviceOption(address,name='枪型飞鼠'){
  const select=$('punch-device');
  if(address&&![...select.options].some(item=>item.value===address))select.add(new Option(`${name} · ${address}`,address));
}
async function request(path,body){
  let response;
  try{response=await fetch(ROOT+path,{cache:'no-store',signal:AbortSignal.timeout(6000),
    ...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});}
  catch{throw new Error('无法连接本机 MotionControl。请先打开软件，并允许浏览器访问本地网络，再点“连接甩拳控制”。');}
  const data=await response.json();
  if(!response.ok||data.ok===false){const error=new Error(data.error||'设置未完成，请重试');error.payload=data;throw error;}
  return data;
}
function render(data){
  const nextInstance=data.settings_persistence?.instance;
  if(nextInstance&&instance!==nextInstance){instance=nextInstance;revision=-1;baseline=null;}
  if(data.config_revision!=null){if(Number(data.config_revision)<revision)return;revision=Number(data.config_revision);}
  const g=data.gunmouse;
  if(!g)throw new Error('本机软件尚不支持网站调节，请更新 MotionControl 后重新连接。');
  linked=true;
  $('punch-badge').textContent=ready(g)?'软件已连接 · 飞鼠就绪':'软件已连接 · 飞鼠未就绪';
  if(!dirty){
    const c=g.config||{};deviceOption(c.address);$('punch-device').value=c.address||'';
    $('punch-enabled').checked=c.enabled===true;
    $('punch-strength').value=String(c.strength_mg??1800);$('punch-cooldown').value=String(c.cooldown_ms??500);labels();
  }
  const total=Number(g.received)||0;
  if(baseline===null||total<lastTotal)baseline=total;
  lastTotal=total;
  $('punch-count').textContent=String(Math.max(0,total-baseline));$('punch-total').textContent=String(total);
  $('punch-last-strength').textContent=g.last_strength_mg?`${(g.last_strength_mg/1000).toFixed(2)} 倍`:'—';
  $('punch-state').textContent=g.state==='ready'&&!g.connected?'等待确认':states[g.state]||'等待状态';
  $('punch-link-status').textContent=connectionDetail(g);
  if(pendingReceipt){
    const state=data.settings_persistence;
    if(state?.instance!==pendingReceipt.instance){message('软件已重新启动，请再次保存本页修改。');dirty=true;pendingReceipt=null;savedNotice=false;}
    else if(pendingReceipt.targets.every(target=>state.components?.some(part=>part.instance===target.instance&&part.saved_revision>=target.revision))){
      savedNotice=true;pendingReceipt=null;
    }
  }
  if(savedNotice&&!dirty&&!pendingReceipt)message(savedMessage(g));
  controls();
}
function disconnected(error){
  clearTimeout(timer);linked=false;controls();
  $('punch-badge').textContent='软件未连接';$('punch-state').textContent='未连接';
  $('punch-link-status').textContent='未连接本机软件，当前没有接收甩拳动作。';
  for(const id of ['punch-count','punch-total','punch-last-strength'])$(id).textContent='—';
  message(error.message);
}
function poll(){
  clearTimeout(timer);
  if(!linked||document.hidden)return;
  timer=setTimeout(async()=>{
    if(busy){poll();return;}
    try{render(await request('/api/gunmouse/status'));poll();}catch(error){disconnected(error);}
  },1000);
}
$('punch-connect').addEventListener('click',async()=>{
  if(busy)return;busy=true;controls();message('正在连接本机软件…');
  try{
    render(await request('/api/gunmouse/status'));
    const devices=await request('/api/gunmouse/devices');
    for(const item of devices.devices||[])deviceOption(item.address,item.name);
    if(!$('punch-device').value&&devices.devices?.length===1){$('punch-device').value=devices.devices[0].address;dirty=true;}
    savedNotice=false;message('已连接本机软件。飞鼠是否就绪请看下方状态；调整后点保存。');
  }catch(error){disconnected(error);}
  finally{busy=false;controls();poll();}
});
for(const id of ['punch-enabled','punch-device','punch-strength','punch-cooldown'])$(id).addEventListener('input',()=>{dirty=true;savedNotice=false;labels();});
$('punch-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!linked||busy)return;busy=true;controls();message('正在保存…');
  const body={enabled:$('punch-enabled').checked,address:$('punch-device').value,
    strength_mg:Number($('punch-strength').value),cooldown_ms:Number($('punch-cooldown').value)};
  try{const data=await request('/api/gunmouse/config',body);dirty=false;pendingReceipt=null;savedNotice=true;render(data);}
  catch(error){
    const data=error.payload;
    if(data?.applied){dirty=false;savedNotice=false;render(data);pendingReceipt=data.settings_write;message('已应用，尚未保存；软件会自动补存。');}
    else message(error.message);
  }finally{busy=false;controls();poll();}
});
$('punch-reset-count').addEventListener('click',()=>{baseline=lastTotal;$('punch-count').textContent='0';});
document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else poll();});
