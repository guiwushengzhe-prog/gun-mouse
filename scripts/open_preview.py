"""打开可长期复用的 CQ-editor 板壳装配窗口。"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "toolchain-demo",
                        help="包含板、壳和几何报告的生成目录。")
    parser.add_argument("--check-seconds", type=int, default=0,
                        help="实际打开并显示模型后自动退出，用于检查显示入口。")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    output = args.output.resolve()
    snapshot = tempfile.TemporaryDirectory(prefix="gun-mouse-preview-")
    snapshot_dir = Path(snapshot.name)
    os.environ["GUN_MOUSE_PREVIEW_OUTPUT"] = str(snapshot_dir)
    log_dir = ROOT / ".logs"
    log_dir.mkdir(exist_ok=True)
    # Windows 无控制台 Python 的标准输出为空；原生查看器仍需要可写输出。
    if sys.stdout is None:
        sys.stdout = (log_dir / "cq-preview.log").open("a", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = sys.stdout

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QAction, QToolBar

    app = QApplication([sys.argv[0]], applicationName="CQ-editor")
    from cq_editor.main_window import MainWindow

    window = MainWindow(filename=str(ROOT / "scripts" / "view_assembly.py"))
    editor = window.components["editor"]
    debugger = window.components["debugger"]
    viewer = window.components["viewer"]
    editor.autoreload(True)
    for name, panel in window.docks.items():
        panel.setVisible(name == "object_tree")
    window.docks["object_tree"].setWindowTitle("模型：勾选显示，取消勾选隐藏")
    window.setWindowTitle("枪型飞鼠 · 板与外壳装配 · 工具验证示例")
    window.resize(1200, 800)

    toolbar = QToolBar("装配查看", window)
    window.addToolBar(toolbar)
    for label, callback in (
        ("刷新模型", lambda: refresh(force=True)),
        ("恢复全貌", viewer.fit),
        ("斜视", viewer.iso_view),
        ("俯视", viewer.top_view),
    ):
        action = QAction(label, window)
        action.triggered.connect(callback)
        toolbar.addAction(action)

    state = {"renders": 0, "error": None}
    model_paths = [output / name for name in (
        "eda-board-export.step", "outer-shell.step", "geometry-report.json"
    )]

    def model_stamp():
        try:
            stats = [path.stat() for path in model_paths]
            if any(stat.st_size == 0 for stat in stats):
                return None
            if stats[-1].st_mtime_ns < max(stat.st_mtime_ns for stat in stats[:-1]):
                return None
            return tuple((stat.st_mtime_ns, stat.st_size) for stat in stats)
        except OSError:
            return None

    last_stamp = None
    attempt_stamp = None

    def rendered(objects):
        nonlocal last_stamp
        last_stamp = attempt_stamp
        state["renders"] += 1
        state["error"] = None
        state["objects"] = list(objects)
        evidence = {
            "viewer": "CQ-editor",
            "output": str(output),
            "objects": list(objects),
            "render_count": state["renders"],
            "automatic_refresh": "几何报告更新后刷新；查看脚本变更由原生自动重载处理",
            "purpose": "工具联动示例，尚非正式枪形飞鼠设计",
        }
        (output / "preview-state.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        window.update_statusbar("左键拖动旋转；滚轮缩放；右侧勾选显示；模型生成完成后自动刷新")

    def failed(exc_info, script):
        if exc_info:
            state["error"] = str(exc_info[1])
            window.update_statusbar("模型未能加载，请查看错误面板或检查模型文件。")
            window.docks["traceback_viewer"].show()

    def refresh(force=False):
        nonlocal attempt_stamp
        current = model_stamp()
        if current is None:
            window.update_statusbar("等待板和外壳生成完成；已有模型继续保留。")
            return
        if not force and current == last_stamp:
            return
        # 在读取前后核对文件状态；查看器只读取完整且同一批次的私有快照。
        try:
            data = [path.read_bytes() for path in model_paths]
            json.loads(data[-1])
            for model in data[:-1]:
                if not model.startswith(b"ISO-10303-21;") or not model.rstrip().endswith(b"END-ISO-10303-21;"):
                    return
        except (OSError, ValueError):
            return
        if current != model_stamp():
            return
        for path, content in zip(model_paths, data):
            (snapshot_dir / path.name).write_bytes(content)
        attempt_stamp = current
        debugger.render()

    debugger.sigRendered.connect(rendered)
    debugger.sigTraceback.connect(failed)
    editor.triggerRerender.disconnect(debugger.render)
    editor.triggerRerender.connect(lambda _: refresh(force=True))
    timer = QTimer(window)
    timer.setInterval(1000)
    timer.timeout.connect(refresh)
    timer.start()
    window.show()
    QTimer.singleShot(100, refresh)

    if args.check_seconds:
        QTimer.singleShot(args.check_seconds * 1000, window.close)
    result = app.exec_()
    snapshot.cleanup()
    if args.check_seconds and (state["renders"] == 0 or state["error"]):
        raise RuntimeError(state["error"] or "查看窗口没有显示模型。")
    return result


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        detail = traceback.format_exc()
        log_dir = ROOT / ".logs"
        log_dir.mkdir(exist_ok=True)
        (log_dir / "cq-preview-error.log").write_text(detail, encoding="utf-8")
        if sys.stderr is not None:
            print(detail, file=sys.stderr)
        if "--check-seconds" not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                "三维查看未能启动。详细记录：\n" + str(log_dir / "cq-preview-error.log"),
                "枪型飞鼠：三维查看", 0x10,
            )
        sys.exit(1)
