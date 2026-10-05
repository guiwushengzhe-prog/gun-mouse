"""将本次核心诊断记录纳入独立试验分支，统一换行并生成文件校验清单。"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMES = (
    "autoroute-visible", "autoroute-menu-visible", "autoroute-menu-headless",
    "verify-visible-routing", "verify-headless-routing", "disk-headless-preview",
    "apply-headless-snapshot", "disk-headless-applied", "apply-visible-snapshot",
    "pour-visible", "pour-headless", "pour-headless-writable",
    "repair-pour-headless", "repair-pour-visible", "disk-headless-pour-corrected",
    "verify-headless-final", "pure-create-pour-corrected", "disk-direct-pour",
    "close-visible-stuck", "reopen-visible",
)


def main():
    target = ROOT / "evidence" / "eda-recovery"
    target.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        source = ROOT / ".logs" / (name + ".json")
        value = json.loads(source.read_text(encoding="utf-8-sig"))
        (target / source.name).write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    manifest_path = target / "文件校验清单.json"
    entries = []
    for file in sorted(target.iterdir()):
        if not file.is_file() or file == manifest_path:
            continue
        data = file.read_bytes()
        if file.suffix in (".json", ".md"):
            data = data.replace(b"\r\n", b"\n")
            file.write_bytes(data)
        entries.append({"name": file.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"purpose": "独立接口试验，不改正式飞鼠成果", "files": entries,
                "note": "磁盘快照中的SHA记录当时的原始软件文件；此清单校验保存的证据和导出压缩包"}
    manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"directory": str(target), "files": len(entries)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
