"""最终装配与两件打印壳的核对视图，复用真实OBJ渲染器。"""
import html
import shutil

import render_formal_structure_review as review
from final_regular_layout import OUT, RELEASE


def main():
    review.OUT = OUT
    review.IMAGES = OUT/"多角度检视"
    review.IMAGES.mkdir(parents=True, exist_ok=True)
    parts = review.load_model()
    all_parts = list(parts)
    base, support = ["一体底座"], ["独立摇杆支座"]
    board = [name for name in parts if name.startswith("载板-")]
    jobs = [
        (all_parts, "最终装配_操作面", (1, 1.6, 1.1), "真实主板与器件；八颗小元件已移到支座下方"),
        (all_parts, "最终装配_元件面", (-1, -1.6, 1), "两处摇杆连接柱通到主体；按键、电源与电池位置已配套"),
        (all_parts, "最终装配_正视", (0, 1, 0), "检查小元件分区、两组螺丝及接线孔"),
        (all_parts, "最终装配_侧视", (1, 0, 0), "检查摇杆悬伸、主体支承和电池托"),
        ([*base, *support, *board], "两件壳体与主板", (-1, -1.6, .8), "隐藏器件与五金，查看新增第四个主体固定点"),
        (base, "主体底座_内侧", (1, 1.5, .9), "两根上部柱共同承托摇杆；两根下部柱固定主板"),
        (base, "主体底座_外侧", (-1, -1.5, .9), "平整大面、连续电池托和必要绑带通道"),
        (base, "主体底座_正视", (0, 1, 0), "四处固定点，上部两处与支座共用"),
        (support, "摇杆支座_外侧", (1, 1.5, .9), "两处横向孔统一使用M2×20，孔距14.5毫米"),
        (support, "摇杆支座_内侧", (-1, -1.5, .7), "无焊点区域已补平；只保留五处短脚与螺丝的实际避让"),
        (support, "摇杆支座_底面", (.5, 1.2, -1.2), "两颗M2×10固定模块，保留原生孔距和工具入口"),
        (support, "摇杆支座_端面", (1, 0, 0), "原生小板短脚预留3毫米，主体焊点按4.5毫米包络核对"),
    ]
    images = [review.render(parts, group, i, title, direction, note)
              for i, (group, title, direction, note) in enumerate(jobs, 1)]
    review.sheet(images[:4], "最终装配总览.png", "最终装配｜实际主板、器件与五金")
    review.sheet([images[5], images[6], images[8], images[9]], "最终两件外壳.png", "最终两件外壳｜主体与摇杆支座")
    cards = "".join(f'<a href="多角度检视/{html.escape(path.name)}"><img src="多角度检视/{html.escape(path.name)}"><p>{html.escape(path.stem)}</p></a>' for path in images)
    (OUT/"最终版截图.html").write_text(f'''<!doctype html><meta charset="utf-8"><title>枪型飞鼠最终版</title><style>body{{font:16px "Microsoft YaHei";margin:24px;background:#edf3f7;color:#193748}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:18px}}a{{background:white;border-radius:10px;text-decoration:none;color:inherit}}img{{width:100%}}p{{padding:8px}}</style><h1>最终版装配与独立壳件</h1><p>当前布局与制造文件配套；模型静态核对通过，尚未完成实物试装。完整装配只供查看；上传打印使用交付包里的两个独立STL文件。</p><main>{cards}</main>''', encoding="utf-8")
    view_dir = RELEASE/"装配查看"
    view_dir.mkdir(parents=True, exist_ok=True)
    for file in ("第二代完整装配.obj", "第二代完整装配.mtl"):
        shutil.copy2(OUT/file, view_dir/file)
    for file in ("最终装配总览.png", "最终两件外壳.png"):
        shutil.copy2(review.IMAGES/file, view_dir/file)


if __name__ == "__main__":
    main()
