"""保存本轮核心证据及本地查看页面，不复制大模型或分块数据。"""
import hashlib
import html
import json
from pathlib import Path
import shutil
from runtime import ROOT, OUT

DEST = ROOT / 'evidence' / 'formal-validation'
FILES = ['prepared-projects.json','baseline-inspect.json','baseline-routes.json',
         'roundtrip-apply-retry.json','roundtrip-reopened-routes.json','roundtrip-reopened-inspect.json',
         'baseline-netlist.enet','baseline-sch-netlist.enet','formal-electrical-summary.json',
         'route-rules.json','route-start.json','native-route-preview.json','native-routes.json',
         'native-apply.json','native-after-write-unsaved.json','copper-build-retry.json',
         'copper-reopened-inspect.json','copper-gerber-geometry-report.json',
         'baseline-gerber.zip','copper-gerber.zip','copper-reopened-gerber.zip',
         'baseline-pcb-with-parts-file.json','assembly-interface-report.json',
         'pcb-shell-current-export-report.json','gun-mouse-formal-roundtrip-saved-validation.json',
         'gun-mouse-formal-baseline-saved-validation.json','copper-gerber-geometry.png']
for source in [OUT/name for name in FILES]:
    if not source.is_file():
        raise FileNotFoundError(source)
DEST.mkdir(parents=True,exist_ok=True)
for name in FILES:
    source, target = OUT/name,DEST/name
    if source.suffix.lower() in {'.json','.enet'}:
        target.write_bytes(source.read_text(encoding='utf-8-sig').replace('\r\n','\n').encode('utf-8'))
    else:
        shutil.copyfile(source,target)
image_dir = DEST/'关系图'
image_dir.mkdir(exist_ok=True)
images = sorted((OUT/'关系图').glob('*.png'))
if len(images) != 4:
    raise RuntimeError('应有四张实际核对关系图')
for source in images:
    shutil.copyfile(source,image_dir/source.name)
description = (ROOT/'docs'/'正式PCB与外壳程序验证结果.md').read_text(encoding='utf-8')
(DEST/'验证说明.md').write_bytes(description.encode('utf-8'))
captions = ['统一坐标下的整机关系','取下左壳后的正式电路板与内部组件','接口与天线附近区域','背面电池仓与固定空间']
figures = ''.join(f'<figure><img src="关系图/{html.escape(path.name)}" alt="{caption}"><figcaption>{caption}</figcaption></figure>' for path,caption in zip(images,captions))
page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>枪型飞鼠：正式PCB与外壳程序核对</title><style>body{max-width:1200px;margin:32px auto;padding:0 20px;background:#f6f8fa;color:#182532;font:17px/1.7 system-ui,"Microsoft YaHei",sans-serif}h1{font-size:29px}h2{font-size:22px}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;text-align:left;border-bottom:1px solid #dbe2ea}figure{margin:24px 0;background:white;border:1px solid #dbe2ea;border-radius:8px;overflow:hidden}img{width:100%;height:auto}figcaption{padding:12px}a{color:#135eaa}.note{padding:16px;background:#fff4d8;border-left:4px solid #ce8b1e}code{font-family:Consolas,monospace}</style>
<h1>正式PCB与外壳程序核对</h1><p>目的是让我通过程序持续设计、检查并联动实际电路板与外壳。原AI方案保留；这一页展示独立副本的真实软件、文件和模型核对。</p>
<table><tr><th>环节</th><th>实际结果</th></tr><tr><td>原正式板</td><td>48器件、160已连接焊盘、575段线、95过孔，规则检查零错误；原理图与电路板编译网表一致。</td></tr><tr><td>程序完整写回</td><td>保存、关闭重开后路线几何与全部读到的属性一致，规则检查零错误。</td></tr><tr><td>主板双面地铜</td><td>创建、填充、保存和重开通过；原线、孔、盘、板框保持。新增铜不覆盖电池线槽。</td></tr><tr><td>PCB与外壳</td><td>新导出实际电路板已按原坐标装配核对，五安装孔、插针、USB及所检查运动状态对应。</td></tr></table>
<p class="note">自动布线仍未全通过：原生算法留有6处未连接；其500段线写回时少了3条极短段。该诊断副本未替代原交付。天线附近原C5/C6布局、扳机极端公差下可能少0.1毫米行程，以及实物尺寸和打印配合仍需确认。</p>
<p>自动布线使用嘉立创原生算法的菜单兼容入口；覆铜和图元读写使用公开程序接口。不能由此推断全部软件功能已可调用。详细结论见 <a href="验证说明.md">验证说明</a>，电路证据见 <a href="formal-electrical-summary.json">电路核对汇总</a>，模型证据见 <a href="pcb-shell-current-export-report.json">新导出装配核对</a>。</p>
<h2>实际模型关系图</h2>'''+figures+'''
<h2>铜层核对</h2><figure><img src="copper-gerber-geometry.png" alt="新增双面地铜和原有天线区域铜"><figcaption>绿色为新增地铜，橙色为当前天线限制范围，红色为原有范围内铜；新增铜接触限制边界，间距为零。</figcaption></figure>
<p><a href="copper-gerber-geometry-report.json">光绘几何报告</a> · <a href="assembly-interface-report.json">装配接口报告</a></p>
<p>分支：<code>codex/formal-validation</code>。图片由实际实体模型生成，非软件截图。开发板、电池仍包含参考尺寸，本页不代表制造与实物验收。</p></html>'''
(DEST/'查看结果.html').write_bytes(page.encode('utf-8'))
manifest = []
for path in sorted(DEST.rglob('*')):
    if path.is_file() and path.name != 'manifest.json':
        data = path.read_bytes()
        manifest.append({'file':path.relative_to(DEST).as_posix(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
(DEST/'manifest.json').write_bytes((json.dumps({'files':manifest,'scope':'正式工程独立程序验证；原交付不变'},ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
print(json.dumps({'files':len(manifest),'bytes':sum(row['bytes'] for row in manifest),'viewer':str(DEST/'查看结果.html')},ensure_ascii=False))
