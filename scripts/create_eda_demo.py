"""创建独立空工程索引，供嘉立创程序接口做工具验证。"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid


root = Path(__file__).resolve().parents[1] / "pcb" / "toolchain-demo"
index_path = root / "toolchain-demo.eprj3"
owner = uuid.uuid4().hex
stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
# 索引结构依据嘉立创官方生成器 easyeda/easyeda-eprj3-skill。
index = {
    "name": root.name, "owner_uuid": owner, "creator_uuid": owner,
    "created_at": stamp, "updated_at": stamp, "modifier_uuid": owner,
    "content": "工具验证示例，不是真实飞鼠设计。", "archive": False,
    "cbb_project": 0, "thumb": "", "ticket": 1, "g_ticket": 1,
    "boards": [], "block_symbol_attrs_groups": {}, "default_sheet": "",
    "branch_uuid": "", "pcb_count": 0, "format": "folder",
    "profile": {
        "boards": {}, "schematics": {}, "sheets": {}, "pcbs": {},
        "panels": {}, "blockSymbols": {}, "owner": {"uuid": owner},
        "simSchematics": {}, "simulations": {},
    },
    "config": {"defaultSheet": "", "settings": {}},
}
root.mkdir(parents=True, exist_ok=True)
(root / "sch").mkdir(exist_ok=True)
(root / "pcb").mkdir(exist_ok=True)
with index_path.open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(index, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
print(index_path)
