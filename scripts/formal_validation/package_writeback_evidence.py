"""收集本轮实际验证证据及校验值；不改PCB或覆盖已有证据。"""
import hashlib
import json
from pathlib import Path
import shutil

from runtime import ROOT, OUT


def main():
    destination = ROOT/'evidence'/'route-writeback-fix'
    destination.mkdir(parents=True,exist_ok=True)
    jobs = []
    for label in ('native-repair-05','baseline-regression-01','native-v2-roundtrip-01'):
        suffixes = ('-report.json','-write.json','-reopened.json','-inspect.json','-gerber-audit.json','-gerber.zip')
        jobs.extend((OUT/(label+suffix),destination/(label+suffix)) for suffix in suffixes)
    for name in ('probe-short-results.json','probe-polyline-results.json'):
        jobs.append((ROOT/'outputs'/'route-writeback-fix'/name,destination/name))
    for name in ('probe_short_lines.js','probe_polyline.js'):
        jobs.append((ROOT/'.logs'/name,destination/name))
    for label in ('native-repair-01','native-repair-02','native-repair-03','native-repair-04'):
        jobs.append((OUT/(label+'-write.json'),destination/(label+'-failed-write.json')))
    records = []
    for source,target in jobs:
        if target.exists():
            raise FileExistsError(target)
        shutil.copyfile(source,target)
        records.append({'path':target.relative_to(ROOT).as_posix(),'bytes':target.stat().st_size,
                        'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    manifest = destination/'manifest.json'
    if manifest.exists():
        raise FileExistsError(manifest)
    manifest.write_text(json.dumps({'files':records,'scope':'本轮原生调用实际证据，含失败记录；不作为制造定稿'},
                                  ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'files':len(records),'bytes':sum(p['bytes'] for p in records),'manifest':str(manifest)},ensure_ascii=False))


if __name__ == '__main__':
    main()
