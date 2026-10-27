// 与本机软件共用设置和事件，不建立第二条蓝牙管理连接。
const $ = id => document.getElementById(id);
const ROOT = 'http://127.0.0.1:8766';
const states = {off:'已关闭',select_device:'等待选设备',connecting:'连接中',waiting:'等待设备',calibrating:'请放稳',
  applying:'应用参数中',ready:'已就绪',disconnected:'设备断开',firmware_required:'需更新固件',unavailable:'组件未准备'};
let linked=false,busy=false,dirty=false,baseline=null,lastTotal=0,timer=null,pendingReceipt=null;
let revision=-1;

function message(text){$('punch-message').textContent=text;}
function controls(){ $('punch-controls').disabled=!linked||busy;$('punch-connect').disabled=busy||linked; }
function labels(){
  $('punch-strength-value').textContent=`${(Number($('punch-strength').value)/1000).toFixed(2)} 倍重力`;
  $('punch-cooldown-value').textContent=`${$('punch-cooldown').value} 毫秒`;
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
  if(data.config_revision!=null){if(Number(data.config_revision)<revision)return;revision=Number(data.config_revision);}
  const g=data.gunmouse;
  if(!g)throw new Error('本机软件尚不支持网站调节，请更新 MotionControl 后重新连接。');
  linked=true;
  $('punch-badge').textContent='已连接本机软件';
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
  $('punch-state').textContent=g.error||states[g.state]||'等待状态';
  if(pendingReceipt){
    const state=data.settings_persistence;
    if(state?.instance!==pendingReceipt.instance){message('软件已重新启动，请再次保存本页修改。');dirty=true;pendingReceipt=null;}
    else if(pendingReceipt.targets.every(target=>state.components?.some(part=>part.instance===target.instance&&part.saved_revision>=target.revision))){
      message('甩拳设置已保存，MotionControl 已同步。');pendingReceipt=null;
    }
  }
  controls();
}
function disconnected(error){
  clearTimeout(timer);linked=false;controls();
  $('punch-badge').textContent='软件未连接';$('punch-state').textContent='未连接';
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
    message('已连接。调整后点保存；本轮计数可随时归零。');
  }catch(error){disconnected(error);}
  finally{busy=false;controls();poll();}
});
for(const id of ['punch-enabled','punch-device','punch-strength','punch-cooldown'])$(id).addEventListener('input',()=>{dirty=true;labels();});
$('punch-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!linked||busy)return;busy=true;controls();message('正在保存…');
  const body={enabled:$('punch-enabled').checked,address:$('punch-device').value,
    strength_mg:Number($('punch-strength').value),cooldown_ms:Number($('punch-cooldown').value)};
  try{const data=await request('/api/gunmouse/config',body);dirty=false;pendingReceipt=null;render(data);message('甩拳设置已保存，MotionControl 已同步。');}
  catch(error){
    const data=error.payload;
    if(data?.applied){dirty=false;render(data);pendingReceipt=data.settings_write;message('已应用，尚未保存；软件会自动补存。');}
    else message(error.message);
  }finally{busy=false;controls();poll();}
});
$('punch-reset-count').addEventListener('click',()=>{baseline=lastTotal;$('punch-count').textContent='0';});
document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else poll();});
