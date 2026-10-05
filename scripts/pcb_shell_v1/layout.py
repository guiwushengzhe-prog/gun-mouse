"""由外壳轮廓与配置计算主板外形、拼板小板、孔位和器件 PCB 坐标，并输出平面检查图。

运行环境：CadQuery（E:\\GunMouseCAD\\CadQuery\\python.exe）。
输出：outputs/pcb-shell-v1/layout.json（检查图由 plot_layout.py 生成）
"""

import math
import sys

import cadquery as cq
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from common import (OUTPUT, fillet_polygon, global_to_uv, load_config, load_geometry,  # noqa: E402
                    part_uv_rot, resolve_lcsc, rotate, write_json)


def face_from_points(points):
    return cq.Face.makeFromWires(cq.Wire.makePolygon([cq.Vector(x, y, 0) for x, y in points], close=True))


def rect(x0, y0, x1, y1):
    return face_from_points([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def sample_wire(wire, step=0.5):
    """按线框顺序逐边离散（直线取端点，圆弧按步长加密），再去掉共线点，得到有序多边形。"""
    from OCP.BRepTools import BRepTools_WireExplorer
    explorer = BRepTools_WireExplorer(wire.wrapped)
    pts = []
    while explorer.More():
        edge = cq.Edge(explorer.Current())
        reverse = explorer.Orientation() == 1  # TopAbs_REVERSED
        n = 1 if edge.geomType() == "LINE" else max(2, int(edge.Length() / step))
        ts = np.linspace(0, 1, n + 1)[:-1]
        if reverse:
            ts = 1 - np.linspace(0, 1, n + 1)[:-1]
        for t in ts:
            p = edge.positionAt(float(t))
            pts.append((round(p.x, 4), round(p.y, 4)))
        explorer.Next()
    return simplify(pts)


def simplify(pts, tol=0.02):
    """去重后用 Douglas–Peucker 精简闭合多边形，最大偏差 tol 毫米。"""
    dedup = []
    for p in pts:
        if not dedup or math.dist(p, dedup[-1]) > 0.02:
            dedup.append(p)
    while len(dedup) > 2 and math.dist(dedup[0], dedup[-1]) <= 0.02:
        dedup.pop()
    if len(dedup) < 4:
        return dedup
    # 以离首点最远的点切成两段开链分别精简
    far = max(range(len(dedup)), key=lambda i: math.dist(dedup[0], dedup[i]))
    first = _rdp(dedup[:far + 1], tol)
    second = _rdp(dedup[far:] + [dedup[0]], tol)
    return first[:-1] + second[:-1]


def _rdp(chain, tol):
    if len(chain) < 3:
        return chain
    a, b = chain[0], chain[-1]
    base = math.dist(a, b)
    best, idx = -1.0, 0
    for i in range(1, len(chain) - 1):
        p = chain[i]
        if base < 1e-12:
            h = math.dist(a, p)
        else:
            h = abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])) / base
        if h > best:
            best, idx = h, i
    if best <= tol:
        return [a, b]
    return _rdp(chain[:idx + 1], tol)[:-1] + _rdp(chain[idx:], tol)


def slab(face):
    """平面面片拉成 1 毫米厚实体，便于可靠的布尔运算（与面片法向无关）。"""
    n = face.normalAt()
    return cq.Solid.extrudeLinear(face, cq.Vector(0, 0, 1 if n.z >= 0 else -1)).translate(
        cq.Vector(0, 0, 0 if n.z >= 0 else 1))


def single_face(solid):
    """取布尔结果的顶面；结果必须是单一连通面。"""
    faces = cq.Workplane().add(solid.clean()).faces(">Z").vals()
    if len(faces) != 1:
        raise RuntimeError(f"合并后顶面有 {len(faces)} 块，期望 1 块")
    return faces[0].translate(cq.Vector(0, 0, -faces[0].Center().z))


def signed_area(pts):
    return 0.5 * sum(pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1] for i in range(len(pts)))


def wires_of(face):
    return face.outerWire(), face.innerWires()


def main_board_face(cfg):
    shell_pts = fillet_polygon(cfg["shell"]["outline_xz"])
    outer = face_from_points(shell_pts)
    inner = outer.outerWire().offset2D(-cfg["board"]["outline_inset_from_shell_outer"], "arc")[0]
    solid = slab(cq.Face.makeFromWires(inner))
    b = cfg["board"]
    solid = solid.cut(slab(rect(b["upper_bar"]["x_max"], -300, 400, 300)))
    tz = b["trigger_zone_z"]
    solid = solid.cut(slab(rect(b["trigger_zone_front_limit_x"], tz[0], 400, b["upper_bar"]["z_min"])))
    pocket = b["bottom_pocket"]
    solid = solid.fuse(slab(rect(pocket["x"][0], pocket["z_board_edge"], pocket["x"][1], -88.0)))
    return shell_pts, single_face(solid)


