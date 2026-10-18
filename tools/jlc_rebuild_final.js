// 最终版原生复绘：仅按机械和电气约定建立新设计，不导入第三方整板。
const a=__CLI__.args||{};
const title='枪型飞鼠最终原生复绘';
function states(p) {
  const names=new Set();
  for(let q=p;q;q=Object.getPrototypeOf(q)) for(const n of Object.getOwnPropertyNames(q)) if(n.startsWith('getState_')) names.add(n);
  return Object.fromEntries([...names].map(n=>[n.slice(9),p[n]()]));
}
async function currentBoard() {
  const project=await eda.dmt_Project.getCurrentProjectInfo();
  if(project?.friendlyName!==title) throw new Error('仅允许本次最终原生复绘工程');
  const boards=project.data.flatMap(x=>x.itemType==='Board'?[x.pcb]:[x]).filter(x=>x?.itemType==='PCB');
  const board=boards.find(x=>x.uuid===a.board)|| (boards.length===1?boards[0]:null);
  if(!board) throw new Error('必须唯一确定主板');
  await eda.dmt_EditorControl.openDocument(board.uuid);
  for(let n=0;n<30;n++) {
    const active=await eda.dmt_SelectControl.getCurrentDocumentInfo();
    if(active?.uuid===board.uuid) return {project,board};
    await new Promise(r=>setTimeout(r,200));
  }
  throw new Error('当前文档尚未切换到指定主板');
}
if(a.action==='environment') return {
  online:eda.sys_Environment.isOnlineMode(),halfOffline:eda.sys_Environment.isHalfOfflineMode(),
  library:await eda.lib_LibrariesList.getPersonalLibraryUuid(),
  system:await eda.lib_LibrariesList.getSystemLibraryUuid(),
  workspace:await eda.dmt_Workspace.getCurrentWorkspaceInfo(),
  project:await eda.dmt_Project.getCurrentProjectInfo(),
  version:eda.sys_Environment.getEditorCurrentVersion()};
