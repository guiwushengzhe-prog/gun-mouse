"""在原生 CadQuery 编辑器中查看真实裸板和外壳，支持分别隐藏。"""

import os
from pathlib import Path

import cadquery as cq


def output_directory():
    override = os.environ.get("GUN_MOUSE_PREVIEW_OUTPUT")
    if override:
        output = Path(override)
        if not output.is_absolute():
            raise ValueError("GUN_MOUSE_PREVIEW_OUTPUT 必须指定绝对路径。")
        return output.resolve()
    # 官方 CQ-editor 会为已保存的脚本提供 __file__，不依赖编辑器当前目录。
    script_path = globals().get("__file__")
    if not script_path:
        raise ValueError("请先保存并打开本脚本，或通过 GUN_MOUSE_PREVIEW_OUTPUT 指定模型目录。")
    return Path(script_path).resolve().parent.parent / "outputs" / "toolchain-demo"


def load_models():
    output = output_directory()
    models = []
    for filename in ("eda-board-export.step", "outer-shell.step"):
        path = output / filename
        if not path.is_file():
            raise FileNotFoundError(f"模型不存在，请先完成工具联动生成：{path}")
        model = cq.importers.importStep(str(path))
        shape = cq.Compound.makeCompound(model.vals())
        if not shape.isValid() or not shape.Solids():
            raise ValueError(f"模型不是有效实体：{path}")
        models.append(model)
    return tuple(models)


if callable(globals().get("show_object")):
    board, shell = load_models()
    show_object(board, name="嘉立创真实裸板", options={"color": (38, 145, 78), "alpha": 1.0})
    show_object(shell, name="外壳及四个固定柱", options={"color": (125, 160, 190), "alpha": 0.35})
elif __name__ == "__main__":
    board, shell = load_models()
    print(f"已只读导入真实裸板和外壳，两个模型均有效。\n模型目录：{output_directory()}")
    print("未启动图形界面；在原生 CadQuery 编辑器中打开本脚本可分别显示或隐藏模型。")
