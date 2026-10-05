"""创建嘉立创专业版文件夹格式工程索引（.eprj3），供程序接口打开。

用法：python create_project.py <工程目录> <工程名> [说明]
目录已存在索引时不覆盖。
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid


def main():
    root = Path(sys.argv[1]).resolve()
    name = sys.argv[2]
    note = sys.argv[3] if len(sys.argv) > 3 else ""
    index_path = root / f"{name}.eprj3"
    if index_path.exists():
        print(index_path)
        return
    owner = uuid.uuid4().hex
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    # 索引结构依据嘉立创官方生成器 easyeda/easyeda-eprj3-skill，与 create_eda_demo.py 相同。
    index = {
        "name": name, "owner_uuid": owner, "creator_uuid": owner,
        "created_at": stamp, "updated_at": stamp, "modifier_uuid": owner,
        "content": note, "archive": False,
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
    (root / "sch").mkdir(parents=True, exist_ok=True)
    (root / "pcb").mkdir(exist_ok=True)
    with index_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(index, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(index_path)


if __name__ == "__main__":
    main()
