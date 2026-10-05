"""核对原生制造铜层的全部直线绘图，包含以单段折线保存的极短连接。"""
import argparse
import json
import math
from pathlib import Path
import re
import zipfile


def strokes(text, layer):
    fmt = re.search(r'%FSLAX(\d)(\d)Y(\d)(\d)\*%',text)
    if not fmt or fmt.group(2) != fmt.group(4) or '%MOMM*%' not in text:
        raise ValueError('光绘单位或绝对坐标格式不符')
    scale = 10**int(fmt.group(2))
    apertures = {int(m.group(1)):float(m.group(2)) for m in
                 re.finditer(r'%ADD(\d+)C,([0-9.]+)\*%',text)}
    records, section, selected, position = [],None,None,(0.,0.)
    for raw in re.sub(r'%.*?%','',text,flags=re.S).split('*'):
        token = raw.strip()
        if token.startswith('G04'):
            marker = re.match(r'G04\s+(.+?)\s+(Start|End)$',token)
            if marker:
                section = marker.group(1) if marker.group(2) == 'Start' else None
            continue
        aperture = re.fullmatch(r'(?:G54)?D(\d+)',token)
        if aperture and int(aperture.group(1)) >= 10:
            selected = int(aperture.group(1))
            continue
        fields = {key:int(value) for key,value in re.findall(r'([XY])([+-]?\d+)',token)}
        operation = re.search(r'D0?([123])$',token)
        if not operation or not fields:
            continue
        end = (fields.get('X',round(position[0]*scale))/scale,
               fields.get('Y',round(position[1]*scale))/scale)
        if operation.group(1) == '1' and section in ('Track','PolygonModel'):
            if re.search(r'G0?[23]',token) or selected not in apertures:
                raise ValueError('存在未支持的路线绘图或非圆形线宽')
            records.append({'layer':layer,'x1':position[0],'y1':position[1],'x2':end[0],'y2':end[1],
                            'width':apertures[selected],'section':section})
        position = end
    return records


def audit(source, gerber):
    actual = []
    with zipfile.ZipFile(gerber) as archive:
        for name,layer in [('Gerber_TopLayer.GTL',1),('Gerber_BottomLayer.GBL',2)]:
            actual.extend(strokes(archive.read(name).decode('utf-8-sig'),layer))
    # 原生文件量化为2.54纳米、光绘坐标量化为10纳米；合计最大约6.27纳米。
    coordinate_tolerance_mm, width_tolerance_mm = 0.000007,0.00001
    unused = set(range(len(actual)))
    matched, errors = [],[]
    for p in source['lines']:
        expected = {k:p[k]*0.0254 for k in ('x1','y1','x2','y2','width')}
        candidates = []
        for index in unused:
            q = actual[index]
            if q['layer'] != p['layer'] or abs(q['width']-expected['width']) > width_tolerance_mm:
                continue
            direct = max(abs(q[k]-expected[k]) for k in ('x1','y1','x2','y2'))
            reverse = max(abs(q[a]-expected[b]) for a,b in [('x1','x2'),('y1','y2'),('x2','x1'),('y2','y1')])
            if min(direct,reverse) <= coordinate_tolerance_mm:
                candidates.append((index,min(direct,reverse)))
        if len(candidates) != 1:
            errors.append({'sourceId':p['id'],'matchingCount':len(candidates)})
            continue
        index,deviation = candidates[0]
        unused.remove(index)
        matched.append({'sourceId':p['id'],'lengthMm':math.hypot(p['x2']-p['x1'],p['y2']-p['y1'])*0.0254,
                        'sourceWidthMm':expected['width'],'actual':actual[index],'maximumCoordinateDeviationMm':deviation})
    passed = not errors and not unused and len(actual) == len(source['lines'])
    return {'passed':passed,'sourceSegments':len(source['lines']),'manufacturingSegments':len(actual),
              'matchedSegments':len(matched),'coordinateToleranceMm':coordinate_tolerance_mm,
              'widthToleranceMm':width_tolerance_mm,'errors':errors,'unexpectedSegments':[actual[i] for i in sorted(unused)],
              'shortSegments':[p for p in matched if p['lengthMm'] < 0.00254],
              'scope':'核对全部铜层路线绘图；网络、锁定和过孔属性由重开快照核对；不代表制造验收'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('gerber',type=Path)
    parser.add_argument('report',type=Path)
    args = parser.parse_args()
    value = json.loads(args.snapshot.read_text(encoding='utf-8-sig'))
    report = audit(value.get('value',value), args.gerber)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
