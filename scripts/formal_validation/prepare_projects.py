"""复制正式工程用于软件验证；新建目录，不覆盖原工程或已有试验。"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import uuid

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "pcb" / "gun-mouse-v1"
NAMES = {
    "gun-mouse-formal-baseline": False,
    "gun-mouse-formal-roundtrip": True,
    "gun-mouse-formal-route": True,
    "gun-mouse-formal-copper": False,
}


def parse_records(path):
    records = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "||" in line:
            head, body = line.split("||", 1)
            content = body.rstrip("|")
            records.append((line, json.loads(head), json.loads(content) if content else {}))
    return records


def main():
    if not SOURCE.resolve().is_relative_to(ROOT / "pcb"):
        raise RuntimeError("源工程不在当前工作树")
    source_index = SOURCE / "gun-mouse-v1.eprj3"
    source_board = SOURCE / "pcb" / "PCB1.epcb2"
    original_hash = hashlib.sha256(source_board.read_bytes()).hexdigest()
    summary = []
    for name, unrouted in NAMES.items():
        target = ROOT / "pcb" / name
        if target.resolve().parent != (ROOT / "pcb").resolve():
            raise RuntimeError("目标超出隔离目录")
        renamed_index = target / (name + ".eprj3")
        board = target / "pcb" / "PCB1.epcb2"
        marker_path = target / "validation-marker.json"
        if target.exists():
            if marker_path.exists():
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                if marker.get("project") != name or marker.get("source_board_sha256") != original_hash:
                    raise RuntimeError(f"既有验证目录身份不符：{target}")
                summary.append(marker)
                continue
            # 只恢复本脚本已创建、尚未更改 PCB 内容的中断副本。
            if not renamed_index.exists() or hashlib.sha256(board.read_bytes()).hexdigest() != original_hash:
                raise RuntimeError(f"拒绝覆盖无法识别的既有目录：{target}")
            if json.loads(renamed_index.read_text(encoding="utf-8"))["name"] != name:
                raise RuntimeError("中断副本的工程名称不符")
        else:
            shutil.copytree(SOURCE, target)
            index = json.loads(source_index.read_text(encoding="utf-8-sig"))
            owner = uuid.uuid4().hex
            for key in ("owner_uuid", "creator_uuid", "modifier_uuid"):
                index[key] = owner
            index["profile"]["owner"]["uuid"] = owner
            index["name"] = name
            index["content"] = "正式飞鼠设计的独立程序验证副本；不替换交付设计"
            (target / source_index.name).rename(renamed_index)
            renamed_index.write_bytes((json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        removed = Counter()
        if unrouted:
            retained = []
            for line, header, body in parse_records(board):
                kind = header["type"]
                if kind == "VIA" or (kind in ("LINE", "ARC") and body.get("layerId") in (1, 2)):
                    removed[kind] += 1
                else:
                    retained.append(line)
            board.write_bytes(("\n".join(retained) + "\n").encode("utf-8"))
        marker = {"project": name, "source": str(SOURCE), "source_board_sha256": original_hash,
                  "board_sha256_before_open": hashlib.sha256(board.read_bytes()).hexdigest(),
                  "removed_routes": dict(removed), "purpose": "正式板独立验证，不更改交付设计"}
        marker_path.write_bytes((json.dumps(marker, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        summary.append(marker)
    destination = ROOT / "outputs" / "formal-validation"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "prepared-projects.json").write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
