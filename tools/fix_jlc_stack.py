"""补齐本机4.1.66原生工程的芯板厚度；关闭编辑会话后运行。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT/"pcb/嘉立创最终版/pcb/枪型飞鼠最终主板.epcb2"


def main():
    rows, pcb, changed = [], False, 0
    for line in PATH.read_text(encoding="utf-8").splitlines():
        header, payload = line.split("||", 1)
        head = json.loads(header)
        raw = payload.removesuffix("|")
        body = json.loads(raw) if raw else None
        if head["type"] == "DOCHEAD":
            pcb = body["docType"] == "PCB"
        if pcb and head["type"] == "LAYER_PHYS" and body and body["material"] == "FR4":
            # 来自当前软件实际新建双层1.6毫米板的原生默认记录，含双面35微米铜和阻焊。
            # 4.1.66实际落盘值为毫英寸，与在线新版字段说明存在差异，不能照新版比例换算。
            body.update(thickness=59.449, permittivity=4.5)
            line = header+"||"+json.dumps(body, ensure_ascii=False, separators=(",", ":"))+"|"
            changed += 1
        rows.append(line)
    assert changed == 1, ("主板芯板记录数量不符", changed)
    PATH.write_text("\n".join(rows)+"\n", encoding="utf-8", newline="\n")
    print("已补齐本机原生芯板厚度，等待软件重新打开核对。")


if __name__ == "__main__":
    main()
