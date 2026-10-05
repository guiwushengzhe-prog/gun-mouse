"""仅检查新支撑柱与已保存装配主板实体的局部空间，不做强度验收。"""
import hashlib
import json
import sys
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "pcb_shell_v1"))
from build_shell import cyl_y  # noqa: E402
from verify_mechanical import solid_contacts  # noqa: E402


def main():
    source = ROOT / "outputs" / "pcb-shell-v1" / "preview-models" / "pcb.step"
    if not source.is_file():
        raise FileNotFoundError("缺少已装配主板实体。先从冻结装配建立对应模型；不凭占位盒通过检查。")
    cfg = json.loads((ROOT / "config" / "pcb-shell-v1.json").read_text(encoding="utf-8"))
    patch = json.loads((ROOT / "config" / "装配优化候选.json").read_text(encoding="utf-8"))["joystick_support"]
    end = cfg["board"]["top_face_y"] - cfg["board"]["thickness"] - patch["nominal_board_gap_mm"]
    column = cyl_y(*patch["xz_mm"], patch["radius_mm"], patch["bottom_y_mm"], end)
    board = cq.importers.importStep(str(source)).val()
    contacts = solid_contacts(column, board)
    if contacts:
        raise ValueError(f"新支撑柱与保存的主板实体干涉：{contacts}")
    result = {"geometry_check_passed": True, "manufacturing_finalized": False,
              "assembled_pcb_source": str(source.relative_to(ROOT)),
              "assembled_pcb_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "assembled_pcb_solids": len(board.Solids()), "positive_intersections_mm3": contacts,
              "note": "只证明所读装配主板的局部几何；未证明真实柱高、板弯曲、触点保持力或寿命。"}
    target = ROOT / "evidence" / "design-review-v1" / "支撑柱局部干涉.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
