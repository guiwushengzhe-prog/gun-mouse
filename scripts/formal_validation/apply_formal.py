"""将路线快照写入明确指定的隔离副本，完整保留其它图元。"""
import argparse
import json
from runtime import OUT, SCRIPTS, invoke

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session')
parser.add_argument('snapshot')
parser.add_argument('target_project_uuid')
parser.add_argument('label')
args = parser.parse_args()
source = json.loads((OUT / args.snapshot).read_text(encoding='utf-8'))
value = source.get('value', source)
result = invoke(args.session, SCRIPTS / 'apply_routes.js', args.label,
                {'snapshot': source, 'target': {'projectUuid': args.target_project_uuid,
                                               'boardUuid': value['board']['uuid']}}, 150000)
print(json.dumps({key: result.get(key) for key in ['project','counts','saved','drc','sourceProject','targetProject','matchedCounts']}, ensure_ascii=False))