def build(cfg):
    geo = load_geometry()
    shell_pts, main_face = main_board_face(cfg)
    # 整机 XZ → PCB uv（u = -X）：镜像后外形仍是同一个面
    main_uv = [global_to_uv(x, z) for x, z in sample_wire(main_face.outerWire())]
    face_uv = face_from_points(main_uv)

    d = cfg["board"]["daughter"]
    a0, a1 = d["outline_local"]["a"]
    b0, b1 = d["outline_local"]["b"]
    corners = [rotate(a, bb, d["panel_rotation_deg"]) for a, bb in [(a0, b0), (a1, b0), (a1, b1), (a0, b1)]]
    du, dv = d["panel_origin_uv"]
    db_uv = [(du + x, dv + y) for x, y in corners]
    db_face = face_from_points(db_uv)
    db_top_v = max(p[1] for p in db_uv)
    bar_v = cfg["board"]["upper_bar"]["z_min"]
    tabs, bites, tab_rects = [], [], []
    for tx in d["tabs_x"]:
        u = -tx
        w = d["tab_width"] / 2
        tabs.append(rect(u - w, db_top_v - 0.5, u + w, bar_v + 0.5))
        tab_rects.append([u - w - 0.5, db_top_v - 0.6, u + w + 0.5, bar_v + 0.6])
        for row in (db_top_v + 0.3, bar_v - 0.3):
            for k in range(-2, 3):
                bites.append((round(u + k * d["mousebite_pitch"], 3), round(row, 3)))
    panel = single_face(slab(face_uv).fuse(slab(db_face), *[slab(t) for t in tabs]))
    outline_uv = sample_wire(panel.outerWire())
    if signed_area(outline_uv) < 0:
        outline_uv.reverse()

    cutouts = []
    for s in cfg["board"]["cable_slots"]:
        (x0, z0), (x1, z1) = s["xz_min"], s["xz_max"]
        u0, u1 = sorted((-x0, -x1))
        cutouts.append({"name": s["id"], "uv": [(u0, z0), (u1, z0), (u1, z1), (u0, z1)]})

    holes = [{"id": h["id"], "uv": global_to_uv(*h["xz"]), "d": h["d"]} for h in cfg["board"]["mount_holes"]]
    npth = []
    for p in cfg["parts"]:
        gp = geo.get(resolve_lcsc(cfg, p["lcsc"])) or {}
        for h in gp.get("npth", []):
            u0, v0, rot = part_uv_rot(cfg, p)
            du, dv = rotate(h["x"], h["y"], rot)
            npth.append({"ref": p["ref"], "uv": [round(u0 + du, 4), round(v0 + dv, 4)], "d": h["d"]})

    parts = []
    for p in cfg["parts"]:
        u, v, rot = part_uv_rot(cfg, p)
        lcsc = resolve_lcsc(cfg, p["lcsc"])
        parts.append({"ref": p["ref"], "lcsc": lcsc, "u": round(u, 4), "v": round(v, 4), "rot": rot,
                      "daughter": bool(p.get("daughter")), "nets": p["nets"]})

    keep = cfg["board"]["antenna_copper_keepout_x_min"]
    pour_face = single_face(slab(main_face).cut(slab(rect(keep, -300, 400, 300))))
    pour_uv = [global_to_uv(x, z) for x, z in sample_wire(pour_face.outerWire())]

    layout = {
        "note": "PCB 数据坐标为毫米（Y 向上），u = -X，v = Z；扳机小板已按拼板位置旋转",
        "outline_uv": [list(p) for p in outline_uv],
        "cutouts": cutouts,
        "mount_holes": holes,
        "footprint_npth": npth,
        "mousebites_uv": bites,
        "mousebite_d": d["mousebite_hole_d"],
        "tabs_uv": tab_rects,
        "prerouted_pairs": cfg.get("prerouted_pairs", []),
        "parts": parts,
        "main_outline_global": [list(global_to_uv(u, v)) for u, v in main_uv],
        "daughter_outline_uv": db_uv,
        "shell_outline_global": shell_pts,
        "pour_uv": [list(p) for p in pour_uv],
        "texts": silk_texts(cfg),
    }
    return layout, main_face, geo


def silk_texts(cfg):
    """顶层丝印（整机 XZ 坐标定义，转换为 uv）。字高单位毫米。"""
    t = [
        ("GUN MOUSE MAIN V1 2026-10", (-38.0, -48.0), 1.2, 90),
        ("BAT+ 1  2 GND", (-40.0, -11.0), 0.9, 0),
        ("TOUCH", (-5.0, 21.2), 0.9, 0),
        ("TRIG", (-14.0, -60.5), 0.9, 0),
        ("USB-C", (-37.0, -86.8), 0.9, 0),
        ("PWR 1|3", (-27.5, -87.5), 0.9, 0),
        ("CHG", (-44.5, -86.9), 0.8, 0),
        ("ESP32-S3 DEV BOARD, ANTENNA ->", (31.4, 25.0), 1.2, 0),
    ]
    out = []
    for text, (x, z), size, rot in t:
        u, v = global_to_uv(x, z)
        out.append({"layer": 3, "u": u, "v": v, "text": text, "size": size, "rot": rot})
    d = cfg["board"]["daughter"]
    u, v = daughter_uv(cfg, 4.2, -14.0)
    out.append({"layer": 3, "u": u, "v": v, "text": "TRIG SS-01GL13", "size": 0.9,
                "rot": (90 + d["panel_rotation_deg"]) % 360})
    return out


def daughter_uv(cfg, a, b):
    from common import daughter_ab_to_uv
    return daughter_ab_to_uv(cfg, a, b)


def main():
    cfg = load_config()
    layout, main_face, geo = build(cfg)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT / "layout.json", layout)
    xs = [p[0] for p in layout["outline_uv"]]
    ys = [p[1] for p in layout["outline_uv"]]
    print(f"拼板外形 {max(xs) - min(xs):.1f} × {max(ys) - min(ys):.1f} 毫米，{len(layout['outline_uv'])} 点；"
          f"主板面积 {main_face.Area() / 100:.1f} 平方厘米")


if __name__ == "__main__":
    main()