if(a.action==='load-library-sample') {
  if(await eda.dmt_Project.getCurrentProjectInfo()) throw new Error('仅用于独立空会话');
  const file=await eda.sys_FileSystem.readFileFromFileSystem(a.path);
  if(!file) throw new Error('封装复用样本不存在');
  const result=await eda.sys_FileManager.importProjectByProjectFile(file,'JLCEDA Pro',
    {importOption:'ImportDocument',associateFootprint:false,associate3DModel:false},
    {operation:'Offline Client Local Path',folderPath:a.folder});
  if(!result) throw new Error('封装复用样本未载入');
  await eda.dmt_Project.openProject(result.uuid);
  return {result,project:await eda.dmt_Project.getCurrentProjectInfo()};
}
if(a.action==='create-legacy-project') {
  if(await eda.dmt_Project.getCurrentProjectInfo()) throw new Error('必须使用独立空会话');
  const uuid=await eda.dmt_Project.createProject(title,'gunmouse-final-native-20261018',
    undefined,undefined,'在嘉立创中从空白重新设计，与最终外壳一致。',undefined,'eprj2');
  if(!uuid) throw new Error('传统原生工程创建失败');
  await eda.dmt_Project.openProject(uuid);
  const file=await eda.sys_FileSystem.readFileFromFileSystem(a.path);
  const result=await eda.sys_FileManager.importProjectByProjectFile(file,'JLCEDA Pro',
    {importOption:'ImportDocument',associateFootprint:false,associate3DModel:false},
    {operation:'Existing Project',existingProjectUuid:uuid});
  return {uuid,result,project:await eda.dmt_Project.getCurrentProjectInfo()};
}
if(a.action==='prepare-final-board') {
  const {project,board:sample}=await currentBoard();
  const components=await eda.pcb_PrimitiveComponent.getAll();
  if(components.length!==18||components.some(x=>!x.getState_Designator().startsWith('LIB_'))) throw new Error('封装样本不符');
  const registry=components.map(x=>({reference:x.getState_Designator().slice(4),footprint:x.getState_Footprint()}));
  const board=await eda.dmt_Pcb.createPcb();
  await eda.dmt_EditorControl.openDocument(board);
  for(let i=0;i<30;i++) {if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid===board) break;await new Promise(r=>setTimeout(r,200));}
  if((await eda.pcb_PrimitivePad.getAll()).length||(await eda.pcb_PrimitiveComponent.getAll()).length) throw new Error('最终板必须从空白建立');
  await eda.pcb_Document.save();
  return {project:project.uuid,sample:sample.uuid,board,registry,empty:true};
}
if(a.action==='library-items') {
  const {project}=await currentBoard();
  const components=await eda.pcb_PrimitiveComponent.getAll();
  const c=components.find(x=>x.getState_Designator()==='LIB_R_TRIG');
  if(!c) throw new Error('封装样本器件未找到');
  const component=states(c);const out=[];
  for(const library of [project.uuid,'project']) {
    try {out.push({library,device:await eda.lib_Device.get(component.Component.uuid.uuid,library),
      footprint:await eda.lib_Footprint.get(component.Footprint.uuid,library)});}
    catch(e) {out.push({library,error:String(e)});}
  }
  return {component,out};
}
if(a.action==='check-native-file') {
  const out=[];
  for(const path of a.paths) {
    const file=await eda.sys_FileSystem.readFileFromFileSystem(path);
    if(!file) {out.push({path,read:false});continue;}
    try {out.push({path,name:file.name,size:file.size,info:await eda.sys_FileManager.extractProjectInfo(file,'JLCEDA Pro')});}
    catch(e) {out.push({path,error:String(e)});}
  }
  return out;
}
if(a.action==='create') {
  if(await eda.dmt_Project.getCurrentProjectInfo()) throw new Error('必须从独立空会话创建');
  const project=await eda.dmt_Project.createProject(title,undefined,undefined,undefined,
    '原最终版按机械和电气约定在嘉立创内重新绘制；新布局布线，不导入其他软件整板。',undefined,'eprj3');
  if(!project) throw new Error('原生新建工程失败');
  await eda.dmt_Project.openProject(project);
  const board=await eda.dmt_Pcb.createPcb();
  await eda.dmt_Pcb.modifyPcbName(board,'最终原生主板');
  await eda.dmt_EditorControl.openDocument(board);
  await eda.pcb_Document.save();
  return {project:await eda.dmt_Project.getCurrentProjectInfo(),board};
}
if(a.action==='footprint-probe') {
  const library=await eda.lib_LibrariesList.getPersonalLibraryUuid();
  if(!library) throw new Error('当前环境没有可用个人库');
  const uuid=await eda.lib_Footprint.create(library,'GM_FINAL_原生封装验证_20261018',[],
    '最终板复绘接口验证；两个2.6毫米焊盘、1.1毫米孔、间距10.16毫米');
  if(!uuid) throw new Error('原生个人库封装建立失败');
  const tab=await eda.lib_Footprint.openInEditor(uuid,library);
  const existing=await eda.pcb_PrimitivePad.getAll();
  if(existing?.length) throw new Error('新封装意外非空');
  const pins=[];
  for(const [n,x] of [['1',-200],['2',200]]) {
    const p=await eda.pcb_PrimitivePad.create(12,n,x,0,0,['ELLIPSE',2.6/.0254,2.6/.0254],
      '', ['ROUND',1.1/.0254],0,0,0,true,0);
    if(!p) throw new Error('原生封装焊盘建立失败');
    pins.push(states(p));
  }
  if(!await eda.pcb_Document.save()) throw new Error('原生封装未保存');
  return {library,uuid,tab,pins,source:await eda.sys_FileManager.getDocumentSource()};
}
if(a.action==='place') {
  const {project,board}=await currentBoard();
  const library=await eda.lib_LibrariesList.getSystemLibraryUuid();
  const result=[];
  const known=await eda.pcb_PrimitiveComponent.getAll();
  for(const spec of a.components) {
    if(known.some(x=>x.getState_Designator()===spec.reference)) throw new Error('禁止重复放置 '+spec.reference);
    const device=spec.footprint?{libraryType:'4',libraryUuid:project.uuid,uuid:spec.footprint.uuid}:
      await eda.lib_Device.get(spec.deviceUuid,library);
    if(!device) throw new Error('库器件不存在 '+spec.reference);
    const c=await eda.pcb_PrimitiveComponent.create(device,spec.layer,spec.x,spec.y,spec.rotation,false);
    if(!c) throw new Error('器件建立失败 '+spec.reference);
    const id=c.getState_PrimitiveId();
    await eda.pcb_PrimitiveComponent.modify(id,{designator:spec.reference,name:spec.name});
    for(const p of spec.pads) {
      const pins=await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(id);
      const target=pins.find(x=>x.getState_PadNumber()===p.number);
      if(!target) throw new Error('引脚编号不符 '+spec.reference+'.'+p.number);
      if(!spec.footprint) {
        target.setState_X(p.x);target.setState_Y(p.y);target.setState_Rotation(p.rotation);
        target.setState_Pad(p.pad);
        target.setState_Hole(p.hole?[p.hole[0],...p.hole.slice(1).map(x=>x*10)]:null);
        target.setState_HoleOffsetX(p.holeOffsetX||0);target.setState_HoleOffsetY(p.holeOffsetY||0);
        target.setState_HoleRotation(p.holeRotation||0);target.setState_Metallization(p.plated);
      }
      target.setState_Net(p.net||'');
      target.setState_SolderMaskAndPasteMaskExpansion({topSolderMask:0,bottomSolderMask:0,topPasteMask:0,bottomPasteMask:0});
      await target.done();
    }
    const pins=await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(id);
    result.push({reference:spec.reference,component:states(await eda.pcb_PrimitiveComponent.get(id)),pads:pins.map(states)});
  }
  if(!await eda.pcb_Document.save()) throw new Error('主板保存失败');
  return {project,board:board.uuid,result,source:await eda.sys_FileManager.getDocumentSource()};
}
if(a.action==='draw-board') {
  const {project,board}=await currentBoard();
  if((await eda.pcb_PrimitivePad.getAll()).length||(await eda.pcb_PrimitiveComponent.getAll()).length) throw new Error('只允许在空白主板绘制');
  const points=a.outline.map(([x,y])=>[x/.0254,-y/.0254]);
  const polygon=eda.pcb_MathPolygon.createPolygon([points[0][0],points[0][1],'L',...points.slice(1).flat(),...points[0]]);
  await eda.pcb_PrimitivePolyline.create('',11,polygon,8,false);
  const result=[];
  for(const p of a.pads) {
    const pad=await eda.pcb_PrimitivePad.create(12,p.ref+(p.number?'.'+p.number:''),p.x,p.y,p.rotation,
      p.pad,p.net,p.hole,0,0,p.holeRotation,p.plated,0,undefined,
      {topSolderMask:0,bottomSolderMask:0,topPasteMask:0,bottomPasteMask:0},undefined,false);
    if(!pad) throw new Error('原生焊盘建立失败 '+p.ref+'.'+p.number);
    result.push({reference:p.ref,number:p.number,...states(pad)});
  }
  for(const s of a.silk) await eda.pcb_PrimitiveString.create(3,s.x,s.y,s.text,'default',s.height||31.5,5.9,5,s.rotation||0,false,0,false,false);
  await eda.pcb_Document.save();
  return {project:project.uuid,board:board.uuid,pads:result,source:await eda.sys_FileManager.getDocumentSource()};
}
if(a.action==='prepare') {
  const {board}=await currentBoard();
  const rules=await eda.pcb_Drc.getCurrentRuleConfiguration();
  const config=rules.config;
  for(const table of Object.values(config.Spacing['Safe Spacing'].copperThickness1oz.tables)) {
    const rows=table.content.map(r=>Array.from(r,Number));
    for(let row=0;row<=7;row++) for(let col=0;col<=row;col++) rows[row][col]=.25;
    for(let col=0;col<=7;col++) {rows[8][col]=.25;rows[11][col]=.5;rows[12][col]=.25;}
    table.content=rows;
  }
  config.Spacing['Other Spacing'].otherClearance.form.hole2Hole=.25;
  Object.assign(config.Physics.Track.copperThickness1oz.form.data['1'],{minValue:.25,defaultValue:.30});
  Object.assign(config.Physics['Via Size'].viaSize.form,{viaOuterdiameterMin:.6,viaOuterdiameterDefault:.7,viaInnerdiameterMin:.25,viaInnerdiameterDefault:.3});
  if(!await eda.pcb_Drc.overwriteCurrentRuleConfiguration(config)) throw new Error('制造规则写入失败');
  for(const p of await eda.pcb_PrimitivePad.getAll()) {
    p.setState_SolderMaskAndPasteMaskExpansion({topSolderMask:0,bottomSolderMask:0,topPasteMask:0,bottomPasteMask:0});
    p.setState_HeatWelding(null);await p.done();
  }
  function poly(mm) {
    const p=mm.map(([x,y])=>[x/.0254,-y/.0254]);
    return eda.pcb_MathPolygon.createPolygon([p[0][0],p[0][1],'L',...p.slice(1).flat(),...p[0]]);
  }
  const existing=await eda.pcb_PrimitiveRegion.getAll();
  if(existing.length) throw new Error('禁布区已存在，拒绝重复建立');
  await eda.pcb_PrimitiveRegion.create(12,poly([[23.42,16.42],[32.58,16.42],[32.58,28.58],[23.42,28.58]]),[5,7],'ANTENNA_NO_COPPER',undefined,false);
  for(const [x,y,travel] of [[43.25,7.7,0],[23.75,7.7,.6]]) {
    const p=[];
    for(let i=0;i<=24;i++) {const r=(-90+180*i/24)*Math.PI/180;p.push([x+travel+2.7*Math.cos(r),y+2.7*Math.sin(r)]);}
    for(let i=0;i<=24;i++) {const r=(90+180*i/24)*Math.PI/180;p.push([x-travel+2.7*Math.cos(r),y+2.7*Math.sin(r)]);}
    await eda.pcb_PrimitiveRegion.create(1,poly(p),[5,7],'SCREW_HEAD_'+x,undefined,false);
  }
  await eda.pcb_Document.save();
  return {board:board.uuid,rules:await eda.pcb_Drc.getCurrentRuleConfiguration(),
    pads:(await eda.pcb_PrimitivePad.getAll()).map(states),drc:await eda.pcb_Drc.check(true,false,true)};
}
if(a.action==='routes') {
  const {board}=await currentBoard();
  const file=await eda.sys_FileSystem.readFileFromFileSystem(a.path);
  const plan=JSON.parse(await file.text());
  if(a.replace) {
    for(const api of [eda.pcb_PrimitivePour,eda.pcb_PrimitiveLine,eda.pcb_PrimitiveVia]) {
      const items=await api.getAll();if(items.length) await api.delete(items);
    }
  } else if(!a.append&&(await eda.pcb_PrimitiveLine.getAll()).length) throw new Error('已有走线，禁止重复写入');
  if(a.append) {const pours=await eda.pcb_PrimitivePour.getAll();if(pours.length) await eda.pcb_PrimitivePour.delete(pours);}
  for(const v of plan.vias) {
    const p=await eda.pcb_PrimitiveVia.create(v.net,v.x,v.y,v.hole,v.diameter);
    if(!p) throw new Error('过孔创建失败');
  }
  for(const s of plan.segments) {
    const p=await eda.pcb_PrimitiveLine.create(s.net,s.layer,s.startX,s.startY,s.endX,s.endY,s.lineWidth,false);
    if(!p) throw new Error('走线创建失败');
  }
  await eda.pcb_Document.save();
  return {board:board.uuid,lines:(await eda.pcb_PrimitiveLine.getAll()).map(states),
    vias:(await eda.pcb_PrimitiveVia.getAll()).map(states),drc:await eda.pcb_Drc.check(true,false,true)};
}
if(a.action==='pour') {
  const {board}=await currentBoard();
  const old=await eda.pcb_PrimitivePour.getAll();if(old.length) await eda.pcb_PrimitivePour.delete(old);
  const p=[[5,5],[57,5],[57,87],[20,87],[20,35],[5,35]].map(([x,y])=>[x/.0254,-y/.0254]);
  const polygon=eda.pcb_MathPolygon.createPolygon([p[0][0],p[0][1],'L',...p.slice(1).flat(),...p[0]]);
  const made=[];
  for(const layer of [1,2]) {
    const pour=await eda.pcb_PrimitivePour.create('GND',layer,polygon,'solid',false,'GND_'+layer,1,8,false);
    if(!pour) throw new Error('铺铜创建失败');
    await pour.rebuildCopperRegion();made.push(states(pour));
  }
  await eda.pcb_Document.save();
  return {board:board.uuid,pours:made,drc:await eda.pcb_Drc.check(true,false,true)};
}
if(a.action==='export') {
  const {project,board}=await currentBoard();
  const drc=await eda.pcb_Drc.check(true,false,true);
  if(!a.diagnostic&&(!Array.isArray(drc)||drc.length)) throw new Error('设计规则未通过，拒绝正式导出');
  if(!await eda.pcb_Document.save()) throw new Error('主板保存失败');
  const files=[];
  async function pack(name,blob) {
    if(!blob) throw new Error('原生文件未生成 '+name);
    const bytes=new Uint8Array(await blob.arrayBuffer());let binary='';
    for(let i=0;i<bytes.length;i+=32768) binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
    files.push({name,bytes:bytes.length,base64:btoa(binary)});
  }
  await pack('嘉立创原始制板文件.zip',await eda.pcb_ManufactureData.getGerberFile('枪型飞鼠_最终原生复绘',false,'mm',
    {integerNumber:4,decimalNumber:6},{metallicDrillingInformation:true,nonMetallicDrillingInformation:true,drillTable:false,flyingProbeTestingFile:false},
    [1,2,3,4,5,6,11].map(layerId=>({layerId,isMirror:false}))));
  await pack('枪型飞鼠_最终原生复绘.epro2',await eda.sys_FileManager.getProjectFile('枪型飞鼠_最终原生复绘',undefined,'epro2'));
  return {project,board:board.uuid,drc,pads:(await eda.pcb_PrimitivePad.getAll()).map(states),
    lines:(await eda.pcb_PrimitiveLine.getAll()).map(states),vias:(await eda.pcb_PrimitiveVia.getAll()).map(states),
    source:await eda.sys_FileManager.getDocumentSource(),files};
}
if(a.action==='labels') {
  const {board}=await currentBoard();
  const existing=await eda.pcb_PrimitiveString.getAll();
  if(existing.length>1) throw new Error('已有元件标注，拒绝重复添加');
  const labels=[];
  for(const s of a.labels) {
    const text=await eda.pcb_PrimitiveString.create(3,s.x/.0254,-s.y/.0254,s.text,'default',(s.height||.8)/.0254,.15/.0254,5,s.rotation||0,false,0,false,false);
    if(!text) throw new Error('标注失败 '+s.text);labels.push(states(text));
  }
  await eda.pcb_Document.save();return {board:board.uuid,labels,drc:await eda.pcb_Drc.check(true,false,true)};
}
if(a.action==='finalize') {
  const {project,board}=await currentBoard();
  const before=await eda.pcb_Drc.check(true,false,true);
  if(!Array.isArray(before)||before.length) throw new Error('规则未通过，不能定稿');
  const sample=project.data.find(x=>x.itemType==='PCB'&&x.name==='仅供封装复用的样本');
  if(sample&&!await eda.dmt_Pcb.deletePcb(sample.uuid)) throw new Error('临时封装样本未移除');
  const renamed=await eda.dmt_Pcb.modifyPcbName(board.uuid,'枪型飞鼠最终主板');
  await new Promise(r=>setTimeout(r,500));
  await eda.pcb_Document.save();
  return {renamed,project:await eda.dmt_Project.getCurrentProjectInfo(),board:board.uuid,
    drc:await eda.pcb_Drc.check(true,false,true),source:await eda.sys_FileManager.getDocumentSource()};
}
if(a.action==='inspect') {
  const {project,board}=await currentBoard();
  return {project,board:board.uuid,components:(await eda.pcb_PrimitiveComponent.getAll()).map(states),
    pads:(await eda.pcb_PrimitivePad.getAll()).map(states),
    lines:(await eda.pcb_PrimitiveLine.getAll()).map(states),vias:(await eda.pcb_PrimitiveVia.getAll()).map(states),
    source:await eda.sys_FileManager.getDocumentSource(),poured:a.poured?(await eda.pcb_PrimitivePoured.getAll()).map(states):undefined,
    drc:a.drc?await eda.pcb_Drc.check(true,false,true):null};
}
throw new Error('未知操作 '+a.action);
