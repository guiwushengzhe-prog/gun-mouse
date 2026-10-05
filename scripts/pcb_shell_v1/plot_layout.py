"""根据 layout.json 绘制整机侧视布局检查图（系统 Python + matplotlib，不依赖 CadQuery）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUT, load_config, load_geometry, rotate  # noqa: E402


def body_polygon_global(part, geo, cfg):
    """器件本体外廓（来自三维模型）投影到整机 XZ 平面；小板器件返回 None。"""
    g = geo.get(part["lcsc"])
    if not g or part["daughter"]:
        return None
    (x0, x1), (y0, y1) = g["body"]["x"], g["body"]["y"]
    pts = []
    for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        rx, ry = rotate(x, y, part["rot"])
        u, v = part["u"] + rx, part["v"] + ry
        pts.append((-u, v))
    return pts


def plot(layout, cfg, geo, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for name in ["Microsoft YaHei", "SimHei", "SimSun"]:
        if any(name in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.sans-serif"] = [name]
            break
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(13, 11), dpi=110)
    sx, sz = zip(*layout["shell_outline_global"])
    ax.fill(sx, sz, color="#dfe6ee", zorder=0)
    ax.plot(sx + sx[:1], sz + sz[:1], color="#58708a", lw=1.2)
    mx, mz = zip(*layout["main_outline_global"])
    ax.fill(mx, mz, color="#9fd3a8", alpha=0.6, zorder=1)
    ax.plot(mx + mx[:1], mz + mz[:1], color="#1d7a3a", lw=1)
    for c in layout["cutouts"]:
        xs = [-p[0] for p in c["uv"]]
        zs = [p[1] for p in c["uv"]]
        ax.fill(xs, zs, color="white", zorder=2)
    for h in layout["mount_holes"]:
        ax.add_patch(plt.Circle((-h["uv"][0], h["uv"][1]), h["d"] / 2, color="black", zorder=5))
        ax.text(-h["uv"][0] + 1.5, h["uv"][1] + 1.5, h["id"], fontsize=7)
    for p in layout["parts"]:
        poly = body_polygon_global(p, geo, cfg)
        if not poly:
            continue
        xs, zs = zip(*poly)
        big = p["ref"][0] in "JSU" or p["ref"].startswith("USB")
        ax.fill(xs, zs, color="#f2a541" if big else "#c96", alpha=0.75 if big else 0.6, zorder=3)
        if big:
            ax.text(sum(xs) / 4, sum(zs) / 4, p["ref"], fontsize=7, ha="center", va="center", zorder=6)
    # 开发板投影、天线
    dv = cfg["dev_board"]
    fx, ln, wd, cz = dv["board_xz"]["front_x"], dv["board_xz"]["length"], dv["board_xz"]["width"], dv["board_xz"]["center_z"]
    ax.add_patch(plt.Rectangle((fx - ln, cz - wd / 2), ln, wd, fill=False, ec="#2b5fb3", lw=1.5, ls="--", zorder=4))
    ax.add_patch(plt.Rectangle((fx, cz - 9), dv["antenna_overhang"], 18, fill=False, ec="#d0a000", lw=1.5, zorder=4))
    ax.text(fx - ln / 2, cz + wd / 2 + 1, "开发板（插在排母上，元件面朝 +Y）", fontsize=8, color="#2b5fb3", ha="center")
    # 扳机小板（装配位置，侧视为细条）
    d = cfg["board"]["daughter"]
    xt = d["assembled_top_face_x"]
    b0, b1 = d["outline_local"]["b"]
    ax.add_patch(plt.Rectangle((xt - 1.6, b0), 1.6, b1 - b0, color="#7a3db8", zorder=4))
    ax.text(xt - 2, b0 - 3, "扳机小板（YZ 平面）", fontsize=7, color="#7a3db8", ha="center")
    # 电池
    bt = cfg["battery"]
    (bx0, bz0), (bx1, bz1) = bt["pocket_xz_min"], bt["pocket_xz_max"]
    ax.add_patch(plt.Rectangle((bx0, bz0), bx1 - bx0, bz1 - bz0, fill=False, ec="#b03030", lw=1.2, ls=":", zorder=4))
    ax.text((bx0 + bx1) / 2, (bz0 + bz1) / 2, "电池（板背面 -Y）", fontsize=8, color="#b03030", ha="center")
    # 拼板中的小板与邮票孔
    du = [(-u, v) for u, v in layout["daughter_outline_uv"]]
    xs, zs = zip(*du)
    ax.fill(xs, zs, color="#c9b3e6", alpha=0.6, zorder=2)
    ax.text(sum(xs) / 4, sum(zs) / 4, "拼板中的扳机小板", fontsize=7, ha="center")
    for u, v in layout["mousebites_uv"]:
        ax.add_patch(plt.Circle((-u, v), 0.3, color="black", zorder=5))
    js = cfg["joystick"]["shaft_xz"]
    ax.plot(*js, "k+", ms=12)
    ax.set_aspect("equal")
    ax.set_xlabel("X 向前（毫米）")
    ax.set_ylabel("Z 向上（毫米）")
    ax.set_title("PCB-Shell-V1 布局检查（从左侧 +Y 看；绿色为主板，橙色为器件本体）")
    ax.grid(True, lw=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main():
    cfg = load_config()
    layout = json.loads((OUTPUT / "layout.json").read_text(encoding="utf-8"))
    plot(layout, cfg, load_geometry(), OUTPUT / "layout-check.png")
    print(OUTPUT / "layout-check.png")


if __name__ == "__main__":
    main()
